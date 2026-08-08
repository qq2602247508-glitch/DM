from __future__ import annotations

import hashlib
import os
import re
import secrets
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.schemas import (
    CombatActionCommand,
    CombatDeflectRedirectCommand,
    CombatEffectCommand,
    CombatEffectEndCommand,
    CombatFeatureActionCommand,
    CombatManeuverCommand,
    CombatPreDamageReactionCommand,
    CombatSummonCommand,
    CombatSummonEndCommand,
    DeathSaveCommand,
    PlayerRollResolutionCommand,
    TurnAdvanceCommand,
)
from dnd_dm_assistant.application.rule_block_compiler import (
    compile_rule_blocks_dict,
)
from dnd_dm_assistant.domain.attack_rider import resolve_post_hit_rider
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.character_creation import (
    ability_generation_label,
    validate_ability_generation,
    validate_character_state,
    validate_languages,
)
from dnd_dm_assistant.domain.equipment_rules import equipment_profile
from dnd_dm_assistant.domain.exploration import (
    cover_between,
    grid_distance_ft,
    line_of_sight,
    movement_cost_ft,
)
from dnd_dm_assistant.domain.feature_runtime import (
    compile_feature_runtime_registry,
    feature_block_payloads,
    feature_runtime_action_projections,
)
from dnd_dm_assistant.domain.noncombat_actions import (
    ABILITY_LABELS,
    OBJECT_SKILLS,
    SKILL_RULES,
    SOCIAL_SKILLS,
    grid_range_ft,
    json_dict,
    public_cells,
    roll_save,
    skill_modifier,
)
from dnd_dm_assistant.domain.rule_blocks import (
    DamageBlock,
    TargetBlock,
    TargetCandidate,
    critical_damage_expression,
    explicit_count_outcomes,
    resolve_damage_component_totals,
    resolve_target_selection,
)
from dnd_dm_assistant.domain.spell_rules import upcast_spell_action
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    Campaign,
    Character,
    CharacterCompanion,
    Combat,
    CombatAction,
    Combatant,
    CombatEffect,
    DeathSave,
    EquipmentInstance,
    KnownSpell,
    MonsterInstance,
    PlayerActionRequest,
    PlayerRoom,
    PlayerSession,
    Scene,
    SceneGrid,
    SceneObject,
    SceneParticipant,
    SceneToken,
    ShopInventory,
    SiteConnector,
    SiteLevel,
    VisibilityState,
    WorldItem,
)
from dnd_dm_assistant.infrastructure.database.player_service import PlayerService
from dnd_dm_assistant.infrastructure.database.spell_economy_service import SpellEconomyService

ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _merge_grid_position(
    current: object,
    *,
    row: int,
    col: int,
    requested: object | None = None,
) -> dict[str, int]:
    """Update horizontal coordinates without erasing a creature's height.

    A movement/teleport request normally only carries row/col.  Replacing the
    whole JSON object at those call sites silently put flying creatures back
    on the ground and made the next 3-D area check disagree with the map.
    Explicit vertical coordinates are accepted only when the request includes
    them; otherwise the current elevation is preserved.
    """

    position = dict(current) if isinstance(current, dict) else {}
    position.update({"row": row, "col": col})
    if isinstance(requested, dict):
        for key in ("elevation_ft", "height_ft", "z"):
            value = requested.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                position[key] = value
    return {
        str(key): int(value)
        for key, value in position.items()
        if key in {"row", "col", "elevation_ft", "height_ft", "z"}
        and isinstance(value, int)
        and not isinstance(value, bool)
    }


CORE_SPECIES = {
    "人类",
    "阿斯莫",
    "龙裔",
    "矮人",
    "精灵",
    "侏儒",
    "歌利亚",
    "半身人",
    "兽人",
    "提夫林",
}
CORE_CLASSES = {
    "野蛮人",
    "吟游诗人",
    "牧师",
    "德鲁伊",
    "战士",
    "武僧",
    "圣武士",
    "游侠",
    "游荡者",
    "术士",
    "邪术师",
    "法师",
}
CORE_BACKGROUNDS = {
    "侍僧",
    "工匠",
    "骗子",
    "罪犯",
    "艺人",
    "农夫",
    "守卫",
    "向导",
    "隐士",
    "商人",
    "贵族",
    "学者",
    "水手",
    "书记员",
    "士兵",
    "流浪者",
}
CLASS_HIT_DIE = {
    "野蛮人": 12,
    "战士": 10,
    "圣武士": 10,
    "游侠": 10,
    "吟游诗人": 8,
    "牧师": 8,
    "德鲁伊": 8,
    "武僧": 8,
    "游荡者": 8,
    "邪术师": 8,
    "法师": 6,
    "术士": 6,
}
CLASS_SKILL_SELECTION: dict[str, tuple[int, frozenset[str]]] = {
    "野蛮人": (2, frozenset({"驯兽", "运动", "威吓", "自然", "察觉", "生存"})),
    "吟游诗人": (
        3,
        frozenset(
            {
                "杂技",
                "驯兽",
                "奥秘",
                "运动",
                "欺瞒",
                "历史",
                "洞悉",
                "威吓",
                "调查",
                "医药",
                "自然",
                "察觉",
                "表演",
                "游说",
                "宗教",
                "巧手",
                "隐匿",
                "生存",
            }
        ),
    ),
    "牧师": (2, frozenset({"历史", "洞悉", "医药", "游说", "宗教"})),
    "德鲁伊": (2, frozenset({"驯兽", "奥秘", "洞悉", "医药", "自然", "察觉", "宗教", "生存"})),
    "战士": (
        2,
        frozenset({"杂技", "驯兽", "运动", "历史", "洞悉", "威吓", "察觉", "游说", "生存"}),
    ),
    "武僧": (2, frozenset({"杂技", "运动", "历史", "洞悉", "宗教", "隐匿"})),
    "圣武士": (2, frozenset({"运动", "洞悉", "威吓", "医药", "游说", "宗教"})),
    "游侠": (3, frozenset({"驯兽", "运动", "洞悉", "调查", "自然", "察觉", "隐匿", "生存"})),
    "游荡者": (
        4,
        frozenset({"杂技", "运动", "欺瞒", "洞悉", "威吓", "调查", "察觉", "游说", "巧手", "隐匿"}),
    ),
    "术士": (2, frozenset({"奥秘", "欺瞒", "洞悉", "威吓", "游说", "宗教"})),
    "邪术师": (2, frozenset({"奥秘", "欺瞒", "历史", "威吓", "调查", "自然", "宗教"})),
    "法师": (2, frozenset({"奥秘", "历史", "洞悉", "调查", "医药", "自然", "宗教"})),
}
SPELL_SELECTION_2024: dict[str, tuple[int, int]] = {
    "吟游诗人": (2, 4),
    "牧师": (3, 4),
    "德鲁伊": (2, 4),
    "圣武士": (0, 2),
    "游侠": (0, 2),
    "术士": (4, 2),
    "邪术师": (2, 2),
    "法师": (3, 6),
}
CLASS_ACTION = {
    "野蛮人": {
        "name": "巨斧",
        "description": "近战武器攻击",
        "damage": "1d12+力量",
        "damage_type": "挥砍",
        "range": "5尺",
        "cost": "动作",
    },
    "战士": {
        "name": "长剑",
        "description": "近战武器攻击",
        "damage": "1d8+力量",
        "damage_type": "挥砍",
        "range": "5尺",
        "cost": "动作",
    },
    "圣武士": {
        "name": "长剑",
        "description": "近战武器攻击",
        "damage": "1d8+力量",
        "damage_type": "挥砍",
        "range": "5尺",
        "cost": "动作",
    },
    "游侠": {
        "name": "长弓",
        "description": "远程武器攻击",
        "damage": "1d8+敏捷",
        "damage_type": "穿刺",
        "range": "150尺",
        "cost": "动作",
    },
    "游荡者": {
        "name": "短弓",
        "description": "远程武器攻击",
        "damage": "1d6+敏捷",
        "damage_type": "穿刺",
        "range": "80尺",
        "cost": "动作",
    },
}
SPECIES_RULES: dict[str, dict[str, Any]] = {
    "阿斯莫": {
        "speed": 30,
        "features": ["黑暗视觉", "天界抗性", "治疗之手", "天界显现"],
    },
    "龙裔": {
        "speed": 30,
        "features": ["龙族血统", "吐息武器", "伤害抗性", "黑暗视觉"],
    },
    "矮人": {
        "speed": 30,
        "features": ["黑暗视觉", "矮人韧性", "石中感知", "坚韧生命"],
    },
    "精灵": {
        "speed": 30,
        "features": ["黑暗视觉", "精类血统", "敏锐感官", "出神"],
    },
    "侏儒": {"speed": 30, "features": ["黑暗视觉", "侏儒狡黠", "侏儒血统"]},
    "歌利亚": {"speed": 35, "features": ["巨人血统", "大体格", "强力体格"]},
    "半身人": {
        "speed": 30,
        "features": ["勇敢", "半身人灵巧", "幸运", "天生隐匿"],
    },
    "人类": {"speed": 30, "features": ["足智多谋", "技艺精通", "多才多艺"]},
    "兽人": {"speed": 30, "features": ["肾上腺素爆发", "黑暗视觉", "不屈耐力"]},
    "提夫林": {"speed": 30, "features": ["黑暗视觉", "异界遗产", "异界风采"]},
}
BACKGROUND_RULES: dict[str, dict[str, Any]] = {
    "侍僧": {
        "skills": ["洞悉", "宗教"],
        "feat": "魔法学徒（牧师）",
        "equipment": ["圣徽", "祈祷书", "长袍"],
    },
    "工匠": {
        "skills": ["调查", "游说"],
        "feat": "工匠",
        "equipment": ["工匠工具", "旅行者服装"],
    },
    "骗子": {
        "skills": ["欺瞒", "巧手"],
        "feat": "熟练",
        "equipment": ["伪装工具", "精美服装"],
    },
    "罪犯": {
        "skills": ["巧手", "隐匿"],
        "feat": "警觉",
        "equipment": ["盗贼工具", "两把匕首"],
    },
    "艺人": {
        "skills": ["杂技", "表演"],
        "feat": "音乐家",
        "equipment": ["乐器", "戏服"],
    },
    "农夫": {
        "skills": ["驯兽", "自然"],
        "feat": "健壮",
        "equipment": ["镰刀", "治疗包"],
    },
    "守卫": {
        "skills": ["运动", "察觉"],
        "feat": "警觉",
        "equipment": ["长矛", "轻弩"],
    },
    "向导": {
        "skills": ["隐匿", "生存"],
        "feat": "魔法学徒（德鲁伊）",
        "equipment": ["短弓", "制图工具"],
    },
    "隐士": {
        "skills": ["医药", "宗教"],
        "feat": "治疗者",
        "equipment": ["治疗包", "草药工具"],
    },
    "商人": {
        "skills": ["驯兽", "游说"],
        "feat": "幸运",
        "equipment": ["导航工具", "旅行者服装"],
    },
    "贵族": {
        "skills": ["历史", "游说"],
        "feat": "熟练",
        "equipment": ["精美服装", "游戏套组"],
    },
    "学者": {
        "skills": ["奥秘", "历史"],
        "feat": "魔法学徒（法师）",
        "equipment": ["法杖", "书法工具"],
    },
    "水手": {
        "skills": ["杂技", "察觉"],
        "feat": "酒馆斗殴者",
        "equipment": ["匕首", "导航工具"],
    },
    "书记员": {
        "skills": ["调查", "察觉"],
        "feat": "熟练",
        "equipment": ["书法工具", "羊皮纸"],
    },
    "士兵": {
        "skills": ["运动", "威吓"],
        "feat": "凶蛮打手",
        "equipment": ["长矛", "短弓"],
    },
    "流浪者": {
        "skills": ["洞悉", "隐匿"],
        "feat": "幸运",
        "equipment": ["匕首", "盗贼工具"],
    },
}
BACKGROUND_CREATION_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "侍僧": {
        "ability_options": ("intelligence", "wisdom", "charisma"),
        "tool_choices": ("书法工具",),
    },
    "工匠": {
        "ability_options": ("strength", "dexterity", "intelligence"),
        "tool_choices": (
            "炼金工具",
            "酿酒工具",
            "书法工具",
            "木匠工具",
            "制图工具",
            "鞋匠工具",
            "厨师工具",
            "玻璃工具",
            "珠宝工具",
            "皮匠工具",
            "石匠工具",
            "绘画工具",
            "陶匠工具",
            "铁匠工具",
            "修补工具",
            "织布工具",
            "木雕工具",
        ),
    },
    "骗子": {
        "ability_options": ("dexterity", "constitution", "charisma"),
        "tool_choices": ("伪装工具",),
    },
    "罪犯": {
        "ability_options": ("dexterity", "constitution", "intelligence"),
        "tool_choices": ("盗贼工具",),
    },
    "艺人": {
        "ability_options": ("dexterity", "intelligence", "charisma"),
        "tool_choices": ("乐器",),
    },
    "农夫": {
        "ability_options": ("strength", "constitution", "wisdom"),
        "tool_choices": ("木匠工具",),
    },
    "守卫": {
        "ability_options": ("strength", "intelligence", "wisdom"),
        "tool_choices": ("游戏套组",),
    },
    "向导": {
        "ability_options": ("dexterity", "constitution", "wisdom"),
        "tool_choices": ("制图工具",),
    },
    "隐士": {
        "ability_options": ("constitution", "wisdom", "charisma"),
        "tool_choices": ("草药工具",),
    },
    "商人": {
        "ability_options": ("constitution", "intelligence", "charisma"),
        "tool_choices": ("导航工具",),
    },
    "贵族": {
        "ability_options": ("strength", "intelligence", "charisma"),
        "tool_choices": ("游戏套组",),
    },
    "学者": {
        "ability_options": ("constitution", "intelligence", "wisdom"),
        "tool_choices": ("书法工具",),
    },
    "水手": {
        "ability_options": ("strength", "dexterity", "wisdom"),
        "tool_choices": ("导航工具",),
    },
    "书记员": {
        "ability_options": ("dexterity", "intelligence", "wisdom"),
        "tool_choices": ("书法工具",),
    },
    "士兵": {
        "ability_options": ("strength", "dexterity", "constitution"),
        "tool_choices": ("游戏套组",),
    },
    "流浪者": {
        "ability_options": ("dexterity", "wisdom", "charisma"),
        "tool_choices": ("盗贼工具",),
    },
}
CLASS_RULES: dict[str, dict[str, Any]] = {
    "野蛮人": {
        "saves": ["力量", "体质"],
        "skills": ["运动", "生存"],
        "proficiencies": ["轻甲", "中甲", "盾牌", "军用武器"],
        "equipment": ["巨斧", "四把手斧", "探索套组"],
        "actions": [
            CLASS_ACTION["野蛮人"],
            {
                "name": "狂暴",
                "description": "进入狂暴并获得对应增益",
                "cost": "附赠动作",
                "resource": "rage",
            },
        ],
        "resources": {
            "rage": {
                "label": "狂暴",
                "current": 2,
                "max": 2,
                "recovery": "long_rest",
            }
        },
    },
    "吟游诗人": {
        "saves": ["敏捷", "魅力"],
        "skills": ["表演", "游说", "洞悉"],
        "proficiencies": ["简易武器", "轻甲", "乐器"],
        "equipment": ["细剑", "乐器", "艺人套组"],
        "actions": [
            {
                "name": "细剑",
                "description": "灵巧近战攻击",
                "damage": "1d8+敏捷 穿刺",
                "range": "5尺",
                "cost": "动作",
            },
            {
                "name": "吟游诗人激励",
                "description": "给予盟友一枚激励骰",
                "cost": "附赠动作",
                "resource": "bardic_inspiration",
            },
        ],
        "resources": {
            "bardic_inspiration": {
                "label": "诗人激励",
                "current": 2,
                "max": 2,
                "recovery": "long_rest",
            }
        },
        "spellcasting": {"ability": "魅力", "mode": "slots", "level1Slots": 2},
    },
    "牧师": {
        "saves": ["感知", "魅力"],
        "skills": ["洞悉", "宗教"],
        "proficiencies": ["轻甲", "中甲", "盾牌", "简易武器"],
        "equipment": ["硬头锤", "鳞甲", "盾牌", "圣徽"],
        "actions": [
            {
                "name": "硬头锤",
                "description": "近战武器攻击",
                "damage": "1d6+力量 钝击",
                "range": "5尺",
                "cost": "动作",
            }
        ],
        "resources": {
            "channel_divinity": {
                "label": "引导神力",
                "current": 2,
                "max": 2,
                "recovery": "short_rest",
            }
        },
        "spellcasting": {"ability": "感知", "mode": "slots", "level1Slots": 2},
    },
    "德鲁伊": {
        "saves": ["智力", "感知"],
        "skills": ["自然", "生存"],
        "proficiencies": ["轻甲", "盾牌", "简易武器", "草药工具"],
        "equipment": ["木盾", "短棍", "德鲁伊法器"],
        "actions": [
            {
                "name": "短棍",
                "description": "近战武器攻击",
                "damage": "1d6+力量 钝击",
                "range": "5尺",
                "cost": "动作",
            }
        ],
        "resources": {
            "wild_shape": {
                "label": "荒野形态",
                "current": 2,
                "max": 2,
                "recovery": "short_rest",
            }
        },
        "spellcasting": {"ability": "感知", "mode": "slots", "level1Slots": 2},
    },
    "战士": {
        "saves": ["力量", "体质"],
        "skills": ["运动", "察觉"],
        "proficiencies": ["所有护甲", "盾牌", "简易武器", "军用武器"],
        "equipment": ["长剑", "盾牌", "链甲", "轻弩"],
        "actions": [
            CLASS_ACTION["战士"],
            {
                "name": "第二风息",
                "description": "恢复1d10+战士等级生命值",
                "damage": "治疗1d10+1",
                "range": "自身",
                "cost": "附赠动作",
                "resource": "second_wind",
            },
        ],
        "resources": {
            "second_wind": {
                "label": "第二风息",
                "current": 2,
                "max": 2,
                "recovery": "short_rest",
            }
        },
    },
    "武僧": {
        "saves": ["力量", "敏捷"],
        "skills": ["杂技", "洞悉"],
        "proficiencies": ["简易武器", "轻型军用武器"],
        "equipment": ["短剑", "探索套组"],
        "actions": [
            {
                "name": "徒手打击",
                "description": "近战攻击",
                "damage": "1d6+敏捷 钝击",
                "range": "5尺",
                "cost": "动作或附赠动作",
            }
        ],
        "resources": {
            "focus": {
                "label": "专注点",
                "current": 1,
                "max": 1,
                "recovery": "short_rest",
            }
        },
    },
    "圣武士": {
        "saves": ["感知", "魅力"],
        "skills": ["运动", "游说"],
        "proficiencies": ["所有护甲", "盾牌", "简易武器", "军用武器"],
        "equipment": ["长剑", "盾牌", "链甲", "圣徽"],
        "actions": [
            CLASS_ACTION["圣武士"],
            {
                "name": "圣疗",
                "description": "从圣疗池恢复生命",
                "range": "接触",
                "cost": "附赠动作",
                "resource": "lay_on_hands",
            },
        ],
        "resources": {
            "lay_on_hands": {
                "label": "圣疗池",
                "current": 5,
                "max": 5,
                "recovery": "long_rest",
            }
        },
        "spellcasting": {"ability": "魅力", "mode": "slots", "level1Slots": 2},
    },
    "游侠": {
        "saves": ["力量", "敏捷"],
        "skills": ["自然", "生存", "察觉"],
        "proficiencies": ["轻甲", "中甲", "盾牌", "军用武器"],
        "equipment": ["长弓", "两把短剑", "探索套组"],
        "actions": [CLASS_ACTION["游侠"]],
        "resources": {},
        "spellcasting": {"ability": "感知", "mode": "slots", "level1Slots": 2},
    },
    "游荡者": {
        "saves": ["敏捷", "智力"],
        "skills": ["隐匿", "巧手", "察觉", "调查"],
        "proficiencies": ["轻甲", "简易武器", "灵巧武器", "盗贼工具"],
        "equipment": ["细剑", "短弓", "盗贼工具"],
        "actions": [
            {
                "name": "细剑",
                "description": "灵巧近战攻击",
                "damage": "1d8+敏捷 穿刺",
                "range": "5尺",
                "cost": "动作",
            },
            {
                "name": "偷袭",
                "description": "满足条件时额外造成伤害",
                "damage": "+1d6",
                "range": "武器射程",
                "cost": "每回合一次",
            },
        ],
        "resources": {},
    },
    "术士": {
        "saves": ["体质", "魅力"],
        "skills": ["奥秘", "游说"],
        "proficiencies": ["简易武器"],
        "equipment": ["轻弩", "奥术法器", "探索套组"],
        "actions": [
            {
                "name": "火焰箭",
                "description": "远程法术攻击",
                "damage": "1d10 火焰",
                "range": "120尺",
                "cost": "动作",
            }
        ],
        "resources": {},
        "spellcasting": {"ability": "魅力", "mode": "slots", "level1Slots": 2},
    },
    "邪术师": {
        "saves": ["感知", "魅力"],
        "skills": ["奥秘", "欺瞒"],
        "proficiencies": ["轻甲", "简易武器"],
        "equipment": ["轻弩", "奥术法器", "学者套组"],
        "actions": [
            {
                "name": "魔能爆",
                "description": "远程法术攻击",
                "damage": "1d10 力场",
                "range": "120尺",
                "cost": "动作",
            }
        ],
        "resources": {
            "pact_slots": {
                "label": "契约魔法位",
                "current": 1,
                "max": 1,
                "recovery": "short_rest",
            }
        },
        "spellcasting": {"ability": "魅力", "mode": "slots", "level1Slots": 1},
    },
    "法师": {
        "saves": ["智力", "感知"],
        "skills": ["奥秘", "调查"],
        "proficiencies": ["简易武器"],
        "equipment": ["法杖", "法术书", "学者套组"],
        "actions": [
            {
                "name": "火焰箭",
                "description": "远程法术攻击",
                "damage": "1d10 火焰",
                "range": "120尺",
                "cost": "动作",
            }
        ],
        "resources": {
            "arcane_recovery": {
                "label": "奥术恢复",
                "current": 1,
                "max": 1,
                "recovery": "long_rest",
            }
        },
        "spellcasting": {"ability": "智力", "mode": "slots", "level1Slots": 2},
    },
}


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _code_digest(value: str, salt_hex: str) -> str:
    """Slow, salted hash for a low-entropy human-readable room code."""

    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError as exc:
        raise ValueError("player room code salt is invalid") from exc
    return hashlib.scrypt(
        value.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    ).hex()


def _code() -> str:
    return "D" + "".join(secrets.choice(ROOM_ALPHABET) for _ in range(5))


def _token() -> str:
    return secrets.token_urlsafe(32)


def _private_ipv4() -> list[str]:
    addresses: set[str] = set()
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("10.255.255.255", 1))
        addresses.add(str(probe.getsockname()[0]))
        probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(str(info[4][0]))
    except OSError:
        pass
    return sorted(
        address
        for address in addresses
        if address != "127.0.0.1" and not address.startswith("169.254.")
    )


def _gateway_port() -> int:
    raw = os.environ.get("DND_DM_PLAYER_GATEWAY_PORT", "8787")
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError("DND_DM_PLAYER_GATEWAY_PORT must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise ValueError("DND_DM_PLAYER_GATEWAY_PORT must be between 1 and 65535")
    return port


def _grid_line(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Return a deterministic adjacent-cell line, including both endpoints."""

    row, col = start
    end_row, end_col = end
    result = [(row, col)]
    while (row, col) != (end_row, end_col):
        if row != end_row:
            row += 1 if end_row > row else -1
        if col != end_col:
            col += 1 if end_col > col else -1
        result.append((row, col))
    return result


def _object_cells(item: SceneObject) -> set[tuple[int, int]]:
    return {
        (row, col)
        for row in range(item.row, item.row + item.height_cells)
        for col in range(item.col, item.col + item.width_cells)
    }


@dataclass(frozen=True)
class PlayerPrincipal:
    room_id: str
    campaign_id: str
    session_id: str
    display_name: str
    character_id: str | None


class PlayerRoomService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.player = PlayerService(engine)
        self.combat = CombatEngineService(engine)
        self.economy = SpellEconomyService(engine)

    @staticmethod
    def _combatant_owner(combatant: Combatant) -> str | None:
        if combatant.entity_type == "character":
            return combatant.entity_id
        raw = combatant.snapshot_json.get("owner_character_id")
        return str(raw) if raw else None

    @classmethod
    def _is_player_controlled(cls, combatant: Combatant, character_id: str | None) -> bool:
        if character_id is None:
            return False
        if combatant.entity_type == "character":
            return combatant.entity_id == character_id
        return (
            combatant.entity_type == "companion"
            and combatant.snapshot_json.get("controller") == "player"
            and cls._combatant_owner(combatant) == character_id
        )

    @classmethod
    def _controlled_actor(
        cls,
        fighters: list[Combatant],
        active: Combatant | None,
        character_id: str | None,
    ) -> Combatant | None:
        if active is None or not cls._is_player_controlled(active, character_id):
            return None
        return active

    @staticmethod
    def _combatant_faction(combatant: Combatant) -> str:
        raw = combatant.snapshot_json.get("disposition")
        if raw in {"ally", "enemy"}:
            return str(raw)
        if combatant.entity_type in {"character", "companion"}:
            return "ally"
        return "enemy"

    @staticmethod
    def _is_enemy_ai_controlled(combatant: Combatant) -> bool:
        """Match the DM summon AI opt-in used by MonsterAIService.

        A player-room snapshot must publish the same active action/range that
        the DM console is previewing.  Do not expose a friendly DM companion
        as an enemy AI actor merely because it is not player-controlled.
        """
        if combatant.entity_type == "monster":
            return True
        state = dict(combatant.snapshot_json or {})
        return (
            combatant.entity_type == "companion"
            and state.get("controller") == "dm"
            and state.get("disposition") == "enemy"
            and state.get("enemy_ai_mode") == "basic"
        )

    @staticmethod
    def _rule_modifier(
        combatant: Combatant,
        stat: str,
        *,
        scope: str,
        skill: str | None = None,
        session: Session | None = None,
        combat_id: str | None = None,
    ) -> tuple[int, bool, bool]:
        """Read compiled numeric/advantage modifiers from a combat snapshot."""

        raw = combatant.snapshot_json.get("rule_modifiers")
        if not isinstance(raw, dict):
            raw = {}
        numeric = 0
        advantage = False
        disadvantage = False
        proficiency_applied = False
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            parts = str(key).split(":", 2)
            if not parts or parts[0] != stat:
                continue
            modifier_scope = parts[1] if len(parts) > 1 else "all"
            modifier_skill = parts[2] if len(parts) > 2 else ""
            if modifier_skill.startswith(":"):
                # Hydrated feature keys reserve the third segment for an
                # optional skill and put the projection index after it:
                # ``saving_throw:self::0``.  That is a self-wide modifier,
                # not a skill named ``:0``.
                modifier_skill = ""
            if modifier_scope not in {"all", scope}:
                continue
            if skill is not None and modifier_skill not in {"", skill}:
                continue
            # Typed feature modifiers carry their own state predicate.  The
            # legacy player helper used to consume the flattened dictionary
            # without evaluating that predicate, which made conditional
            # bonuses permanent on the player endpoint.
            if isinstance(value.get("stat"), str):
                eligible = CombatEngineService._feature_rule_modifiers(
                    combatant,
                    stat=stat,
                    scope=scope,
                    ability=skill if stat == "saving_throw" else None,
                )
                if not any(item is value for item in eligible):
                    continue
            operation = str(value.get("operation") or "")
            raw_value = value.get("value")
            if operation == "add" and isinstance(raw_value, int):
                numeric += raw_value
            elif operation == "grant_proficiency" and stat == "saving_throw":
                if proficiency_applied:
                    continue
                runtime = combatant.snapshot_json.get("feature_runtime")
                progression = runtime.get("progression") if isinstance(runtime, dict) else None
                proficiency_bonus = (
                    progression.get("proficiency_bonus")
                    if isinstance(progression, dict)
                    else None
                )
                if isinstance(proficiency_bonus, int) and proficiency_bonus > 0:
                    numeric += proficiency_bonus
                    proficiency_applied = True
            elif operation == "advantage":
                advantage = True
            elif operation == "disadvantage":
                disadvantage = True
        if stat == "saving_throw":
            numeric += PlayerRoomService._aura_saving_throw_modifier(
                combatant,
                session=session,
                combat_id=combat_id,
            )
        return numeric, advantage, disadvantage

    @staticmethod
    def _aura_saving_throw_modifier(
        target: Combatant,
        *,
        session: Session | None,
        combat_id: str | None,
    ) -> int:
        return CombatEngineService._ranged_passive_numeric_modifier(
            target,
            stat="saving_throw",
            session=session,
            combat_id=combat_id,
        )

    @staticmethod
    def _feature_additive_modifier(
        combatant: Combatant,
        stat: str,
        *,
        scope: str,
    ) -> int:
        """Consume an active typed numeric feature modifier on the player path."""

        return sum(
            int(item.get("value") or 0)
            for item in CombatEngineService._feature_rule_modifiers(
                combatant,
                stat=stat,
                scope=scope,
            )
            if item.get("operation") == "add"
            and isinstance(item.get("value"), int)
        )

    @staticmethod
    def _reliable_talent_applies(character: Character, skill: str) -> bool:
        """Return whether Reliable Talent can floor this skill check's d20."""

        feature_names = {
            "可靠才能",
            "可靠天赋",
            "reliabletalent",
        }
        for raw_feature in character.features or []:
            name = (
                raw_feature.get("name")
                if isinstance(raw_feature, dict)
                else str(raw_feature)
            )
            normalized = str(name or "").strip().lower().replace(" ", "")
            if normalized in {item.lower() for item in feature_names}:
                skill_data = (character.skills or {}).get(skill)
                return isinstance(skill_data, dict) and bool(
                    skill_data.get("proficient")
                )
        return False

    @staticmethod
    def _condition_attack_context(
        actor: Combatant,
        target: Combatant,
        *,
        distance_ft: int | None,
        target_dodging: bool = False,
        action: dict[str, Any] | None = None,
        session: Session | None = None,
        combat_id: str | None = None,
    ) -> tuple[str, bool, bool, bool]:
        """Resolve the deterministic attack consequences of core conditions."""

        advantage: list[str] = []
        disadvantage: list[str] = []
        automatic_critical = False
        action_data = action if isinstance(action, dict) else {}
        if CombatEngineService._has_condition(actor, "prone"):
            disadvantage.append("攻击者倒地")
        for condition, label in (
            ("blinded", "攻击者目盲"),
            ("poisoned", "攻击者中毒"),
            ("restrained", "攻击者束缚"),
            ("frightened", "攻击者恐慌"),
        ):
            if CombatEngineService._has_condition(actor, condition):
                disadvantage.append(label)
        if CombatEngineService._has_condition(actor, "invisible"):
            advantage.append("攻击者隐形")
        if CombatEngineService._has_condition(actor, "reckless_attack"):
            attack_ability = str(
                action_data.get("attack_ability") or action_data.get("ability") or ""
            ).strip().lower()
            action_text = " ".join(
                str(action_data.get(key) or "")
                for key in ("name", "description", "action_name")
            ).lower()
            is_weapon_attack = bool(
                action_data.get("is_weapon_attack") is True
                or "武器攻击" in action_text
                or "近战攻击" in action_text
                or "weapon attack" in action_text
            )
            if attack_ability in {"strength", "力量"} and is_weapon_attack:
                advantage.append("攻击者鲁莽攻击")
        is_spell_attack = bool(
            action_data.get("is_spell_attack") is True
            or action_data.get("is_spell") is True
            or action_data.get("kind") == "spell"
            or action_data.get("spell_level") is not None
        )
        spellcasting_class = str(
            action_data.get("spellcasting_class")
            or action_data.get("class_name")
            or ""
        ).strip().lower()
        is_sorcerer_spell = spellcasting_class in {"术士", "sorcerer"}
        for modifier in CombatEngineService._feature_rule_modifiers(
            actor,
            stat="attack_roll",
            scope="outgoing",
        ):
            if (
                str(modifier.get("applies_when") or "").strip().lower()
                == "innate_sorcery_active_and_sorcerer_spell"
                and is_spell_attack
                and is_sorcerer_spell
                and modifier.get("operation") == "advantage"
            ):
                advantage.append(str(modifier.get("source") or "先天术法"))
        steady_aim_active = (
            session is not None
            and combat_id is not None
            and CombatEngineService._active_runtime_effects(
                session,
                combat_id,
                target_id=actor.id,
                state_name="steady_aim",
            )
        )
        if steady_aim_active:
            advantage.append("攻击者稳定瞄准")
        if (
            session is not None
            and combat_id is not None
            and CombatEngineService._active_studied_attack_effect(
                session,
                combat_id,
                actor_id=actor.id,
                target_id=target.id,
            )
            is not None
        ):
            advantage.append("究明攻击")
        if session is not None and combat_id is not None:
            incoming_advantage = CombatEngineService._active_runtime_modifier_effects(
                session,
                combat_id,
                target_id=target.id,
                stat="attack_roll",
                scope="incoming",
            )
            if any(
                (CombatEngineService._runtime_state(effect) or {})
                .get("modifier", {})
                .get("operation")
                == "advantage"
                for effect in incoming_advantage
            ):
                advantage.append("命中后效果：下一次攻击具有优势")
        for condition, label in (
            ("blinded", "目标目盲"),
            ("restrained", "目标束缚"),
            ("stunned", "目标震慑"),
            ("paralyzed", "目标麻痹"),
            ("petrified", "目标石化"),
            ("unconscious", "目标昏迷"),
        ):
            if CombatEngineService._has_condition(target, condition):
                advantage.append(label)
        if CombatEngineService._has_condition(target, "invisible"):
            disadvantage.append("目标隐形")
        if CombatEngineService._has_condition(target, "prone"):
            if distance_ft is not None and distance_ft <= 5:
                advantage.append("近距离攻击倒地目标")
            else:
                disadvantage.append("远距离攻击倒地目标")
        if target_dodging:
            disadvantage.append("目标闪避")
        if CombatEngineService._has_condition(target, "reckless_attack"):
            advantage.append("目标鲁莽攻击")
        if CombatEngineService._suppresses_incoming_attack_advantage(target):
            advantage.clear()
        if (
            distance_ft is not None
            and distance_ft <= 5
            and (
                CombatEngineService._has_condition(target, "paralyzed")
                or CombatEngineService._has_condition(target, "unconscious")
            )
        ):
            automatic_critical = True
        mode = "normal"
        if advantage and not disadvantage:
            mode = "advantage"
        elif disadvantage and not advantage:
            mode = "disadvantage"
        # Unconscious is not itself an advantage source in the condition
        # matrix, but it still makes a hit from within 5 feet a critical hit.
        # Do not gate this independent rule on ``reasons``; otherwise a lone
        # unconscious target silently loses the automatic-critical rule.
        return mode, bool(advantage), bool(disadvantage), automatic_critical

    @staticmethod
    def _action_rule_blocks(action: dict[str, Any]) -> list[dict[str, Any]]:
        raw_plan = action.get("rule_plan")
        if not isinstance(raw_plan, dict):
            raw_plan = compile_rule_blocks_dict(
                action,
                source_kind="spell" if action.get("spell_level") is not None else "action",
            )
            action["rule_plan"] = raw_plan
        raw_blocks = raw_plan.get("blocks")
        if not isinstance(raw_blocks, list):
            raise ValueError("该动作的规则计划无效，无法自动结算")
        return [block for block in raw_blocks if isinstance(block, dict)]

    @staticmethod
    def _attack_rider_total(
        rider: dict[str, Any],
        *,
        special_inputs: dict[str, Any],
        critical_hit: bool,
    ) -> tuple[int, dict[str, Any]] | None:
        """Validate one compiled attack rider without rolling on the server.

        Fixed riders such as Rage's ``+4`` are deterministic.  Dice riders
        (Sneak Attack, Divine Smite dice supplied by a future registry entry,
        and similar features) must arrive as an explicit player-reported total
        under ``attack_rider_totals``.  The engine never invents a dice result.
        """

        rider_id = str(rider.get("id") or "").strip()
        if not rider_id:
            return None
        raw_value = str(rider.get("value") or rider.get("expression") or "").strip()
        if not raw_value:
            raise ValueError(f"攻击附伤 {rider_id} 缺少明确骰式或固定数值")
        normalized = raw_value.replace(" ", "")
        match = re.fullmatch(r"\+?(?:(\d*)d(\d+)([+-]\d+)?|(\d+))", normalized, re.I)
        if match is None:
            raise ValueError(f"攻击附伤 {rider_id} 的骰式无法自动解析：{raw_value}")
        dice_count = int(match.group(1) or 0)
        sides = int(match.group(2) or 0)
        modifier = int(match.group(3) or 0) if match.group(3) else int(match.group(4) or 0)
        raw_totals = special_inputs.get("attack_rider_totals")
        totals = raw_totals if isinstance(raw_totals, dict) else {}
        if dice_count:
            reported = totals.get(rider_id)
            if isinstance(reported, bool) or not isinstance(reported, (int, float)):
                raise ValueError(f"必须提交攻击附伤 {rider_id} 的伤害骰最终总值（{raw_value}）")
            total = int(reported)
            expected_dice = dice_count * (2 if critical_hit else 1)
            minimum = expected_dice + modifier
            maximum = expected_dice * sides + modifier
            if not minimum <= total <= maximum:
                raise ValueError(
                    f"攻击附伤 {rider_id} 的伤害骰结果应在 {minimum}–{maximum} 之间"
                )
            return total, {
                "rider_id": rider_id,
                "expression": raw_value,
                "reported_total": total,
                "dice": True,
            }
        total = modifier
        if total < 0:
            raise ValueError(f"攻击附伤 {rider_id} 的固定值不能为负数")
        return total, {
            "rider_id": rider_id,
            "expression": raw_value,
            "reported_total": total,
            "dice": False,
        }

    @classmethod
    def _eligible_attack_riders(
        cls,
        actor: Combatant,
        action: dict[str, Any],
        target: Combatant,
        *,
        special_inputs: dict[str, Any],
        critical_hit: bool,
        used_this_turn: set[str],
        event_id: str | None = None,
        turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return only riders whose trigger is explicit or mechanically known."""

        registry = actor.snapshot_json.get("feature_runtime")
        raw_riders = registry.get("attack_riders") if isinstance(registry, dict) else None
        canonical_riders = (
            feature_block_payloads(registry, "attack_rider")
            if isinstance(registry, dict)
            else []
        )
        riders = list(canonical_riders)
        canonical_ids = {
            str(item.get("id") or "") for item in canonical_riders if isinstance(item, dict)
        }
        riders.extend(
            item
            for item in (raw_riders if isinstance(raw_riders, list) else [])
            if isinstance(item, dict) and str(item.get("id") or "") not in canonical_ids
        )
        action_text = " ".join(
            str(action.get(key) or "") for key in ("name", "description", "damage")
        )
        attack_ability = str(
            action.get("attack_ability") or action.get("ability") or ""
        ).lower()
        is_strength_attack = attack_ability in {"strength", "力量"} or "力量" in action_text
        is_weapon_attack = bool(
            action.get("is_weapon_attack") is True
            or "武器攻击" in action_text
            or "近战攻击" in action_text
            or "远程攻击" in action_text
        )
        raw_eligibility = special_inputs.get("attack_rider_eligibility")
        eligibility = raw_eligibility if isinstance(raw_eligibility, dict) else {}
        result: list[dict[str, Any]] = []
        for raw in riders:
            if not isinstance(raw, dict):
                continue
            rider_id = str(raw.get("id") or "").strip()
            if not rider_id or rider_id in used_this_turn:
                continue
            if raw.get("kind") == "post_hit_rider":
                raw_inputs_by_rider = special_inputs.get("post_hit_rider_inputs")
                inputs_by_rider = (
                    raw_inputs_by_rider if isinstance(raw_inputs_by_rider, dict) else {}
                )
                raw_inputs = inputs_by_rider.get(rider_id)
                rider_inputs = dict(raw_inputs) if isinstance(raw_inputs, dict) else {}
                # Compatibility adapter for clients that submitted the old
                # flat attack_rider_totals shape.  It translates input only;
                # eligibility and execution remain in the generic resolver.
                legacy_totals = special_inputs.get("attack_rider_totals")
                legacy_total = (
                    legacy_totals.get(rider_id)
                    if isinstance(legacy_totals, dict)
                    else None
                )
                raw_damage = raw.get("damage")
                damage_entries = raw_damage if isinstance(raw_damage, list) else [raw_damage]
                if legacy_total is not None and not rider_inputs:
                    for damage_entry in damage_entries:
                        if isinstance(damage_entry, dict):
                            input_key = str(damage_entry.get("input_key") or "").strip()
                            if input_key:
                                rider_inputs[input_key] = legacy_total
                action_tags = {"attack"}
                if is_weapon_attack:
                    action_tags.add("weapon")
                if action.get("is_unarmed_attack") is True:
                    action_tags.add("unarmed")
                if action.get("is_monk_weapon") is True:
                    action_tags.add("monk_weapon")
                if action.get("is_spell_attack") is True or action.get("kind") == "spell":
                    action_tags.add("spell_attack")
                if action.get("melee_weapon_attack") is True or "近战" in action_text:
                    action_tags.add("melee")
                if "远程" in action_text:
                    action_tags.add("ranged")
                runtime_progression = (
                    registry.get("progression") if isinstance(registry, dict) else None
                )
                bindings: dict[str, int | str] = {}
                class_levels = (
                    runtime_progression.get("class_levels", {})
                    if isinstance(runtime_progression, dict)
                    else {}
                )
                normalized_levels = {
                    re.sub(r"[\s_：:（）()\-]", "", str(key)).casefold(): int(value)
                    for key, value in class_levels.items()
                    if isinstance(value, int) and not isinstance(value, bool)
                }
                barbarian_level = max(
                    (
                        level
                        for key, level in normalized_levels.items()
                        if key in {"野蛮人", "barbarian"}
                    ),
                    default=0,
                )
                ranger_level = max(
                    (
                        level
                        for key, level in normalized_levels.items()
                        if key in {"游侠", "ranger"}
                    ),
                    default=0,
                )
                if barbarian_level:
                    bindings["barbarian_level_half"] = barbarian_level // 2
                if ranger_level:
                    bindings["dreadful_strikes_die"] = "d6" if ranger_level >= 11 else "d4"
                # Bind only authoritative snapshot values for generic rider
                # expressions.  Dice bindings remain as ``dN`` strings so the
                # domain resolver can validate reported totals and critical
                # doubling without guessing a roll.
                runtime_resources = (
                    registry.get("resources") if isinstance(registry, dict) else None
                )
                if isinstance(runtime_resources, dict):
                    for key in ("martial_arts_die", "bardic_inspiration_die"):
                        raw_die = runtime_resources.get(key)
                        if isinstance(raw_die, dict):
                            die_value = raw_die.get("value") or raw_die.get("label")
                            if isinstance(die_value, str) and re.fullmatch(
                                r"d\d+", die_value.strip(), re.IGNORECASE
                            ):
                                bindings[key] = die_value.strip()
                ability_scores = (actor.snapshot_json or {}).get("ability_scores")
                if isinstance(ability_scores, dict):
                    for ability, binding_key in (
                        ("strength", "strength_modifier"),
                        ("dexterity", "dexterity_modifier"),
                        ("constitution", "constitution_modifier"),
                        ("intelligence", "intelligence_modifier"),
                        ("wisdom", "wisdom_modifier"),
                        ("charisma", "charisma_modifier"),
                    ):
                        raw_score = ability_scores.get(ability, ability_scores.get({
                            "strength": "力量",
                            "dexterity": "敏捷",
                            "constitution": "体质",
                            "intelligence": "智力",
                            "wisdom": "感知",
                            "charisma": "魅力",
                        }[ability]))
                        if isinstance(raw_score, int):
                            bindings[binding_key] = (raw_score - 10) // 2
                raw_save = raw.get("saving_throw")
                if isinstance(raw_save, dict) and raw_save.get("dc_source"):
                    dc_source = str(raw_save.get("dc_source") or "").strip()
                    dc_ability = str(raw_save.get("dc_ability") or "").strip()
                    ability_scores = (actor.snapshot_json or {}).get("ability_scores")
                    proficiency_bonus = (
                        runtime_progression.get("proficiency_bonus")
                        if isinstance(runtime_progression, dict)
                        else None
                    )
                    ability_score = (
                        ability_scores.get(dc_ability)
                        if isinstance(ability_scores, dict)
                        else None
                    )
                    if (
                        dc_source
                        and isinstance(proficiency_bonus, int)
                        and isinstance(ability_score, int)
                    ):
                        bindings[dc_source] = 8 + proficiency_bonus + (ability_score - 10) // 2
                resolved = resolve_post_hit_rider(
                    raw,
                    hit=True,
                    actor={
                        "id": actor.id,
                        "entity_type": actor.entity_type,
                        "faction": CombatEngineService._combatant_faction(actor),
                        "conditions": sorted(CombatEngineService._condition_set(actor)),
                        "class_levels": (
                            runtime_progression.get("class_levels", {})
                            if isinstance(runtime_progression, dict)
                            else {}
                        ),
                        "state": dict(actor.snapshot_json or {}),
                    },
                    target={
                        "id": target.id,
                        "entity_type": target.entity_type,
                        "faction": CombatEngineService._combatant_faction(target),
                        "relation": (
                            "ally"
                            if CombatEngineService._combatant_faction(actor)
                            == CombatEngineService._combatant_faction(target)
                            else "enemy"
                        ),
                        "conditions": sorted(CombatEngineService._condition_set(target)),
                    },
                    action={"tags": sorted(action_tags), "attack_ability": attack_ability},
                    resources=(
                        registry.get("resources", {}) if isinstance(registry, dict) else {}
                    ),
                    event_id=event_id or f"attack:{actor.id}:{target.id}",
                    turn_id=turn_id,
                    inputs=rider_inputs,
                    bindings=bindings,
                    critical_hit=critical_hit,
                )
                if resolved is None or resolved.get("status") == "already_used":
                    continue
                if resolved.get("status") in {
                    "pending_activation",
                    "pending_choice",
                    "pending_save",
                }:
                    result.append(
                        {
                            "rider_id": rider_id,
                            "source": raw.get("feature_name") or rider_id,
                            "frequency": raw.get("frequency"),
                            "target_combatant_id": target.id,
                            "post_hit_status": resolved.get("status"),
                            "post_hit_resolution": resolved,
                            "post_hit_config": dict(raw),
                            "post_hit_action_context": {
                                "tags": sorted(action_tags),
                                "attack_ability": attack_ability,
                            },
                            "post_hit_inputs": rider_inputs,
                            "post_hit_bindings": bindings,
                            "post_hit_event_id": event_id or f"attack:{actor.id}:{target.id}",
                            "post_hit_turn_id": turn_id,
                        }
                    )
                    continue
                if resolved.get("status") == "declined":
                    continue
                if resolved.get("status") != "resolved":
                    raise ValueError(f"攻击骑手 {rider_id} 无法结算")
                if resolved.get("saving_throw") is not None or resolved.get("effects"):
                    raise ValueError("该命中后骑手必须通过持久化后续动作提交效果")
                damage = resolved.get("damage")
                components = damage if isinstance(damage, list) else []
                total = sum(int(item.get("reported_total") or 0) for item in components)
                if total <= 0:
                    continue
                result.append(
                    {
                        "rider_id": rider_id,
                        "expression": "+".join(
                            str(item.get("expression") or "") for item in components
                        ),
                        "reported_total": total,
                        "dice": True,
                        "total": total,
                        "source": raw.get("feature_name") or rider_id,
                        "damage_type": (
                            components[0].get("damage_type")
                            if len(components) == 1
                            else "mixed"
                        ),
                        "frequency": raw.get("frequency"),
                        "target_combatant_id": target.id,
                        "post_hit_resolution_key": resolved.get("resolution_key"),
                        "resource_spends": list(
                            (resolved.get("commit") or {}).get("resource_spends") or []
                        ),
                    }
                )
                continue
            applies_when = str(raw.get("applies_when") or "").strip().lower()
            if applies_when == "raging_strength_attack":
                eligible = (
                    CombatEngineService._has_condition(actor, "raging")
                    and is_strength_attack
                    and is_weapon_attack
                )
            elif applies_when == "raging_reckless_strength_weapon_attack":
                eligible = (
                    CombatEngineService._has_condition(actor, "raging")
                    and CombatEngineService._has_condition(actor, "reckless_attack")
                    and is_strength_attack
                    and bool(
                        is_weapon_attack or action.get("is_unarmed_attack") is True
                    )
                )
            elif applies_when == "brutal_strike_eligible":
                explicit = eligibility.get(rider_id, eligibility.get("brutal_strike"))
                eligible = (
                    explicit is True
                    and CombatEngineService._has_condition(actor, "raging")
                    and CombatEngineService._has_condition(actor, "reckless_attack")
                    and is_strength_attack
                    and bool(
                        is_weapon_attack or action.get("is_unarmed_attack") is True
                    )
                    and str(action.get("attack_roll_mode") or "").strip().lower()
                    == "advantage"
                )
            elif applies_when == "radiant_soul_spell_damage":
                explicit = eligibility.get(rider_id, eligibility.get("radiant_soul"))
                raw_damage_types = action.get("damage_types")
                damage_types = {
                    str(value).strip().lower()
                    for value in raw_damage_types
                    if str(value).strip()
                } if isinstance(raw_damage_types, list) else set()
                selected_target = str(
                    special_inputs.get("radiant_soul_target_id") or ""
                ).strip()
                is_spell_action = bool(
                    action.get("is_spell_attack") is True
                    or action.get("kind") == "spell"
                    or action.get("spell_level") is not None
                )
                eligible = (
                    explicit is True
                    and selected_target == target.id
                    and is_spell_action
                    and bool(damage_types & {"radiant", "fire"})
                )
            elif applies_when == "elemental_affinity_spell_damage":
                selected_damage_type = str(raw.get("selected_damage_type") or "").strip().lower()
                raw_damage_types = action.get("damage_types")
                damage_types = {
                    str(value).strip().lower()
                    for value in raw_damage_types
                    if str(value).strip()
                } if isinstance(raw_damage_types, list) else set()
                is_spell_action = bool(
                    action.get("is_spell_attack") is True
                    or action.get("kind") == "spell"
                    or action.get("spell_level") is not None
                )
                eligible = (
                    bool(selected_damage_type)
                    and is_spell_action
                    and selected_damage_type in damage_types
                )
            elif applies_when == "sneak_attack_eligible":
                explicit = eligibility.get(rider_id, eligibility.get("sneak_attack"))
                eligible = explicit is True
            elif applies_when == "divine_smite_selected_after_melee_weapon_or_unarmed_hit":
                explicit = eligibility.get(rider_id, eligibility.get("divine_smite"))
                melee_weapon_attack = bool(
                    action.get("melee_weapon_attack") is True
                    or ("近战" in action_text and "攻击" in action_text)
                )
                eligible = explicit is True and is_weapon_attack and melee_weapon_attack
            elif applies_when == "radiant_strikes_eligible":
                # 光耀打击 applies to a structurally identified weapon or
                # unarmed attack.  Damage dice are still supplied by the
                # player/DM; the trigger itself must not require a guessed
                # eligibility flag.
                eligible = bool(
                    action.get("is_unarmed_attack") is True
                    or is_weapon_attack
                )
            elif applies_when == "target_is_current_hunters_mark":
                current_mark = (actor.snapshot_json or {}).get(
                    "current_hunters_mark_target_id"
                )
                explicit = eligibility.get(rider_id)
                eligible = current_mark == target.id or explicit is True
            else:
                explicit = eligibility.get(rider_id)
                eligible = explicit is True
            if not eligible:
                continue
            rider_for_total = raw
            selected_slot_level: int | None = None
            dice_count_source = str(raw.get("dice_count_source") or "").strip()
            if dice_count_source:
                if dice_count_source != "rage_damage":
                    raise ValueError(f"攻击附伤 {rider_id} 的骰数来源不受支持")
                rage_rider = next(
                    (
                        candidate
                        for candidate in riders
                        if isinstance(candidate, dict)
                        and str(candidate.get("id") or "") == "rage:bonus_damage"
                    ),
                    None,
                )
                raw_rage_value = str(rage_rider.get("value") or "") if rage_rider else ""
                match = re.search(r"(\d+)", raw_rage_value)
                if match is None:
                    raise ValueError("攻击附伤缺少权威狂暴伤害骰数")
                dice_count = int(match.group(1))
                rider_for_total = {
                    **raw,
                    "value": f"{dice_count}d6",
                    "expression": f"{dice_count}d6",
                }
            modifier_source = str(raw.get("modifier_source") or "").strip()
            if modifier_source:
                ability = modifier_source.removesuffix("_modifier")
                scores = (actor.snapshot_json or {}).get("ability_scores")
                raw_score = scores.get(ability) if isinstance(scores, dict) else None
                if not isinstance(raw_score, int):
                    raise ValueError(f"攻击附伤 {rider_id} 缺少权威属性值")
                rider_for_total = {
                    **raw,
                    "value": str(max(0, (raw_score - 10) // 2)),
                    "expression": f"{modifier_source}",
                }
            if rider_id == "divine_smite:bonus_damage":
                raw_slot = special_inputs.get("divine_smite_slot_level")
                if isinstance(raw_slot, bool) or not isinstance(raw_slot, (int, float)):
                    raise ValueError("圣武斩必须选择要消耗的法术位环阶")
                selected_slot_level = int(raw_slot)
                minimum_slot_level = int(raw.get("minimum_spell_slot_level") or 1)
                if selected_slot_level < minimum_slot_level or selected_slot_level > 5:
                    raise ValueError("圣武斩法术位环阶必须为 1–5 环")
                dice_count = min(5, selected_slot_level + 1)
                rider_for_total = {
                    **raw,
                    "value": f"{dice_count}d8",
                    "expression": f"{dice_count}d8",
                }
            total_result = cls._attack_rider_total(
                rider_for_total,
                special_inputs=special_inputs,
                critical_hit=critical_hit,
            )
            if total_result is None:
                continue
            total, metadata = total_result
            if total <= 0:
                continue
            result.append(
                {
                    **metadata,
                    "total": total,
                    "source": raw.get("feature_name") or raw.get("id"),
                    "damage_type": raw.get("damage_type") or "weapon_damage_type",
                    "frequency": raw.get("frequency"),
                    "target_combatant_id": target.id,
                    **(
                        {
                            "resource_key": f"spell_slots_{selected_slot_level}",
                            "resource_cost": 1,
                            "selected_spell_slot_level": selected_slot_level,
                        }
                        if selected_slot_level is not None
                        else {}
                    ),
                }
            )
        return result

    @staticmethod
    def _mark_attack_rider_usage(
        engine: Engine,
        actor_id: str,
        turn_key: str,
        rider_ids: set[str],
    ) -> None:
        if not rider_ids:
            return
        with Session(engine) as session, session.begin():
            actor = session.get(Combatant, actor_id)
            if actor is None:
                return
            snapshot = dict(actor.snapshot_json or {})
            raw_usage = snapshot.get("attack_rider_uses")
            usage = dict(raw_usage) if isinstance(raw_usage, dict) else {}
            turn_usage = set(
                str(value)
                for value in (usage.get(turn_key) if isinstance(usage.get(turn_key), list) else [])
            )
            turn_usage.update(rider_ids)
            usage[turn_key] = sorted(turn_usage)
            # Keep only a small bounded history; older turns cannot affect a
            # once-per-turn rider and should not grow combat snapshots forever.
            recent = sorted(usage)[-20:]
            snapshot["attack_rider_uses"] = {key: usage[key] for key in recent}
            actor.snapshot_json = snapshot
            actor.version += 1
            actor.updated_at = _now()

    def _persist_post_hit_rider_requests(
        self,
        principal: PlayerPrincipal,
        *,
        combat_id: str,
        actor_id: str,
        rider_results_by_target: dict[str, list[dict[str, Any]]],
        attack_idempotency_key: str,
    ) -> list[dict[str, Any]]:
        """Persist generic follow-ups produced by the post-hit executor."""

        pending = [
            rider
            for riders in rider_results_by_target.values()
            for rider in riders
            if rider.get("post_hit_status")
        ]
        if not pending or principal.character_id is None:
            return []
        created: list[dict[str, Any]] = []
        with Session(self.engine) as session, session.begin():
            character = session.get(Character, principal.character_id)
            combat = session.get(Combat, combat_id)
            actor = session.get(Combatant, actor_id)
            if (
                character is None
                or character.campaign_id != principal.campaign_id
                or combat is None
                or combat.campaign_id != principal.campaign_id
                or combat.status != "active"
                or actor is None
                or not actor.is_active
                or actor.combat_id != combat_id
                or CombatEngineService._combatant_owner(actor) != principal.character_id
            ):
                raise StateNotFoundError("post-hit rider actor not found")
            open_requests = session.scalars(
                select(PlayerActionRequest).where(
                    PlayerActionRequest.campaign_id == principal.campaign_id,
                    PlayerActionRequest.character_id == principal.character_id,
                    PlayerActionRequest.action_type == "post_hit_rider",
                    PlayerActionRequest.status == "pending",
                )
            ).all()
            for rider in pending:
                rider_id = str(rider.get("rider_id") or "")
                target_id = str(rider.get("target_combatant_id") or "")
                target = session.get(Combatant, target_id)
                if target is None or not target.is_active or target.combat_id != combat_id:
                    raise StateNotFoundError("post-hit rider target not found")
                turn_id = str(rider.get("post_hit_turn_id") or "")
                digest = hashlib.sha256(
                    f"{attack_idempotency_key}:{target_id}:{rider_id}".encode()
                ).hexdigest()[:32]
                request_key = f"post-hit:{digest}"
                if any(
                    existing.idempotency_key != request_key
                    and isinstance(existing.payload_json, dict)
                    and existing.payload_json.get("created_by") == "combat_engine"
                    and existing.payload_json.get("rider_id") == rider_id
                    and existing.payload_json.get("turn_id") == turn_id
                    for existing in open_requests
                ):
                    continue
                existing = session.scalar(
                    select(PlayerActionRequest).where(
                        PlayerActionRequest.campaign_id == principal.campaign_id,
                        PlayerActionRequest.idempotency_key == request_key,
                    )
                )
                if existing is not None:
                    existing_payload = dict(existing.payload_json or {})
                    if (
                        existing.action_type != "post_hit_rider"
                        or existing.character_id != principal.character_id
                        or existing_payload.get("created_by") != "combat_engine"
                        or existing_payload.get("combat_id") != combat_id
                        or existing_payload.get("actor_combatant_id") != actor_id
                        or existing_payload.get("target_combatant_id") != target_id
                        or existing_payload.get("rider_id") != rider_id
                    ):
                        raise ValueError("post-hit rider request key collision")
                    created.append(serialize(existing))
                    continue
                resolution = rider.get("post_hit_resolution")
                phase = str(rider.get("post_hit_status") or "")
                item = PlayerActionRequest(
                    campaign_id=principal.campaign_id,
                    character_id=principal.character_id,
                    player_key=principal.session_id,
                    action_type="post_hit_rider",
                    message=f"{rider.get('source') or rider_id}命中后续结算",
                    payload_json={
                        "schema_version": "1.0",
                        "created_by": "combat_engine",
                        "phase": phase,
                        "combat_id": combat_id,
                        "actor_combatant_id": actor_id,
                        "target_combatant_id": target_id,
                        "rider_id": rider_id,
                        "rider_config": rider.get("post_hit_config") or {},
                        "action_context": rider.get("post_hit_action_context") or {},
                        "inputs": rider.get("post_hit_inputs") or {},
                        "bindings": rider.get("post_hit_bindings") or {},
                        "event_id": rider.get("post_hit_event_id"),
                        "turn_id": rider.get("post_hit_turn_id"),
                        "resolution": resolution if isinstance(resolution, dict) else {},
                    },
                    character_version=character.version,
                    idempotency_key=request_key,
                    status="pending",
                )
                session.add(item)
                session.flush()
                created.append(serialize(item))
        return created

    @classmethod
    def _resolve_combat_targets(
        cls,
        *,
        target_rule: TargetBlock,
        actor: Combatant,
        primary_target_id: str,
        requested_target_ids: list[str],
        fighters: list[Combatant],
    ) -> tuple[list[Combatant], dict[str, Any]]:
        requested_ids = list(dict.fromkeys(requested_target_ids or [primary_target_id]))
        if primary_target_id not in requested_ids:
            requested_ids.insert(0, primary_target_id)
        by_id = {fighter.id: fighter for fighter in fighters}
        candidates = []
        for fighter in fighters:
            relation: Literal["self", "ally", "enemy"]
            if fighter.id == actor.id:
                relation = "self"
            elif cls._combatant_faction(fighter) == cls._combatant_faction(actor):
                relation = "ally"
            else:
                relation = "enemy"
            candidates.append(
                TargetCandidate(
                    id=fighter.id,
                    relation=relation,
                    active=fighter.is_active and fighter.hp > 0,
                )
            )
        resolution = resolve_target_selection(
            target_rule,
            caster_id=actor.id,
            primary_target_id=primary_target_id,
            requested_target_ids=requested_ids,
            candidates=candidates,
        )
        if not resolution.accepted:
            messages = "；".join(issue.message for issue in resolution.issues)
            raise ValueError(f"目标不符合该法术计划：{messages}")
        return [by_id[target_id] for target_id in resolution.target_ids], resolution.model_dump(
            mode="json"
        )

    def _player_hit_dice(self, campaign_id: str, character_id: str) -> list[dict[str, Any]]:
        """Return only the bound player's usable hit-die pools."""
        pools = self.player.rest.list_resources(campaign_id, character_id=character_id)
        return [
            {
                "id": pool["id"],
                "key": pool["key"],
                "label": pool["label"],
                "category": pool["category"],
                "current": pool["current"],
                "maximum": pool["maximum"],
                "die_size": pool["die_size"],
                "version": pool["version"],
            }
            for pool in pools
            if pool.get("category") == "hit_die"
        ]

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        return campaign

    @staticmethod
    def _room(session: Session, campaign_id: str) -> PlayerRoom:
        room = session.scalar(select(PlayerRoom).where(PlayerRoom.campaign_id == campaign_id))
        if room is None:
            raise StateNotFoundError("player room not found")
        return room

    @staticmethod
    def _first_active_scene(session: Session, campaign_id: str) -> Scene | None:
        return session.scalar(
            select(Scene)
            .where(Scene.campaign_id == campaign_id, Scene.status == "active")
            .order_by(Scene.created_at, Scene.id)
        )

    def _combat_scene_id(self, principal: PlayerPrincipal, combat_id: str) -> str | None:
        with Session(self.engine) as session:
            combat = session.get(Combat, combat_id)
            if combat is not None and combat.scene_id:
                return combat.scene_id
            room = session.get(PlayerRoom, principal.room_id)
            return room.current_scene_id if room is not None else None

    @staticmethod
    def _active(room: PlayerRoom) -> None:
        if room.status != "active" or _aware(room.expires_at) <= _now():
            raise ValueError("player room is closed or expired")

    def open_room(self, campaign_id: str, *, hours: int = 12) -> dict[str, Any]:
        join_code = _code()
        join_code_salt = secrets.token_hex(16)
        now = _now()
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            first_scene = self._first_active_scene(session, campaign_id)
            room = session.scalar(select(PlayerRoom).where(PlayerRoom.campaign_id == campaign_id))
            if room is None:
                room = PlayerRoom(
                    campaign_id=campaign_id,
                    join_code_salt=join_code_salt,
                    join_code_hash=_code_digest(join_code, join_code_salt),
                    join_code_hint=join_code[-2:],
                    status="active",
                    expires_at=now + timedelta(hours=hours),
                    current_scene_id=first_scene.id if first_scene is not None else None,
                )
                session.add(room)
            else:
                room.join_code_salt = join_code_salt
                room.join_code_hash = _code_digest(join_code, join_code_salt)
                room.join_code_hint = join_code[-2:]
                room.status = "active"
                room.expires_at = now + timedelta(hours=hours)
                if room.current_scene_id is None and first_scene is not None:
                    room.current_scene_id = first_scene.id
                room.version += 1
                room.updated_at = now
                for member in session.scalars(
                    select(PlayerSession).where(PlayerSession.room_id == room.id)
                ).all():
                    member.status = "revoked"
                    member.version += 1
            session.flush()
            result = self._room_payload(session, room)
            result["join_code"] = join_code
            return result

    def room_status(self, campaign_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            room = self._room(session, campaign_id)
            return self._room_payload(session, room)

    def _room_payload(self, session: Session, room: PlayerRoom) -> dict[str, Any]:
        members = session.scalars(
            select(PlayerSession)
            .where(PlayerSession.room_id == room.id)
            .order_by(PlayerSession.created_at)
        ).all()
        host = socket.gethostname().split(".")[0]
        port = _gateway_port()
        urls = [f"http://{address}:{port}/#/player" for address in _private_ipv4()]
        urls.append(f"http://{host}.local:{port}/#/player")
        expired = _aware(room.expires_at) <= _now()
        effective_status = "expired" if room.status == "active" and expired else room.status
        return {
            "id": room.id,
            "campaign_id": room.campaign_id,
            "status": effective_status,
            "active": effective_status == "active",
            "join_code_hint": room.join_code_hint,
            "expires_at": room.expires_at,
            "current_scene_id": room.current_scene_id,
            "current_combat_id": room.current_combat_id,
            "version": room.version,
            "urls": urls,
            "members": [
                {
                    "id": member.id,
                    "display_name": member.display_name,
                    "character_id": member.character_id,
                    "status": member.status,
                    "last_seen_at": member.last_seen_at,
                    "version": member.version,
                }
                for member in members
            ],
        }

    def close_room(self, campaign_id: str) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            room = self._room(session, campaign_id)
            room.status = "closed"
            room.version += 1
            room.updated_at = _now()
            for member in session.scalars(
                select(PlayerSession).where(PlayerSession.room_id == room.id)
            ).all():
                member.status = "revoked"
                member.version += 1
            session.flush()
            return self._room_payload(session, room)

    def set_live_state(
        self,
        campaign_id: str,
        scene_id: str | None,
        combat_id: str | None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            room = self._room(session, campaign_id)
            if expected_version is not None and room.version != expected_version:
                raise VersionConflict("player room", room.id, expected_version, room.version)
            if scene_id is not None:
                scene = session.get(Scene, scene_id)
                if scene is None or scene.campaign_id != campaign_id:
                    raise StateNotFoundError("scene not found")
            if combat_id is not None:
                combat = session.get(Combat, combat_id)
                if combat is None or combat.campaign_id != campaign_id:
                    raise StateNotFoundError("combat not found")
            if room.current_scene_id == scene_id and room.current_combat_id == combat_id:
                return self._room_payload(session, room)
            room.current_scene_id = scene_id
            room.current_combat_id = combat_id
            room.version += 1
            room.updated_at = _now()
            session.flush()
            return self._room_payload(session, room)

    def kick(self, campaign_id: str, member_id: str) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            room = self._room(session, campaign_id)
            member = session.get(PlayerSession, member_id)
            if member is None or member.room_id != room.id:
                raise StateNotFoundError("player session not found")
            member.status = "revoked"
            member.version += 1
            member.updated_at = _now()
            session.flush()
            return serialize(member)

    def join(self, join_code: str, display_name: str) -> tuple[str, dict[str, Any]]:
        normalized = join_code.strip().upper()
        with Session(self.engine) as session, session.begin():
            candidates = session.scalars(
                select(PlayerRoom).where(PlayerRoom.status == "active")
            ).all()
            room = next(
                (
                    item
                    for item in candidates
                    if secrets.compare_digest(
                        item.join_code_hash,
                        _code_digest(normalized, item.join_code_salt),
                    )
                ),
                None,
            )
            if room is None or _aware(room.expires_at) <= _now():
                raise ValueError("房间码无效或已过期")
            token = _token()
            joined_at = _now()
            member = PlayerSession(
                room_id=room.id,
                display_name=display_name.strip(),
                token_hash=_token_digest(token),
                status="active",
                expires_at=room.expires_at,
                last_seen_at=joined_at,
            )
            session.add(member)
            session.flush()
            campaign = self._campaign(session, room.campaign_id)
            return token, {
                "campaign": {"id": campaign.id, "name": campaign.name},
                "player": {"id": member.id, "display_name": member.display_name},
                "joined_at": joined_at,
                "expires_at": member.expires_at,
                "session_max_age_seconds": max(
                    0,
                    int((_aware(member.expires_at) - joined_at).total_seconds()),
                ),
            }

    def authenticate(self, token: str | None) -> PlayerPrincipal:
        if not token:
            raise ValueError("player session is required")
        with Session(self.engine) as session, session.begin():
            member = session.scalar(
                select(PlayerSession).where(PlayerSession.token_hash == _token_digest(token))
            )
            if member is None or member.status != "active" or _aware(member.expires_at) <= _now():
                raise ValueError("player session is invalid or expired")
            room = session.get(PlayerRoom, member.room_id)
            if room is None:
                raise ValueError("player room no longer exists")
            self._active(room)
            if member.character_id is not None:
                character = session.get(Character, member.character_id)
                if character is None or character.campaign_id != room.campaign_id:
                    raise ValueError("bound character is outside the player room campaign")
            member.last_seen_at = _now()
            return PlayerPrincipal(
                room.id, room.campaign_id, member.id, member.display_name, member.character_id
            )

    def _dm_principal(self, campaign_id: str, character_id: str) -> PlayerPrincipal:
        with Session(self.engine) as session:
            room = self._room(session, campaign_id)
            self._active(room)
            character = session.get(Character, character_id)
            if character is None or character.campaign_id != campaign_id:
                raise StateNotFoundError("character not found in campaign")
            return PlayerPrincipal(
                room_id=room.id,
                campaign_id=campaign_id,
                session_id=f"dm:{character_id}",
                display_name="DM 代玩家操作",
                character_id=character_id,
            )

    def dm_noncombat_snapshot(self, campaign_id: str, character_id: str) -> dict[str, Any]:
        principal = self._dm_principal(campaign_id, character_id)
        with Session(self.engine) as session:
            room = self._room(session, campaign_id)
            return self._noncombat_snapshot(session, room, principal)

    def dm_plan_noncombat_action(
        self,
        campaign_id: str,
        character_id: str,
        data: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        return self.plan_noncombat_action(
            self._dm_principal(campaign_id, character_id),
            data,
            request_id,
        )

    def dm_roll_noncombat_action(
        self,
        campaign_id: str,
        character_id: str,
        action_request_id: str,
        expected_version: int,
        raw_roll: int,
    ) -> dict[str, Any]:
        return self.roll_noncombat_action(
            self._dm_principal(campaign_id, character_id),
            action_request_id,
            expected_version,
            raw_roll,
        )

    def logout(self, principal: PlayerPrincipal) -> None:
        with Session(self.engine) as session, session.begin():
            member = session.get(PlayerSession, principal.session_id)
            if member is None or member.room_id != principal.room_id:
                raise StateNotFoundError("player session not found")
            member.status = "revoked"
            member.version += 1
            member.updated_at = _now()

    def bind_character(self, principal: PlayerPrincipal, character_id: str) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            room = session.get(PlayerRoom, principal.room_id)
            if room is None or room.campaign_id != principal.campaign_id:
                raise StateNotFoundError("player room not found")
            self._active(room)
            character = session.get(Character, character_id)
            if character is None or character.campaign_id != principal.campaign_id:
                raise StateNotFoundError("character not found")
            occupied = session.scalar(
                select(PlayerSession).where(
                    PlayerSession.room_id == room.id,
                    PlayerSession.character_id == character_id,
                    PlayerSession.status == "active",
                    PlayerSession.id != principal.session_id,
                )
            )
            if occupied is not None:
                raise ValueError("character is already bound to another player")
            member = session.get(PlayerSession, principal.session_id)
            if member is None or member.room_id != room.id or member.status != "active":
                raise StateNotFoundError("player session not found")
            member.character_id = character_id
            member.version += 1
            member.updated_at = _now()
            session.flush()
            return self.player.character_view(principal.campaign_id, character_id)

    def preview_equipment(self, principal: PlayerPrincipal, data: dict[str, Any]) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        character = self.player.character_view(principal.campaign_id, principal.character_id)
        safe = {
            **data,
            "character_id": principal.character_id,
            "character_version": character["version"],
            "amount": int(data.get("amount") or 1),
            "preview_token": None,
            "idempotency_key": None,
        }
        return self.economy.equipment_preview(principal.campaign_id, safe)

    def confirm_equipment(self, principal: PlayerPrincipal, data: dict[str, Any]) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        character = self.player.character_view(principal.campaign_id, principal.character_id)
        safe = {
            **data,
            "character_id": principal.character_id,
            "character_version": character["version"],
            "amount": int(data.get("amount") or 1),
        }
        return self.economy.equipment_confirm(principal.campaign_id, safe)

    def preview_commerce(self, principal: PlayerPrincipal, data: dict[str, Any]) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        safe = {
            **data,
            "direction": "buy",
            "price_modifier_bps": 10_000,
            "preview_token": None,
            "idempotency_key": None,
        }
        return self.economy.player_commerce_preview(
            principal.campaign_id,
            principal.room_id,
            principal.character_id,
            safe,
        )

    def confirm_commerce(self, principal: PlayerPrincipal, data: dict[str, Any]) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        safe = {
            **data,
            "direction": "buy",
            "price_modifier_bps": 10_000,
        }
        return self.economy.player_commerce_confirm(
            principal.campaign_id,
            principal.room_id,
            principal.character_id,
            safe,
        )

    def create_character(self, principal: PlayerPrincipal, data: dict[str, Any]) -> dict[str, Any]:
        race = str(data["race"])
        class_name = str(data["class_name"])
        background = str(data["background"])
        if (
            race not in CORE_SPECIES
            or class_name not in CORE_CLASSES
            or background not in CORE_BACKGROUNDS
        ):
            raise ValueError("请选择 D&D 5e 2024 核心种族、职业与背景")
        species_rule = SPECIES_RULES[race]
        background_rule = BACKGROUND_RULES[background]
        background_creation_rule = BACKGROUND_CREATION_RULES[background]
        class_rule = CLASS_RULES[class_name]
        origin_increases = {
            str(key): int(value)
            for key, value in dict(data.get("origin_ability_increases") or {}).items()
        }
        ability_generation_method = str(data.get("ability_generation_method") or "standard_array")
        scores = validate_ability_generation(
            ability_generation_method,
            data.get("ability_scores"),
            origin_ability_increases=origin_increases,
            allowed_origin_abilities=background_creation_rule["ability_options"],
            ability_rolls=data.get("ability_rolls"),
        )
        background_tool = str(data.get("background_tool_proficiency") or "").strip()
        if background_tool not in background_creation_rule["tool_choices"]:
            raise ValueError(f"{background}必须选择该背景提供的工具熟练")
        languages = validate_languages(data.get("languages") or [])
        if str(data.get("starter_equipment_option") or "fixed_package") != "fixed_package":
            raise ValueError("玩家规则车卡当前只支持固定起始装备包")
        requested_equipment = [str(item).strip() for item in data.get("equipment") or []]
        if any(requested_equipment):
            raise ValueError("玩家规则车卡不能在起始装备包外追加自定义装备")
        con_mod = (scores["constitution"] - 10) // 2
        max_hp = max(1, CLASS_HIT_DIE[class_name] + con_mod)
        requested_skills = [str(item) for item in data.get("skill_proficiencies") or []]
        skill_count, allowed_skills = CLASS_SKILL_SELECTION[class_name]
        background_skills = set(background_rule.get("skills") or [])
        if (
            len(requested_skills) != skill_count
            or len(set(requested_skills)) != skill_count
            or not set(requested_skills) <= allowed_skills
            or set(requested_skills) & background_skills
        ):
            raise ValueError(
                f"{class_name}必须从职业列表中选择{skill_count}项不与背景重复的技能熟练"
            )
        requested_spells = list(data.get("spells") or [])
        expected_cantrips, expected_leveled = SPELL_SELECTION_2024.get(class_name, (0, 0))
        canonical_class = "魔契师" if class_name == "邪术师" else class_name
        spell_ids = [str(spell.get("source_record_id") or "") for spell in requested_spells]
        cantrip_count = sum(int(spell.get("spell_level") or 0) == 0 for spell in requested_spells)
        leveled_count = sum(int(spell.get("spell_level") or 0) == 1 for spell in requested_spells)
        prepared_leveled_count = sum(
            int(spell.get("spell_level") or 0) == 1 and spell.get("prepared") is True
            for spell in requested_spells
        )
        if (
            any(not spell_id for spell_id in spell_ids)
            or len(set(spell_ids)) != len(spell_ids)
            or cantrip_count != expected_cantrips
            or leveled_count != expected_leveled
            or any(
                int(spell.get("spell_level") or 0) not in {0, 1}
                or canonical_class not in list(spell.get("classes") or [canonical_class])
                for spell in requested_spells
            )
        ):
            raise ValueError(
                f"{class_name}1级必须选择{expected_cantrips}个戏法和"
                f"{expected_leveled}个1环法术，且只能来自本职业法术表"
            )
        if class_name == "法师" and prepared_leveled_count != 4:
            raise ValueError("1级法师必须从法术书的6个1环法术中恰好准备4个")
        if class_name != "法师" and any(
            int(spell.get("spell_level") or 0) == 1 and spell.get("prepared") is not True
            for spell in requested_spells
        ):
            raise ValueError(f"{class_name}选择的1环法术必须标记为已准备")
        if any(
            int(spell.get("spell_level") or 0) == 0 and spell.get("prepared") is not True
            for spell in requested_spells
        ):
            raise ValueError("戏法必须标记为始终可用")
        resources = {
            key: dict(value) for key, value in dict(class_rule.get("resources") or {}).items()
        }
        spellcasting = dict(class_rule.get("spellcasting") or {})
        if spellcasting:
            slots = int(spellcasting.get("level1Slots", 0))
            resources["spell_slots_1"] = {
                "label": "1环法术位",
                "current": slots,
                "max": slots,
                "recovery": "long_rest",
            }
        skill_names = {*requested_skills, *background_skills}
        initial_equipment = [
            *list(class_rule.get("equipment") or []),
            *list(background_rule.get("equipment") or []),
        ]
        dexterity_modifier = (scores["dexterity"] - 10) // 2
        wisdom_modifier = (scores["wisdom"] - 10) // 2
        armor_class = (
            10 + dexterity_modifier + wisdom_modifier
            if class_name == "武僧"
            else 10 + dexterity_modifier + con_mod
            if class_name == "野蛮人"
            else 10 + dexterity_modifier
        )
        starter_assets: list[dict[str, Any]] = []
        occupied_hands: set[str] = set()
        has_armor = False
        for equipment_name in dict.fromkeys(initial_equipment):
            profile = equipment_profile(str(equipment_name))
            slot = str(profile["default_slot"])
            equip_now = False
            if slot == "armor" and not has_armor:
                equip_now = True
                has_armor = True
            elif slot == "main_hand" and not occupied_hands:
                equip_now = True
                occupied_hands.add("main_hand")
                if profile["two_handed"]:
                    occupied_hands.add("off_hand")
            elif slot == "off_hand" and "off_hand" not in occupied_hands:
                equip_now = True
                occupied_hands.add("off_hand")
            elif slot == "focus":
                equip_now = True
            metadata: dict[str, Any] = {
                "equipment_profile": profile,
                "origin": "character_creation_2024",
                "rule_reference": profile["rule_reference"],
            }
            if equip_now:
                metadata["equipment_slot"] = slot
            starter_assets.append(
                {
                    "name": str(equipment_name),
                    "category": str(profile["kind"]),
                    "armor_class": profile["base_armor_class"],
                    "equipped": equip_now,
                    "metadata_json": metadata,
                }
            )
        equipped_armor = next(
            (
                asset
                for asset in starter_assets
                if asset["equipped"] and asset["category"] == "armor"
            ),
            None,
        )
        if equipped_armor and equipped_armor["armor_class"] is not None:
            armor_type = str(
                dict(equipped_armor["metadata_json"])["equipment_profile"].get("armor_type") or ""
            )
            base_ac = int(equipped_armor["armor_class"])
            armor_class = (
                base_ac + dexterity_modifier
                if armor_type == "light"
                else base_ac + min(2, dexterity_modifier)
                if armor_type == "medium"
                else base_ac
            )
        if any(asset["equipped"] and asset["category"] == "shield" for asset in starter_assets):
            armor_class += 2
        with Session(self.engine) as session, session.begin():
            member = session.get(PlayerSession, principal.session_id)
            room = session.get(PlayerRoom, principal.room_id)
            if (
                member is None
                or member.room_id != principal.room_id
                or member.status != "active"
                or room is None
                or room.campaign_id != principal.campaign_id
            ):
                raise ValueError("player room session is invalid")
            self._active(room)
            if not room.allow_character_creation:
                raise ValueError("当前房间不允许玩家车卡")
            item = Character(
                campaign_id=principal.campaign_id,
                name=str(data["name"]).strip(),
                race=race,
                class_name=class_name,
                background=background,
                level=1,
                armor_class=armor_class,
                speed=int(species_rule["speed"]),
                ability_scores=scores,
                hp=max_hp,
                max_hp=max_hp,
                equipment=initial_equipment,
                proficiencies=list(
                    dict.fromkeys(
                        [
                            *list(class_rule.get("proficiencies") or []),
                            *[f"{ability}豁免" for ability in list(class_rule.get("saves") or [])],
                            f"工具：{background_tool}",
                            *[f"语言：{language}" for language in languages],
                        ]
                    )
                ),
                skills={skill: {"proficient": True} for skill in sorted(skill_names)},
                features=[
                    *list(species_rule.get("features") or []),
                    f"属性生成：{ability_generation_label(ability_generation_method)}",
                    "背景起源："
                    + "、".join(
                        f"{ABILITY_LABELS[key]} +{value}" for key, value in origin_increases.items()
                    ),
                    f"背景专长：{background_rule['feat']}",
                ],
                actions=[dict(action) for action in list(class_rule.get("actions") or [])],
                resources=resources,
                spells=[
                    {
                        **{
                            key: (str(value)[:2400] if isinstance(value, str) else value)
                            for key, value in spell.items()
                            if key
                            in {
                                "name",
                                "source_record_id",
                                "source_path",
                                "spell_level",
                                "prepared",
                                "school",
                                "casting_time",
                                "range",
                                "components",
                                "duration",
                                "concentration",
                                "ritual",
                                "damage",
                                "damage_type",
                                "save_ability",
                                "save_dc",
                                "half_damage_on_save",
                                "description",
                                "cost",
                                "resource_key",
                                "resource_cost",
                                "ritual_only",
                                "resolution_kind",
                                "classes",
                            }
                        },
                        "rule_plan": compile_rule_blocks_dict(
                            spell,
                            source_kind="spell",
                        ),
                    }
                    for spell in requested_spells
                    if spell.get("name")
                ],
                spellcasting=spellcasting,
                class_levels={"魔契师" if class_name == "邪术师" else class_name: 1},
                notes=f"D&D 5e 2024规则角色 · 背景：{background}",
            )
            validate_character_state(
                {
                    "level": item.level,
                    "class_name": item.class_name,
                    "class_levels": item.class_levels,
                    "subclass_choices": {},
                    "ability_scores": item.ability_scores,
                    "hp": item.hp,
                    "max_hp": item.max_hp,
                    "resources": item.resources,
                    "spells": item.spells,
                },
                require_complete_abilities=True,
            )
            session.add(item)
            session.flush()
            session.add_all(
                [
                    EquipmentInstance(
                        campaign_id=principal.campaign_id,
                        character_id=item.id,
                        quantity=1,
                        attunement_required=False,
                        **asset,
                    )
                    for asset in starter_assets
                ]
            )
            member.character_id = item.id
            member.version += 1
            session.flush()
            character_id = item.id
        return self.player.character_view(principal.campaign_id, character_id)

    def assign_character(
        self,
        campaign_id: str,
        member_id: str,
        character_id: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            room = self._room(session, campaign_id)
            self._active(room)
            member = session.get(PlayerSession, member_id)
            if member is None or member.room_id != room.id or member.status != "active":
                raise StateNotFoundError("player session not found")
            character = session.get(Character, character_id)
            if character is None or character.campaign_id != campaign_id:
                raise StateNotFoundError("character not found")
            occupied = session.scalar(
                select(PlayerSession).where(
                    PlayerSession.room_id == room.id,
                    PlayerSession.character_id == character_id,
                    PlayerSession.status == "active",
                    PlayerSession.id != member.id,
                )
            )
            if occupied is not None:
                raise ValueError("character is already bound to another player")
            member.character_id = character.id
            member.version += 1
            member.updated_at = _now()
            session.flush()
            return serialize(member)

    def _public_shops(self, session: Session, scene: Scene | None) -> list[dict[str, Any]]:
        """Expose only merchant stock explicitly published in the live Scene."""
        if scene is None:
            return []
        visible_npc_ids = {
            participant.entity_id
            for participant in session.scalars(
                select(SceneParticipant).where(
                    SceneParticipant.scene_id == scene.id,
                    SceneParticipant.entity_type == "npc",
                    SceneParticipant.visible.is_(True),
                )
            ).all()
        }
        groups: dict[str, dict[str, Any]] = {}
        for item in session.scalars(
            select(ShopInventory)
            .where(ShopInventory.campaign_id == scene.campaign_id)
            .order_by(ShopInventory.name, ShopInventory.id)
        ).all():
            metadata = dict(item.metadata_json)
            merchant_id = str(metadata.get("merchant_id") or "")
            merchant_npc_id = str(metadata.get("merchant_npc_id") or "")
            if (
                not merchant_id
                or not merchant_npc_id
                or str(metadata.get("scene_id") or "") != scene.id
                or merchant_npc_id not in visible_npc_ids
            ):
                continue
            npc = session.get(NPC, merchant_npc_id)
            if npc is None or npc.campaign_id != scene.campaign_id:
                continue
            group = groups.setdefault(
                merchant_id,
                {
                    "merchant_id": merchant_id,
                    "name": npc.name,
                    "description": npc.description,
                    "stock": [],
                },
            )
            group["stock"].append(
                {
                    "id": item.id,
                    "name": item.name,
                    "quantity": item.quantity,
                    "price_copper": item.price_copper,
                    "version": item.version,
                    "category": metadata.get("category"),
                    "item_tier": metadata.get("item_tier"),
                }
            )
        return sorted(
            groups.values(),
            key=lambda shop: (str(shop["name"]), str(shop["merchant_id"])),
        )

    def snapshot(self, principal: PlayerPrincipal) -> dict[str, Any]:
        hit_dice = (
            self._player_hit_dice(principal.campaign_id, principal.character_id)
            if principal.character_id
            else []
        )
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            if room is None or room.campaign_id != principal.campaign_id:
                raise StateNotFoundError("player room not found")
            self._active(room)
            campaign = self._campaign(session, principal.campaign_id)
            claimed_ids = set(
                session.scalars(
                    select(PlayerSession.character_id).where(
                        PlayerSession.room_id == room.id,
                        PlayerSession.status == "active",
                        PlayerSession.character_id.is_not(None),
                    )
                ).all()
            )
            available_characters = [
                {
                    "id": character.id,
                    "name": character.name,
                    "race": character.race,
                    "class_name": character.class_name,
                    "level": character.level,
                }
                for character in session.scalars(
                    select(Character)
                    .where(Character.campaign_id == principal.campaign_id)
                    .order_by(Character.created_at, Character.id)
                ).all()
                if character.id not in claimed_ids
            ]
            scene = session.get(Scene, room.current_scene_id) if room.current_scene_id else None
            public = self.player.player_view(principal.campaign_id)
            if scene is not None:
                if scene.campaign_id != principal.campaign_id:
                    raise ValueError("player room scene is outside its campaign")
                public["scene"] = self._safe_scene(session, scene, principal)
            character = (
                self.player.character_view(principal.campaign_id, principal.character_id)
                if principal.character_id
                else None
            )
            if character is not None:
                character["hit_dice"] = hit_dice
                feature_grants = [
                    item for item in character.get("features", [])
                    if isinstance(item, dict)
                ]
                scaling_values = {
                    str(item.get("scaling_key")): item.get("value")
                    for item in feature_grants
                    if item.get("kind") == "class_scaling"
                    and isinstance(item.get("scaling_key"), str)
                }
                feature_registry = compile_feature_runtime_registry(
                    feature_grants,
                    resources=(character.get("resources") or {})
                    if isinstance(character.get("resources"), dict)
                    else {},
                    scalings={
                        key: {"value": value}
                        for key, value in scaling_values.items()
                    },
                    class_levels=(character.get("class_levels") or {})
                    if isinstance(character.get("class_levels"), dict)
                    else {},
                    total_level=int(character.get("level") or 0) or None,
                )
                character["feature_runtime"] = feature_registry
                runtime_actions = feature_runtime_action_projections(feature_registry)
                if runtime_actions:
                    existing_names = {
                        str(item.get("name"))
                        for item in character.get("actions", [])
                        if isinstance(item, dict)
                    }
                    character["actions"] = [
                        *list(character.get("actions") or []),
                        *[
                            item for item in runtime_actions
                            if str(item.get("name")) not in existing_names
                        ],
                    ]
                character["companions"] = [
                    {
                        "id": companion.id,
                        "name": companion.name,
                        "companion_type": companion.companion_type,
                        "source_record_id": companion.source_record_id,
                        "template_json": companion.template_json,
                        "hp": companion.hp,
                        "max_hp": companion.max_hp,
                        "armor_class": companion.armor_class,
                        "speed": companion.speed,
                        "active": companion.active,
                    }
                    for companion in session.scalars(
                        select(CharacterCompanion).where(
                            CharacterCompanion.campaign_id == principal.campaign_id,
                            CharacterCompanion.owner_character_id == principal.character_id,
                            CharacterCompanion.active.is_(True),
                        )
                    ).all()
                ]
            return {
                "room": {"id": room.id, "status": room.status, "expires_at": room.expires_at},
                "campaign": {
                    "id": campaign.id,
                    "name": campaign.name,
                    "current_time": campaign.current_time,
                },
                "player": {
                    "id": principal.session_id,
                    "display_name": principal.display_name,
                    "character_id": principal.character_id,
                },
                "character": character,
                "available_characters": available_characters,
                "table": {
                    "scene": public.get("scene"),
                    "handouts": public.get("handouts", []),
                    "shared_log": public.get("shared_log", []),
                    "shops": self._public_shops(session, scene),
                    "noncombat": self._noncombat_snapshot(session, room, principal),
                },
                "combat": self._combat_snapshot(session, room, principal),
            }

    def _safe_scene(
        self, session: Session, scene: Scene, principal: PlayerPrincipal
    ) -> dict[str, Any]:
        grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene.id))
        fog_enabled = principal.character_id is not None
        visibility = self._visibility_for(session, scene, principal, grid)
        visible = visibility["visible"]
        explored = visibility["explored"]
        tokens = session.scalars(
            select(SceneToken).where(
                SceneToken.scene_id == scene.id,
                SceneToken.visible.is_(True),
            )
        ).all()
        objects = session.scalars(
            select(SceneObject).where(
                SceneObject.scene_id == scene.id,
                SceneObject.visibility == "public",
            )
        ).all()
        safe_tokens = (
            tokens
            if not fog_enabled
            else [
                item
                for item in tokens
                if (item.entity_type == "character" and item.entity_id == principal.character_id)
                or (item.row, item.col) in visible
            ]
        )
        safe_objects = (
            objects
            if not fog_enabled
            else [item for item in objects if (item.row, item.col) in explored | visible]
        )
        transitions: list[dict[str, Any]] = []
        current_level = session.scalar(
            select(SiteLevel).where(SiteLevel.location_id == scene.location_id)
        )
        if current_level is not None:
            for connector in session.scalars(
                select(SiteConnector).where(
                    SiteConnector.site_id == current_level.site_id,
                    SiteConnector.from_level_index == current_level.level_index,
                    SiteConnector.connector_type.in_(("stairs_up", "stairs_down")),
                )
            ).all():
                position = dict(connector.position_json or {})
                public_position = (
                    int(position.get("row", -2)) + 1,
                    int(position.get("col", -2)) + 1,
                )
                if fog_enabled and public_position not in explored | visible:
                    continue
                target_level = session.scalar(
                    select(SiteLevel).where(
                        SiteLevel.site_id == current_level.site_id,
                        SiteLevel.level_index == connector.to_level_index,
                    )
                )
                target_scene = (
                    session.scalar(
                        select(Scene).where(
                            Scene.campaign_id == scene.campaign_id,
                            Scene.location_id == target_level.location_id,
                        )
                    )
                    if target_level is not None
                    else None
                )
                if target_level is None or target_scene is None:
                    continue
                transitions.append(
                    {
                        "connector_id": connector.id,
                        "direction": connector.connector_type,
                        "label": connector.label,
                        "row": public_position[0],
                        "col": public_position[1],
                        "from_scene_id": scene.id,
                        "target_scene_id": target_scene.id,
                        "target_level_index": target_level.level_index,
                        "target_level_name": target_level.name,
                    }
                )
        return {
            "id": scene.id,
            "name": scene.name,
            "description": scene.description,
            "grid": (
                None
                if grid is None
                else {
                    "width": grid.width,
                    "height": grid.height,
                    "cell_size_ft": grid.cell_size_ft,
                    "mode": grid.mode,
                    "public_description": grid.public_description,
                    **(
                        {
                            "theme": str(dict(grid.layers_json or {})["theme"]),
                            "visual_theme": dict(grid.layers_json or {}).get("visual_theme", {}),
                        }
                        if dict(grid.layers_json or {}).get("theme")
                        else {}
                    ),
                    **(
                        {
                            "fog_of_war": True,
                            "explored_cells": [
                                {"row": row, "col": col} for row, col in sorted(explored)
                            ],
                            "visible_cells": [
                                {"row": row, "col": col} for row, col in sorted(visible)
                            ],
                        }
                        if fog_enabled
                        else {}
                    ),
                    # Unexplored cells are not transmitted at all.  The
                    # player renderer therefore sees an opaque cell and the
                    # complete dungeon topology cannot be recovered from the
                    # network payload or browser devtools.
                    "cells": (
                        [
                            cell
                            for cell in public_cells(grid.layers_json)
                            if (int(cell.get("row", -1)), int(cell.get("col", -1)))
                            in explored | visible
                        ]
                        if fog_enabled
                        else public_cells(grid.layers_json)
                    ),
                }
            ),
            "tokens": [
                {
                    "id": item.id,
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "label": item.label,
                    "row": item.row,
                    "col": item.col,
                    "size_cells": item.size_cells,
                    "elevation_ft": item.elevation_ft,
                }
                for item in safe_tokens
            ],
            "objects": [
                {
                    "id": item.id,
                    "object_type": item.object_type,
                    "label": item.label,
                    "row": item.row,
                    "col": item.col,
                    "width_cells": item.width_cells,
                    "height_cells": item.height_cells,
                    "state": item.state,
                    "version": item.version,
                    "interaction": {
                        key: value
                        for key, value in (item.interaction_json or {}).items()
                        if key in {"action", "locked", "tool", "description"}
                    },
                }
                for item in safe_objects
            ],
            "available_transitions": transitions,
        }

    @staticmethod
    def _visibility_for(
        session: Session,
        scene: Scene,
        principal: PlayerPrincipal,
        grid: SceneGrid | None,
        *,
        origin_override: tuple[int, int] | None = None,
    ) -> dict[str, set[tuple[int, int]]]:
        if grid is None or principal.character_id is None:
            return {"visible": set(), "explored": set()}
        viewer_key = f"character:{principal.character_id}"
        state = session.scalar(
            select(VisibilityState).where(
                VisibilityState.scene_id == scene.id,
                VisibilityState.viewer_key == viewer_key,
            )
        )
        explored = {
            (int(item["row"]), int(item["col"]))
            for item in (state.explored_cells if state else [])
            if isinstance(item, dict) and "row" in item and "col" in item
        }
        origin = origin_override
        if origin is None:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is not None:
                combatant = session.scalar(
                    select(Combatant).where(
                        Combatant.combat_id == combat.id,
                        Combatant.entity_type == "character",
                        Combatant.entity_id == principal.character_id,
                    )
                )
                position = combatant.snapshot_json.get("grid_position") if combatant else None
                if isinstance(position, dict):
                    origin = (int(position["row"]), int(position["col"]))
        if origin is None:
            token = session.scalar(
                select(SceneToken).where(
                    SceneToken.scene_id == scene.id,
                    SceneToken.entity_type == "character",
                    SceneToken.entity_id == principal.character_id,
                )
            )
            if token is not None:
                origin = (token.row, token.col)
        if origin is None:
            return {"visible": set(), "explored": explored}
        blockers = {
            (int(cell["row"]), int(cell["col"]))
            for cell in public_cells(grid.layers_json)
            if CombatEngineService._sight_transparency(
                cell,
                default="opaque" if cell.get("blocks_sight") is True else "transparent",
            )
            == "opaque"
        }
        for item in session.scalars(
            select(SceneObject).where(SceneObject.scene_id == scene.id)
        ).all():
            if item.state in {"destroyed", "picked_up"}:
                continue
            if item.object_type == "wall" or (
                item.object_type == "door" and item.state in {"active", "closed"}
            ):
                if CombatEngineService._sight_transparency(
                    item.metadata_json,
                    default="opaque",
                ) == "opaque":
                    blockers.update(_object_cells(item))
        radius = 8
        visible = {
            (row, col)
            for row in range(max(0, origin[0] - radius), min(grid.height, origin[0] + radius) + 1)
            for col in range(max(0, origin[1] - radius), min(grid.width, origin[1] + radius) + 1)
            if grid_distance_ft(origin, (row, col), cell_size_ft=grid.cell_size_ft)
            <= radius * grid.cell_size_ft
            and line_of_sight(origin, (row, col), blockers)
        }
        return {"visible": visible, "explored": explored | visible}

    def _noncombat_snapshot(
        self, session: Session, room: PlayerRoom, principal: PlayerPrincipal
    ) -> dict[str, Any]:
        if principal.character_id is None or room.current_scene_id is None:
            return {"available_actions": [], "pending_actions": []}
        character = session.get(Character, principal.character_id)
        if character is None:
            return {"available_actions": [], "pending_actions": []}
        actions: list[dict[str, Any]] = [
            {
                "id": f"skill:{name}",
                "kind": "skill",
                "name": name,
                "description": description,
                "ability": ability,
                "ability_label": ABILITY_LABELS[ability],
                "suggested_dc": dc,
                "rule_plan": compile_rule_blocks_dict(
                    {
                        "name": name,
                        "description": description,
                        "ability": ability,
                        "skill": name,
                        "resolution_kind": "skill_check",
                        "dc_source": "dm_chosen_dc",
                    },
                    source_kind="feature",
                ),
                "target_types": (
                    ["npc", "monster"]
                    if name in SOCIAL_SKILLS
                    else ["object", "area"]
                    if name in OBJECT_SKILLS
                    else ["self", "area"]
                ),
            }
            for name, (ability, dc, description) in SKILL_RULES.items()
        ]
        actions.append(
            {
                "id": "tool:thieves_tools",
                "kind": "tool",
                "name": "盗贼工具：撬锁/解除机关",
                "description": "对公开的门、宝箱或机关提出结构化操作。",
                "ability": "dexterity",
                "ability_label": "敏捷",
                "suggested_dc": 15,
                "rule_plan": compile_rule_blocks_dict(
                    {
                        "name": "盗贼工具：撬锁/解除机关",
                        "description": "对公开的门、宝箱或机关提出结构化操作。",
                        "ability": "dexterity",
                        "skill": "巧手",
                        "resolution_kind": "skill_check",
                    },
                    source_kind="feature",
                ),
                "target_types": ["object"],
            }
        )
        for index, raw in enumerate(character.spells or []):
            if not isinstance(raw, dict) or raw.get("prepared") is False:
                continue
            if raw.get("resolution_kind") == "damage" or raw.get("damage"):
                continue
            name = str(raw.get("name") or f"法术 {index + 1}")
            actions.append(
                {
                    "id": f"spell:{raw.get('source_record_id') or index}",
                    "kind": "spell",
                    "name": name,
                    "description": str(raw.get("description") or "由 DM 按法术说明裁定。"),
                    "range": raw.get("range"),
                    "duration": raw.get("duration"),
                    "concentration": bool(raw.get("concentration")),
                    "resource_key": raw.get("resource_key"),
                    "resource_cost": int(raw.get("resource_cost") or 0),
                    "ritual_only": bool(raw.get("ritual_only")),
                    "save_ability": raw.get("save_ability"),
                    "save_dc": raw.get("save_dc"),
                    "rule_plan": raw.get("rule_plan")
                    or compile_rule_blocks_dict(
                        {
                            **raw,
                            "name": name,
                            "description": str(raw.get("description") or ""),
                            "resolution_kind": str(raw.get("resolution_kind") or "control"),
                        },
                        source_kind="spell",
                    ),
                    "target_types": self._spell_target_types(name),
                }
            )
        pending = session.scalars(
            select(PlayerActionRequest)
            .where(
                PlayerActionRequest.campaign_id == principal.campaign_id,
                PlayerActionRequest.player_key == principal.session_id,
                PlayerActionRequest.action_type == "noncombat_rule",
                PlayerActionRequest.status == "pending",
            )
            .order_by(PlayerActionRequest.created_at.desc())
        ).all()
        return {
            "available_actions": actions,
            "pending_actions": [
                {
                    "id": item.id,
                    "version": item.version,
                    "message": item.message,
                    "payload": item.payload_json,
                }
                for item in pending
            ],
        }

    @staticmethod
    def _pr_spell_key(name: str) -> str:
        """Normalize the small, explicitly supported exploration-spell set."""
        return re.sub(r"[\s_.-]+", "", name).casefold()

    @classmethod
    def _pr_spell_effect_kind(cls, name: str) -> str | None:
        key = cls._pr_spell_key(name)
        aliases = (
            ("light", ("光亮术", "不灭明焰", "昼明术", "舞光术", "light")),
            ("darkness", ("黑暗术", "darkness")),
            ("detect_magic", ("侦测魔法", "探测魔法", "detectmagic")),
            ("detect_trap", ("寻找陷阱", "侦测陷阱", "findtraps")),
            ("locate", ("物件定位术", "生物定位术", "动植物定位术", "定位术", "locate")),
            ("grant_language", ("通晓语言", "巧言术", "comprehendlanguages")),
            ("create_supply", ("造粮术", "造水术", "造水/枯水术", "神莓术", "goodberry")),
            ("knock", ("敲击术", "knock")),
            ("arcane_lock", ("秘法锁", "奥术锁", "arcanelock")),
            ("mending", ("修复术", "mending")),
            ("message", ("传讯", "message")),
            ("sending", ("短讯", "sending")),
            ("comprehend_languages", ("通晓语言", "comprehendlanguages")),
            ("speak_with_animals", ("动物交谈", "speakwithanimals")),
            (
                "communicate",
                ("植物交谈", "动物信使", "心灵感应", "拉瑞心灵联结", "communicate"),
            ),
        )
        return next(
            (effect for effect, names in aliases if any(alias in key for alias in names)),
            None,
        )

    @classmethod
    def _spell_target_types(cls, name: str) -> list[str]:
        effect = cls._pr_spell_effect_kind(name)
        if effect in {"knock", "arcane_lock", "mending"}:
            return ["object"]
        if effect in {"light", "darkness"}:
            return ["self", "object", "area"]
        if effect in {"detect_magic", "detect_trap", "locate", "create_supply"}:
            return ["self", "object", "area", "npc", "monster"]
        if effect == "grant_language":
            return ["self", "npc", "monster"]
        if effect in {"message", "sending"}:
            return ["self", "npc", "monster"]
        if effect == "comprehend_languages":
            return ["self"]
        if effect == "speak_with_animals":
            return ["self", "npc", "monster"]
        if "隐形" in name:
            return ["self"]
        if "命令" in name:
            return ["npc", "monster"]
        return ["self", "npc", "monster", "object", "area"]

    @staticmethod
    def _manual_automation(reason: str) -> dict[str, Any]:
        return {
            "status": "manual",
            "mode": "manual",
            "apply_on_dm_accept": False,
            "requires_dm_confirmation": True,
            "reason": reason,
        }

    @classmethod
    def _safe_pr_spell_execution(
        cls,
        *,
        action: dict[str, Any],
        target: dict[str, Any],
        target_object: SceneObject | None,
    ) -> dict[str, dict[str, Any]] | None:
        """Return a DM-confirmed operation for a deliberately tiny safe spell set.

        These effects never alter fog of war, creatures, or hidden information.  A
        proposal is merely ready for the DM inbox; it is applied only by
        ``PlayerService.resolve_action`` after acceptance.
        """
        name = str(action.get("name") or "")
        effect = cls._pr_spell_effect_kind(name)
        if effect is None:
            return None

        def object_operation(
            operation: str,
            *,
            summary: str,
            extra: dict[str, Any] | None = None,
        ) -> dict[str, dict[str, Any]]:
            if target_object is None:
                raise ValueError(f"{name}必须选择当前公开 Scene 中的物体")
            proposal: dict[str, Any] = {
                "kind": "scene_object_operation",
                "operation": operation,
                "object_id": target_object.id,
                "expected_object_type": target_object.object_type,
                "expected_state": target_object.state,
                "expected_object_version": target_object.version,
                "summary": summary,
            }
            if extra:
                proposal.update(extra)
            return {
                "resolution": {
                    "kind": "automatic_effect",
                    "effect": operation,
                    "requires_player_roll": False,
                    "requires_dm_confirmation": True,
                    "status": "ready",
                },
                "proposal": proposal,
                "automation": {
                    "status": "ready_for_dm_confirmation",
                    "mode": "dm_confirmed_object_operation",
                    "operation": operation,
                    "apply_on_dm_accept": True,
                    "requires_dm_confirmation": True,
                },
            }

        if effect == "knock":
            if target_object is None or target_object.object_type != "door":
                raise ValueError("敲击术只能自动处理当前公开 Scene 中的门")
            interaction = dict(target_object.interaction_json or {})
            if interaction.get("locked") is not True:
                raise ValueError("敲击术只能自动处理明确标记为已锁的门")
            return object_operation(
                "unlock_door",
                summary=f"DM 确认后将解除「{target_object.label}」的锁定，不自动打开门。",
                extra={"expected_locked": True},
            )

        if effect == "arcane_lock":
            if target_object is None or target_object.object_type != "door":
                raise ValueError("秘法锁只能自动处理当前公开 Scene 中的门")
            if target_object.state != "closed":
                raise ValueError("秘法锁只能自动处理关闭的门")
            interaction = dict(target_object.interaction_json or {})
            return object_operation(
                "lock_door",
                summary=f"DM 确认后将把「{target_object.label}」标记为秘法锁定。",
                extra={"expected_locked": bool(interaction.get("locked"))},
            )

        if effect == "mending":
            return object_operation(
                "mark_repaired",
                summary=f"DM 确认后将记录「{target_object.label}」已由修复术修补。",
            )

        if effect in {"light", "darkness"} and target_object is not None:
            operation = "illuminate_object" if effect == "light" else "darken_object"
            spell_name = str(action.get("name") or "")
            bright_radius = 60 if spell_name == "昼明术" else 10 if spell_name == "舞光术" else 20
            dim_radius = bright_radius
            effect_data = (
                {
                    "mode": "bright_light",
                    "bright_radius_ft": bright_radius,
                    "dim_radius_ft": dim_radius,
                }
                if effect == "light"
                else {"mode": "magical_darkness", "radius_ft": 15}
            )
            label = "光照" if effect == "light" else "魔法黑暗"
            return object_operation(
                operation,
                summary=(
                    f"DM 确认后将把「{target_object.label}」记录为{label}来源；不自动改写战争迷雾。"
                ),
                extra={"illumination": effect_data},
            )

        if effect in {"detect_magic", "detect_trap", "locate", "create_supply"}:
            descriptions = {
                "detect_magic": "记录侦测魔法请求；系统不会伪造隐藏物或学派信息。",
                "detect_trap": "记录寻找陷阱请求；发现与解除仍由 DM 根据公开场景和规则确认。",
                "locate": "记录定位请求；目标是否存在、方向和距离仍由 DM 确认。",
                "grant_language": "记录语言理解能力生效；具体交流内容仍由 DM 确认。",
                "create_supply": "记录补给创造结果；数量按法术原文和 DM 确认，不从名称猜测。",
            }
            return {
                "resolution": {
                    "kind": "structured_effect",
                    "effect": effect,
                    "requires_player_roll": False,
                    "requires_dm_confirmation": True,
                    "status": "ready",
                },
                "proposal": {
                    "kind": "structured_result",
                    "result_type": effect,
                    "target": target,
                    "summary": descriptions[effect],
                },
                "automation": {
                    "status": "ready_for_dm_confirmation",
                    "mode": "dm_confirmed_result",
                    "operation": "record_structured_result",
                    "apply_on_dm_accept": False,
                    "requires_dm_confirmation": True,
                },
            }

        if effect in {"light", "darkness"}:
            label = "光亮术" if effect == "light" else "黑暗术"
            spell_name = str(action.get("name") or "")
            light_range = 120 if spell_name == "昼明术" else 20 if spell_name == "舞光术" else 40
            details = (
                f"明亮光照{light_range // 2}尺，外加微光光照{light_range // 2}尺。"
                if effect == "light"
                else "半径15尺的魔法黑暗区域。"
            )
            return {
                "resolution": {
                    "kind": "automatic_effect",
                    "effect": "light_suggestion" if effect == "light" else "darkness_suggestion",
                    "requires_player_roll": False,
                    "requires_dm_confirmation": True,
                    "status": "ready",
                },
                "proposal": {
                    "kind": "lighting_suggestion",
                    "effect": effect,
                    "summary": f"{label}：{details} DM 可据场景补充光照、遮蔽和可见性后果。",
                },
                "automation": {
                    "status": "ready_for_dm_confirmation",
                    "mode": "dm_confirmed_result",
                    "operation": "record_lighting_suggestion",
                    "apply_on_dm_accept": False,
                    "requires_dm_confirmation": True,
                },
            }

        communication = {
            "message": ("message", "传递一段简短讯息"),
            "sending": ("sending", "向目标发送短讯"),
            "comprehend_languages": ("comprehend_languages", "获得理解语言的临时能力"),
            "speak_with_animals": ("speak_with_animals", "获得与动物交谈的临时能力"),
            "communicate": ("communicate", "建立与目标的结构化沟通窗口"),
        }
        if effect == "grant_language":
            effect = "comprehend_languages"
        if effect in communication:
            channel, outcome = communication[effect]
            return {
                "resolution": {
                    "kind": "structured_communication",
                    "channel": channel,
                    "requires_player_roll": False,
                    "requires_dm_confirmation": True,
                    "status": "ready",
                },
                "proposal": {
                    "kind": "structured_result",
                    "result_type": channel,
                    "target": {
                        "type": target.get("type"),
                        "id": target.get("id"),
                        "name": target.get("name"),
                    },
                    "summary": f"DM 确认后记录：{outcome}。具体内容、回应与持续时间由 DM 裁定。",
                },
                "automation": {
                    "status": "ready_for_dm_confirmation",
                    "mode": "dm_confirmed_result",
                    "operation": "record_structured_result",
                    "apply_on_dm_accept": False,
                    "requires_dm_confirmation": True,
                },
            }
        return None

    def _combat_snapshot(
        self, session: Session, room: PlayerRoom, principal: PlayerPrincipal
    ) -> dict[str, Any] | None:
        combat = session.get(Combat, room.current_combat_id) if room.current_combat_id else None
        if combat is None or combat.status not in {"active", "ended"}:
            return None
        fighters = session.scalars(
            select(Combatant)
            .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
            .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
        ).all()
        active = (
            fighters[combat.current_turn_index]
            if (
                combat.status == "active" and fighters and combat.current_turn_index < len(fighters)
            )
            else None
        )
        own_ids = {
            item.id for item in fighters if self._is_player_controlled(item, principal.character_id)
        }
        own = next((item for item in fighters if item.id in own_ids), None)
        death_save: dict[str, Any] | None = None
        if own is not None and own.entity_type == "character" and own.hp <= 0:
            death_save_row = session.scalar(
                select(DeathSave).where(DeathSave.combatant_id == own.id)
            )
            death_save = (
                serialize(death_save_row)
                if death_save_row is not None
                else {
                    "combatant_id": own.id,
                    "successes": 0,
                    "failures": 0,
                    "stable": False,
                    "dead": False,
                    "pending_death_confirmation": False,
                    "last_roll": None,
                    "version": 1,
                }
            )
        visibility_scene_id = combat.scene_id or room.current_scene_id
        visibility_scene = (
            session.get(Scene, visibility_scene_id) if visibility_scene_id is not None else None
        )
        visibility_grid = (
            session.scalar(select(SceneGrid).where(SceneGrid.scene_id == visibility_scene.id))
            if visibility_scene is not None
            else None
        )
        fog_enabled = (
            principal.character_id is not None
            and combat.status == "active"
            and visibility_scene is not None
            and visibility_grid is not None
        )
        visible_cells = (
            self._visibility_for(session, visibility_scene, principal, visibility_grid)["visible"]
            if fog_enabled and visibility_scene is not None and visibility_grid is not None
            else set()
        )

        def combatant_position(item: Combatant) -> tuple[int, int] | None:
            raw = item.snapshot_json.get("grid_position")
            if not isinstance(raw, dict) or "row" not in raw or "col" not in raw:
                return None
            return int(raw["row"]), int(raw["col"])

        def combatant_is_visible(item: Combatant) -> bool:
            return (
                not fog_enabled or item.id in own_ids or combatant_position(item) in visible_cells
            )

        visible_fighters = [item for item in fighters if combatant_is_visible(item)]
        visible_fighter_ids = {item.id for item in visible_fighters}
        visible_active = active if active is not None and active.id in visible_fighter_ids else None
        actions = session.scalars(
            select(CombatAction)
            .where(CombatAction.combat_id == combat.id)
            .order_by(CombatAction.created_at.desc())
            .limit(80)
        ).all()
        fighters_by_id = {item.id: item for item in fighters}
        safe_fighters_by_id = {item.id: item for item in visible_fighters}
        active_effects_by_target: dict[str, list[dict[str, Any]]] = {}
        for effect in session.scalars(
            select(CombatEffect).where(
                CombatEffect.combat_id == combat.id,
                CombatEffect.status == "active",
            )
        ).all():
            if effect.target_combatant_id not in safe_fighters_by_id:
                continue
            details = dict(effect.details_json or {})
            raw_block = details.get("rule_block")
            active_effects_by_target.setdefault(effect.target_combatant_id, []).append(
                {
                    "id": effect.id,
                    "name": effect.name,
                    "effect_type": effect.effect_type,
                    "duration_unit": effect.duration_unit,
                    "duration_value": effect.duration_value,
                    "ends_round": effect.ends_round,
                    "trigger_timing": effect.trigger_timing,
                    "rule_block": raw_block if isinstance(raw_block, dict) else None,
                }
            )
        pending = []
        for action in actions:
            if (
                combat.status != "active"
                or action.status != "previewed"
                or not own_ids.intersection(action.target_combatant_ids)
            ):
                continue
            if action.request_json.get("resolution_type"):
                target = (
                    safe_fighters_by_id.get(action.target_combatant_ids[0])
                    if action.target_combatant_ids
                    else None
                )
                raw_dice = target.snapshot_json.get("feature_dice") if target else None
                raw_bardic_die = (
                    raw_dice.get("bardic_inspiration_die")
                    if isinstance(raw_dice, dict)
                    else None
                )
                bardic_inspiration_die = (
                    {
                        "value": raw_bardic_die.get("value"),
                        "source": raw_bardic_die.get("source"),
                    }
                    if isinstance(raw_bardic_die, dict)
                    and raw_bardic_die.get("available") is True
                    else None
                )
                pending.append(
                    {
                        "id": action.id,
                        "version": action.version,
                        "action_name": action.request_json.get("action_name"),
                        "resolution_type": action.request_json.get("resolution_type"),
                        "dc": action.request_json.get("dc"),
                        "ability": action.request_json.get("ability"),
                        "skill": action.request_json.get("skill"),
                        "roll_formula": action.request_json.get("roll_formula", "1d20"),
                        "description": action.request_json.get("description"),
                        "actor_combatant_id": action.actor_combatant_id,
                        "actor_name": action.request_json.get("actor_name"),
                        "target_combatant_id": (
                            action.target_combatant_ids[0] if action.target_combatant_ids else None
                        ),
                        "target_name": action.request_json.get("target_name"),
                        "effect_target_combatant_id": action.request_json.get(
                            "effect_target_combatant_id"
                        ),
                        "effect_target_name": action.request_json.get("effect_target_name"),
                        "damage_on_success": action.request_json.get("damage_on_success", 0),
                        "damage_on_failure": action.request_json.get("damage_on_failure", 0),
                        "damage_type": action.request_json.get("damage_type"),
                        "damage_components_on_success": action.request_json.get(
                            "damage_components_on_success", []
                        ),
                        "damage_components_on_failure": action.request_json.get(
                            "damage_components_on_failure", []
                        ),
                        "damage_tags": action.request_json.get("damage_tags", []),
                        "action_cost": action.request_json.get("action_cost", "none"),
                        "legendary_cost": action.request_json.get("legendary_cost"),
                        "legendary_pool_max": action.request_json.get("legendary_pool_max"),
                        "reaction_trigger": action.request_json.get("reaction_trigger"),
                        "sequence_step": action.request_json.get("sequence_step"),
                        "sequence_size": action.request_json.get("sequence_size"),
                        "bardic_inspiration_die": bardic_inspiration_die,
                    }
                )

        active_action: dict[str, Any] | None = None
        if active is not None and self._is_enemy_ai_controlled(active):
            active_actions = self._combatant_actions(session, active)
            pending_action_name = next(
                (
                    str(item.get("action_name"))
                    for item in pending
                    if item.get("actor_combatant_id") == active.id
                    and item.get("action_name")
                ),
                None,
            )
            if pending_action_name:
                active_action = next(
                    (
                        dict(item)
                        for item in active_actions
                        if isinstance(item, dict)
                        and str(item.get("name") or "") == pending_action_name
                    ),
                    None,
                )
            active_action = active_action or self._active_monster_action(
                active_actions,
                combat.round_number,
                active.snapshot_json,
            )

        def action_is_visible(action: CombatAction) -> bool:
            if not fog_enabled:
                return True
            if own_ids and (
                action.actor_combatant_id in own_ids
                or own_ids.intersection(action.target_combatant_ids)
            ):
                return True
            actor = fighters_by_id.get(action.actor_combatant_id or "")
            if actor is not None and actor.id in visible_fighter_ids:
                return True
            for key in ("to_position", "from_position"):
                raw_position = action.request_json.get(key)
                if (
                    isinstance(raw_position, dict)
                    and "row" in raw_position
                    and "col" in raw_position
                ):
                    if (int(raw_position["row"]), int(raw_position["col"])) in visible_cells:
                        return True
            return False

        def public_damage_components(raw: object) -> list[dict[str, object]]:
            """Keep the typed damage audit trail in the player-safe snapshot."""

            if not isinstance(raw, list):
                return []
            result: list[dict[str, object]] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                damage_type = str(item.get("damage_type") or "").strip()
                if not damage_type or damage_type.lower() in {"mixed", "复合", "多种"}:
                    continue
                component: dict[str, object] = {"damage_type": damage_type}
                for key in (
                    "original_damage",
                    "adjusted_damage",
                    "modifier",
                    "temporary_hp_lost",
                    "hp_lost",
                    "unapplied_damage",
                    "amount",
                ):
                    value = item.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        component[key] = int(value)
                tags = item.get("damage_tags")
                if isinstance(tags, list):
                    component["damage_tags"] = [
                        str(tag).strip() for tag in tags if str(tag).strip()
                    ]
                result.append(component)
            return result

        def public_damage_details(action: CombatAction) -> dict[str, object]:
            result_json = action.result_json if isinstance(action.result_json, dict) else {}
            details: dict[str, object] = {
                "damage_type": result_json.get("damage_type"),
                "damage_components": public_damage_components(
                    result_json.get("damage_components")
                ),
            }
            raw_target_results = result_json.get("target_results")
            if isinstance(raw_target_results, list):
                by_target: list[dict[str, object]] = []
                for target_result in raw_target_results:
                    if not isinstance(target_result, dict):
                        continue
                    target_id = target_result.get("target_combatant_id")
                    if not isinstance(target_id, str) or target_id not in safe_fighters_by_id:
                        continue
                    damage = target_result.get("damage")
                    if not isinstance(damage, dict):
                        continue
                    components = public_damage_components(damage.get("damage_components"))
                    if components:
                        by_target.append(
                            {
                                "target_combatant_id": target_id,
                                "target_name": safe_fighters_by_id[target_id].display_name,
                                "damage_components": components,
                            }
                        )
                if by_target:
                    details["damage_components_by_target"] = by_target
            return details

        pending_reactions: list[dict[str, Any]] = []
        if principal.character_id is not None:
            for request in session.scalars(
                select(PlayerActionRequest).where(
                    PlayerActionRequest.campaign_id == room.campaign_id,
                    PlayerActionRequest.character_id == principal.character_id,
                    PlayerActionRequest.player_key == principal.session_id,
                    PlayerActionRequest.action_type == "opportunity_reaction",
                    PlayerActionRequest.status == "pending",
                ).order_by(PlayerActionRequest.created_at)
            ).all():
                payload = dict(request.payload_json or {})
                pending_reactions.append(
                    {
                        "id": request.id,
                        "version": request.version,
                        "source_name": payload.get("source_name"),
                        "source_action_name": payload.get("source_action_name"),
                        "damage_expression": payload.get("damage_expression"),
                        "damage_type": payload.get("damage_type"),
                        "target_name": payload.get("target_name"),
                        "reaction_trigger": payload.get("reaction_trigger"),
                        "message": request.message,
                    }
                )
            for window in session.scalars(
                select(CombatAction).where(
                    CombatAction.combat_id == combat.id,
                    CombatAction.action_type == "eligible_action_window",
                    CombatAction.actor_combatant_id.in_(own_ids),
                ).order_by(CombatAction.created_at, CombatAction.id)
            ).all():
                metadata = dict((window.result_json or {}).get("action_window") or {})
                if (
                    metadata.get("phase") not in {"pre_damage", "deflect_redirect"}
                    or metadata.get("status") != "pending"
                ):
                    continue
                if metadata.get("phase") == "deflect_redirect":
                    candidate_ids = [
                        str(item)
                        for item in metadata.get("candidate_target_ids", [])
                        if isinstance(item, str) and item in safe_fighters_by_id
                    ]
                    candidate_names = {
                        candidate_id: safe_fighters_by_id[candidate_id].display_name
                        for candidate_id in candidate_ids
                    }
                    pending_reactions.append(
                        {
                            "id": window.id,
                            "version": window.version,
                            "kind": "deflect_redirect",
                            "feature_id": metadata.get("feature_id"),
                            "feature_name": metadata.get("feature_name"),
                            "source_name": metadata.get("trigger_combatant_name"),
                            "source_action_name": metadata.get("source_action_name"),
                            "target_name": metadata.get("reactor_combatant_name"),
                            "reaction_trigger": "偏转攻击伤害归零",
                            "message": window.summary,
                            "candidate_target_ids": candidate_ids,
                            "candidate_target_names": candidate_names,
                            "save_ability": metadata.get("save_ability"),
                            "save_dc": metadata.get("save_dc"),
                            "damage_die_expression": metadata.get("damage_die_expression"),
                            "damage_die_sides": metadata.get("damage_die_sides"),
                            "damage_dice_count": metadata.get("damage_dice_count"),
                            "damage_modifier": metadata.get("damage_modifier"),
                            "damage_type": metadata.get("damage_type"),
                            "resource_key": metadata.get("resource_key"),
                            "resource_cost": metadata.get("resource_cost"),
                        }
                    )
                    continue
                raw_candidates = metadata.get("candidate_interventions")
                candidate_features = []
                if isinstance(raw_candidates, dict):
                    for candidate_id, raw_candidate in raw_candidates.items():
                        if not isinstance(raw_candidate, dict):
                            continue
                        raw_intervention = raw_candidate.get("intervention")
                        raw_requirements = (
                            raw_intervention.get("input_requirements")
                            if isinstance(raw_intervention, dict)
                            else []
                        )
                        requires_roll = any(
                            isinstance(item, dict)
                            and item.get("key") == "reduction_roll"
                            for item in raw_requirements or []
                        )
                        candidate_features.append(
                            {
                                "id": str(candidate_id),
                                "name": raw_candidate.get("feature_name") or candidate_id,
                                "requires_reduction_roll": requires_roll,
                                "damage_reduction_formula": metadata.get(
                                    "damage_reduction_formula"
                                ),
                                "damage_reduction_bonus": (
                                    int(raw_candidate.get("dexterity_modifier") or 0)
                                    + int(raw_candidate.get("class_level") or 1)
                                    if requires_roll
                                    else None
                                ),
                            }
                        )
                pending_reactions.append(
                    {
                        "id": window.id,
                        "version": window.version,
                        "kind": "pre_damage",
                        "feature_id": metadata.get("feature_id"),
                        "feature_name": metadata.get("feature_name"),
                        "candidate_features": candidate_features,
                        "requires_reduction_roll": metadata.get("requires_reduction_roll", False),
                        "damage_reduction_formula": metadata.get("damage_reduction_formula"),
                        "damage_reduction_bonus": (
                            int(metadata.get("dexterity_modifier") or 0)
                            + int(metadata.get("class_level") or 1)
                            if metadata.get("requires_reduction_roll")
                            else None
                        ),
                        "eligible_damage_types": metadata.get("eligible_damage_types"),
                        "source_name": metadata.get("trigger_combatant_name"),
                        "source_action_name": metadata.get("trigger_action_name"),
                        "damage_expression": None,
                        "damage_type": None,
                        "target_name": metadata.get("hit_combatant_name"),
                        "reaction_trigger": "被攻击命中（伤害尚未落地）",
                        "message": window.summary,
                    }
                )

        return {
            "id": combat.id,
            "version": combat.version,
            "name": combat.name,
            "status": combat.status,
            "round_number": combat.round_number,
            "current_turn_index": combat.current_turn_index,
            "active_combatant_id": visible_active.id if visible_active else None,
            "is_my_turn": active is not None and active.id in own_ids,
            "own_combatant_id": own.id if own else None,
            "own_combatant_ids": sorted(own_ids),
            "combatants": [
                self._safe_combatant(
                    session,
                    item,
                    own_ids,
                    active_effects_by_target.get(item.id, []),
                    active_action if active is not None and item.id == active.id else None,
                )
                for item in visible_fighters
            ],
            "log": [
                {
                    "id": action.id,
                    "summary": action.summary,
                    "round_number": action.round_number,
                    "turn_index": action.turn_index,
                    "status": action.status,
                    "action_type": action.action_type,
                    "actor_combatant_id": action.actor_combatant_id,
                    "actor_name": (
                        fighters_by_id[action.actor_combatant_id].display_name
                        if action.actor_combatant_id in fighters_by_id
                        else None
                    ),
                    "target_combatant_ids": [
                        target_id
                        for target_id in action.target_combatant_ids
                        if target_id in safe_fighters_by_id
                    ],
                    "target_names": [
                        safe_fighters_by_id[target_id].display_name
                        for target_id in action.target_combatant_ids
                        if target_id in safe_fighters_by_id
                    ],
                    "action_name": action.request_json.get("action_name"),
                    "from_position": action.request_json.get("from_position"),
                    "to_position": action.request_json.get("to_position"),
                    "movement_spent_ft": action.request_json.get("movement_spent_ft"),
                    "resolution_type": action.request_json.get("resolution_type"),
                    "dc": action.request_json.get("dc"),
                    "roll_formula": action.request_json.get("roll_formula"),
                    "damage": action.result_json.get(
                        "adjusted_damage",
                        action.result_json.get("damage"),
                    ),
                    **public_damage_details(action),
                    "created_at": action.created_at.isoformat(),
                }
                for action in actions
                if action_is_visible(action)
            ],
            "pending_rolls": pending,
            "pending_reactions": pending_reactions,
            "death_save": death_save,
        }

    @staticmethod
    def _safe_combatant(
        session: Session,
        item: Combatant,
        own_ids: set[str],
        active_effects: list[dict[str, Any]] | None = None,
        active_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        is_own = item.id in own_ids
        ratio = item.hp / max(1, item.max_hp)
        health = (
            "倒地"
            if item.hp <= 0
            else "重伤"
            if ratio <= 0.25
            else "受伤"
            if ratio <= 0.6
            else "状态良好"
        )
        position = (
            item.snapshot_json.get("grid_position")
            if isinstance(item.snapshot_json, dict)
            else None
        )
        result: dict[str, Any] = {
            "id": item.id,
            "version": item.version,
            "name": item.display_name,
            "entity_type": item.entity_type,
            "initiative": item.initiative,
            "position": position,
            "health_status": health,
            "is_own": is_own,
            "controller": item.snapshot_json.get("controller"),
            "owner_character_id": item.snapshot_json.get("owner_character_id"),
            "disposition": item.snapshot_json.get("disposition"),
            # The shared battle card exposes deterministic combat statistics
            # needed for assisted play. DM notes and unrevealed narrative
            # identity remain outside this snapshot.
            "armor_class": item.armor_class,
            "hp": item.hp,
            "max_hp": item.max_hp,
            "temporary_hp": item.temporary_hp,
            "conditions": item.conditions,
            "speed_ft": item.speed_ft,
            "ability_scores": json_dict(item.snapshot_json.get("ability_scores")),
            "actions": PlayerRoomService._combatant_actions(session, item),
            "active_action": active_action,
            "damage_resistances": item.damage_resistances,
            "damage_vulnerabilities": item.damage_vulnerabilities,
            "damage_immunities": item.damage_immunities,
            "active_effects": active_effects or [],
        }
        if is_own:
            result.update(
                {
                    "movement_remaining_ft": item.movement_remaining_ft,
                    "action_available": item.action_available,
                    "bonus_action_available": item.bonus_action_available,
                    "reaction_available": item.reaction_available,
                    "extra_action_budget": int(
                        item.snapshot_json.get("extra_action_budget") or 0
                    ),
                    "attack_roll_budget": int(
                        item.snapshot_json.get("attack_roll_budget") or 0
                    ),
                    "bardic_inspiration_die": (
                        {
                            "value": item.snapshot_json.get("feature_dice", {})
                            .get("bardic_inspiration_die", {})
                            .get("value"),
                            "source": item.snapshot_json.get("feature_dice", {})
                            .get("bardic_inspiration_die", {})
                            .get("source"),
                        }
                        if isinstance(item.snapshot_json.get("feature_dice"), dict)
                        and isinstance(
                            item.snapshot_json.get("feature_dice", {}).get(
                                "bardic_inspiration_die"
                            ),
                            dict,
                        )
                        and item.snapshot_json.get("feature_dice", {})
                        .get("bardic_inspiration_die", {})
                        .get("available")
                        is True
                        else None
                    ),
                }
            )
        if item.entity_type == "companion" and "summon_source" in item.snapshot_json:
            duration = item.snapshot_json.get("summon_duration")
            result["summon"] = {
                "source_combatant_id": item.snapshot_json.get("summon_source_combatant_id"),
                "lifecycle_effect_id": item.snapshot_json.get("summon_lifecycle_effect_id"),
                "duration": duration if isinstance(duration, dict) else None,
                "enemy_ai_mode": item.snapshot_json.get("enemy_ai_mode"),
            }
        return result

    @staticmethod
    def _active_monster_action(
        actions: list[Any],
        round_number: int,
        snapshot: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Expose the same deterministic standard-AI action window to players.

        The DM console may still override the tactic locally, but the default
        simulation uses the standard round-seeded selection.  Publishing the
        selected structured action makes the player's range preview stable
        before a saving-throw prompt exists.
        """
        recharge = snapshot.get("recharge_available")
        recharge_state = recharge if isinstance(recharge, dict) else None
        eligible: list[dict[str, Any]] = []
        for index, raw in enumerate(actions):
            if not isinstance(raw, dict):
                continue
            action = dict(raw)
            if action.get("auto_eligible") is False:
                continue
            action_type = action.get("action_type")
            if action_type not in (None, "action", "bonus_action", "spellcasting"):
                continue
            has_damage_dice = bool(re.search(r"\d+\s*d\s*\d+", str(action.get("damage") or "")))
            if not has_damage_dice and not action.get("multiattack"):
                continue
            recharge_value = action.get("recharge")
            if recharge_state is not None and recharge_value:
                key = str(action.get("name") or f"action-{index + 1}")
                if recharge_state.get(key) is not True:
                    continue
            eligible.append(action)
        if not eligible:
            return None
        return eligible[abs(round_number) % len(eligible)]

    @staticmethod
    def _combatant_actions(session: Session, item: Combatant) -> list[Any]:
        raw_actions = (
            item.snapshot_json.get("actions") if isinstance(item.snapshot_json, dict) else []
        )
        actions = (
            [dict(raw) if isinstance(raw, dict) else raw for raw in raw_actions]
            if isinstance(raw_actions, list)
            else []
        )
        registry = item.snapshot_json.get("feature_runtime")
        if isinstance(registry, dict):
            existing_names = {
                str(action.get("name") or "")
                for action in actions
                if isinstance(action, dict)
            }
            actions.extend(
                action
                for action in feature_runtime_action_projections(registry)
                if str(action.get("name") or "") not in existing_names
            )
        if item.entity_type != "character" or not item.entity_id:
            return actions
        known_spells = session.scalars(
            select(KnownSpell).where(KnownSpell.character_id == item.entity_id)
        ).all()
        by_name = {spell.name: dict(spell.metadata_json or {}) for spell in known_spells}
        for action in actions:
            if not isinstance(action, dict):
                continue
            metadata = by_name.get(str(action.get("name") or ""), {})
            source = metadata.get("character_spell")
            source_fields = dict(source) if isinstance(source, dict) else metadata
            for key in (
                "damage",
                "damage_expression",
                "damage_dice",
                "damage_type",
                "save_ability",
                "save_dc",
                "half_damage_on_save",
                "range",
                "description",
                "cost",
                "resource_key",
                "resource_cost",
                "resolution_kind",
                "rule_plan",
            ):
                if source_fields.get(key) not in (None, ""):
                    action[key] = source_fields[key]
            PlayerRoomService._attach_attack_riders(
                action,
                registry if isinstance(registry, dict) else None,
            )
        return actions

    def submit_request(
        self,
        principal: PlayerPrincipal,
        action_type: str,
        message: str,
        payload: dict[str, Any],
        idempotency_key: str,
        request_id: str,
    ) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        if action_type == "site_level_transition":
            with Session(self.engine) as session:
                room = session.get(PlayerRoom, principal.room_id)
                scene = (
                    session.get(Scene, room.current_scene_id)
                    if room is not None and room.current_scene_id
                    else None
                )
                if room is None or scene is None:
                    raise ValueError("DM 尚未发布可切换楼层的当前场景")
                safe_scene = self._safe_scene(session, scene, principal)
                connector_id = str(payload.get("connector_id") or "")
                transition = next(
                    (
                        item
                        for item in safe_scene.get("available_transitions", [])
                        if item.get("connector_id") == connector_id
                    ),
                    None,
                )
                if transition is None:
                    raise ValueError("尚未探索到该楼梯，或楼层连接已经变化")
                payload = {"schema_version": "1.0", **transition}
                message = message or f"申请{transition['label']}：{transition['target_level_name']}"
        character = self.player.character_view(principal.campaign_id, principal.character_id)
        if action_type == "rest_request":
            rest_type = str(payload.get("rest_type") or "")
            if rest_type not in {"short", "long"}:
                raise ValueError("休息申请必须选择短休或长休")
            with Session(self.engine) as session:
                existing = session.scalar(
                    select(PlayerActionRequest).where(
                        PlayerActionRequest.campaign_id == principal.campaign_id,
                        PlayerActionRequest.character_id == principal.character_id,
                        PlayerActionRequest.action_type == "rest_request",
                        PlayerActionRequest.status == "pending",
                    )
                )
            if existing is not None:
                raise ValueError("已有一条待 DM 处理的休息申请")
            raw_hit_dice = payload.get("hit_dice", [])
            if raw_hit_dice is None:
                raw_hit_dice = []
            if not isinstance(raw_hit_dice, list):
                raise ValueError("短休生命骰选择格式无效")
            pools_by_id = {
                str(pool["id"]): pool
                for pool in self._player_hit_dice(principal.campaign_id, principal.character_id)
            }
            usage_by_pool: dict[str, int] = {}
            normalized_hit_dice: list[dict[str, Any]] = []
            for raw_selection in raw_hit_dice:
                if not isinstance(raw_selection, dict):
                    raise ValueError("短休生命骰选择格式无效")
                pool_id = str(raw_selection.get("resource_pool_id") or "")
                pool = pools_by_id.get(pool_id)
                if pool is None:
                    raise ValueError("只能选择当前角色的生命骰")
                die_size = int(pool.get("die_size") or 0)
                raw_roll = raw_selection.get("roll")
                if raw_roll is None:
                    raise ValueError("生命骰结果必须是整数")
                try:
                    roll = int(str(raw_roll))
                except (TypeError, ValueError) as exc:
                    raise ValueError("生命骰结果必须是整数") from exc
                if roll < 1 or roll > die_size:
                    raise ValueError(f"生命骰结果必须在 1–{die_size} 之间")
                usage_by_pool[pool_id] = usage_by_pool.get(pool_id, 0) + 1
                if usage_by_pool[pool_id] > int(pool["current"]):
                    raise ValueError("选择的生命骰数量超过当前可用数量")
                normalized_hit_dice.append({"resource_pool_id": pool_id, "roll": roll})
            payload = {
                "schema_version": "1.0",
                "rest_type": rest_type,
                "duration_minutes": 60 if rest_type == "short" else 480,
                "interrupted": False,
                "fallback_to_short_rest": False,
                "participants": [
                    {
                        "character_id": principal.character_id,
                        "character_version": int(character["version"]),
                        "hit_dice": normalized_hit_dice if rest_type == "short" else [],
                        "excluded_resource_keys": [],
                    }
                ],
            }
            message = message or f"申请进行{'短休' if rest_type == 'short' else '长休'}。"
        request_data = {
            "character_id": principal.character_id,
            "character_version": character["version"],
            "player_key": principal.session_id,
            "action_type": action_type,
            "message": message,
            "payload_json": payload,
            "idempotency_key": idempotency_key,
        }
        try:
            return self.player.submit_action(
                principal.campaign_id,
                request_data,
                request_id,
            )
        except IntegrityError as exc:
            with Session(self.engine) as session:
                existing = session.scalar(
                    select(PlayerActionRequest).where(
                        PlayerActionRequest.campaign_id == principal.campaign_id,
                        PlayerActionRequest.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    return serialize(existing)
                pending_rest = session.scalar(
                    select(PlayerActionRequest).where(
                        PlayerActionRequest.campaign_id == principal.campaign_id,
                        PlayerActionRequest.character_id == principal.character_id,
                        PlayerActionRequest.action_type == "rest_request",
                        PlayerActionRequest.status == "pending",
                    )
                )
            if pending_rest is not None:
                raise ValueError("已有一条待 DM 处理的休息申请") from exc
            raise

    def plan_noncombat_action(
        self,
        principal: PlayerPrincipal,
        data: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session, session.begin():
            room = session.get(PlayerRoom, principal.room_id)
            if room is None or room.campaign_id != principal.campaign_id:
                raise StateNotFoundError("player room not found")
            self._active(room)
            if room.current_scene_id is None:
                raise ValueError("DM 尚未选择当前 Scene")
            if room.current_combat_id:
                combat = session.get(Combat, room.current_combat_id)
                if combat is not None and combat.status == "active":
                    raise ValueError("战斗中请使用战斗面板，不能提交非战斗行动")
            scene = session.get(Scene, room.current_scene_id)
            character = session.get(Character, principal.character_id)
            if scene is None or character is None:
                raise StateNotFoundError("current scene or character not found")
            available = self._noncombat_snapshot(session, room, principal)["available_actions"]
            action = next((item for item in available if item["id"] == data["action_id"]), None)
            if action is None:
                raise ValueError("该能力不在角色当前可用的非战斗行动中")

            target_type = str(data.get("target_type") or "area")
            target_id = str(data.get("target_id") or "")
            if target_type not in action["target_types"]:
                raise ValueError("该能力不能选择这种目标")
            target: dict[str, Any] = {"type": target_type, "id": target_id, "name": "当前区域"}
            target_position: dict[str, int] | None = None
            target_scores: dict[str, int] | None = None
            target_object: SceneObject | None = None
            if target_type == "self":
                target.update(id=character.id, name=character.name)
            elif target_type == "object":
                target_object = session.get(SceneObject, target_id)
                if (
                    target_object is None
                    or target_object.scene_id != scene.id
                    or target_object.visibility != "public"
                ):
                    raise ValueError("目标物体不在当前公开 Scene 中")
                target.update(name=target_object.label, state=target_object.state)
                target_position = {"row": target_object.row, "col": target_object.col}
            elif target_type in {"npc", "monster"}:
                token = session.scalar(
                    select(SceneToken).where(
                        SceneToken.scene_id == scene.id,
                        SceneToken.entity_type == target_type,
                        SceneToken.entity_id == target_id,
                        SceneToken.visible.is_(True),
                    )
                )
                if token is None:
                    raise ValueError("目标不在当前公开 Scene 中")
                entity = (
                    session.get(NPC, target_id)
                    if target_type == "npc"
                    else session.get(MonsterInstance, target_id)
                )
                if entity is None or entity.campaign_id != principal.campaign_id:
                    raise ValueError("目标原子不存在")
                target.update(name=entity.name)
                target_position = {"row": token.row, "col": token.col}
                target_scores = dict(entity.ability_scores or {})

            actor_token = session.scalar(
                select(SceneToken).where(
                    SceneToken.scene_id == scene.id,
                    SceneToken.entity_type == "character",
                    SceneToken.entity_id == character.id,
                    SceneToken.visible.is_(True),
                )
            )
            actor_position = (
                {"row": actor_token.row, "col": actor_token.col} if actor_token else None
            )
            grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene.id))
            measured_range = grid_range_ft(
                actor_position,
                target_position,
                grid.cell_size_ft if grid else 5,
            )
            range_text = str(action.get("range") or "")
            match = re.search(r"(\d+)\s*(?:ft|feet|foot|尺)", range_text.lower())
            maximum_range = int(match.group(1)) if match else None
            raw_plan = action.get("rule_plan")
            target_block = (
                next(
                    (
                        block
                        for block in raw_plan.get("blocks", [])
                        if isinstance(block, dict) and block.get("kind") == "target"
                    ),
                    None,
                )
                if isinstance(raw_plan, dict) and isinstance(raw_plan.get("blocks"), list)
                else None
            )
            if maximum_range is None and isinstance(target_block, dict):
                plan_range = target_block.get("range_ft")
                if isinstance(plan_range, int) and plan_range > 0:
                    maximum_range = plan_range
            if (
                maximum_range is not None
                and measured_range is not None
                and measured_range > maximum_range
            ):
                raise ValueError(f"目标距离 {measured_range} 尺，超过该能力 {maximum_range} 尺范围")

            plan: dict[str, Any] = {
                "schema_version": "1.0",
                "phase": "resolved",
                "scene": {"id": scene.id, "name": scene.name},
                "actor": {"type": "character", "id": character.id, "name": character.name},
                "target": target,
                "action": action,
                "eligibility": {
                    "owned": True,
                    "prepared": True,
                    "range_ft": measured_range,
                    "maximum_range_ft": maximum_range,
                },
                "cost": {
                    "resource_key": action.get("resource_key"),
                    "amount": int(action.get("resource_cost") or 0),
                    "consume_on_dm_accept": True,
                },
                "resolution": {"kind": "narrative", "requires_dm_confirmation": True},
                "proposal": {
                    "kind": "narrative",
                    "summary": "按规则结果推进叙事；具体世界状态由 DM 确认。",
                },
                "automation": self._manual_automation(
                    "默认不自动改变场景、角色或隐藏信息；由 DM 确认具体后果。"
                ),
                "narrative_suggestions": [
                    "描述行动造成的直接可见变化。",
                    "给出目标反应，并保留 DM 对隐情与后果的裁量。",
                    "若行动改变 Scene 状态，把变化写入公开推进日志。",
                ],
            }
            kind = str(action["kind"])
            if (
                kind == "tool"
                and target_object is not None
                and target_object.object_type not in {"door", "trap", "treasure", "portal"}
            ):
                raise ValueError("盗贼工具只能用于门、锁具、机关、宝箱或传送机关")
            if kind in {"skill", "tool"}:
                skill = "巧手" if kind == "tool" else str(action["name"])
                ability = str(action["ability"])
                modifier, reasons = skill_modifier(character, skill, ability)
                interaction = target_object.interaction_json if target_object else {}
                dc = int(str(interaction.get("dc") or action.get("suggested_dc") or 12))
                plan["phase"] = "awaiting_player_roll"
                plan["resolution"] = {
                    "kind": "ability_check",
                    "roll_owner": "player",
                    "raw_roll_formula": "1d20",
                    "ability": ability,
                    "ability_label": ABILITY_LABELS[ability],
                    "skill": skill,
                    "modifier": modifier,
                    "modifier_reasons": reasons,
                    "dc": dc,
                    "instruction": (
                        f"请玩家掷 1d20 并输入裸骰。系统会加 {modifier:+d}；"
                        f"最终总值需达到 DC {dc}（≥ {dc}）。"
                    ),
                    "requires_dm_confirmation": True,
                }
                if kind == "tool" and target_object is not None:
                    desired_state = "disarmed" if target_object.object_type == "trap" else "open"
                    plan["proposal"] = {
                        "kind": "object_state",
                        "object_id": target_object.id,
                        "from_state": target_object.state,
                        "to_state": desired_state,
                        "summary": f"成功后将「{target_object.label}」标记为{desired_state}。",
                    }
                    plan["automation"] = {
                        "status": "pending_player_roll",
                        "mode": "dm_confirmed_object_state",
                        "operation": "set_object_state",
                        "apply_on_dm_accept": True,
                        "requires_dm_confirmation": True,
                    }
            elif kind == "spell":
                if action.get("ritual_only") is True and data.get("ritual") is not True:
                    raise ValueError("该法术特性仅限以仪式施展；请明确提交 ritual=true")
                resource_key = action.get("resource_key")
                resource_cost = int(action.get("resource_cost") or 0)
                if resource_key and resource_cost:
                    resource = (character.resources or {}).get(str(resource_key))
                    current = int(resource.get("current") or 0) if isinstance(resource, dict) else 0
                    if current < resource_cost:
                        raise ValueError("对应法术位或资源不足")
                    plan["cost"]["available_before"] = current
                    plan["cost"]["available_after"] = current - resource_cost
                safe_execution = self._safe_pr_spell_execution(
                    action=action,
                    target=target,
                    target_object=target_object,
                )
                if safe_execution is not None:
                    plan.update(safe_execution)
                elif "命令" in str(action["name"]):
                    if target_scores is None:
                        raise ValueError("命令术必须选择当前 Scene 中的 NPC 或怪物")
                    dc = int(action.get("save_dc") or 10)
                    save = roll_save(target_scores, "wisdom", dc)
                    plan["resolution"] = {
                        "kind": "saving_throw",
                        "roll_owner": "system",
                        "save": save,
                        "requires_dm_confirmation": True,
                    }
                    plan["proposal"] = {
                        "kind": "narrative",
                        "summary": (
                            f"{target['name']}感知豁免"
                            + (
                                "成功，通常不受命令影响。"
                                if save["success"]
                                else "失败，建议按命令术文本执行到其下一回合。"
                            )
                        ),
                    }
                    plan["automation"] = {
                        "status": "ready_for_dm_confirmation",
                        "mode": "dm_confirmed_result",
                        "operation": "record_save_result",
                        "apply_on_dm_accept": False,
                        "requires_dm_confirmation": True,
                    }
                elif "隐形" in str(action["name"]):
                    plan["proposal"] = {
                        "kind": "condition_advice",
                        "condition": "隐形",
                        "concentration": True,
                        "summary": "建议记录目标隐形与施法者专注；具体可见性由 DM 裁定。",
                    }
                    plan["automation"] = {
                        "status": "ready_for_dm_confirmation",
                        "mode": "dm_confirmed_result",
                        "operation": "record_condition_advice",
                        "apply_on_dm_accept": False,
                        "requires_dm_confirmation": True,
                    }
            item = PlayerActionRequest(
                campaign_id=principal.campaign_id,
                character_id=character.id,
                character_version=character.version,
                player_key=principal.session_id,
                action_type="noncombat_rule",
                message=str(data.get("message") or f"{character.name}使用{action['name']}"),
                payload_json=plan,
                idempotency_key=str(data["idempotency_key"]),
            )
            existing = session.scalar(
                select(PlayerActionRequest).where(
                    PlayerActionRequest.campaign_id == principal.campaign_id,
                    PlayerActionRequest.idempotency_key == item.idempotency_key,
                )
            )
            if existing is not None:
                return serialize(existing)
            session.add(item)
            session.flush()
            return serialize(item)

    def roll_noncombat_action(
        self,
        principal: PlayerPrincipal,
        action_request_id: str,
        expected_version: int,
        raw_roll: int,
    ) -> dict[str, Any]:
        if raw_roll < 1 or raw_roll > 20:
            raise ValueError("请输入 d20 的裸骰结果（1–20）")
        with Session(self.engine) as session, session.begin():
            item = session.get(PlayerActionRequest, action_request_id)
            if (
                item is None
                or item.campaign_id != principal.campaign_id
                or item.player_key != principal.session_id
                or item.character_id != principal.character_id
                or item.action_type != "noncombat_rule"
            ):
                raise StateNotFoundError("noncombat action request not found")
            if item.version != expected_version:
                raise VersionConflict(
                    "player_action_request", item.id, expected_version, item.version
                )
            payload = dict(item.payload_json or {})
            if payload.get("phase") != "awaiting_player_roll":
                return serialize(item)
            resolution = json_dict(payload.get("resolution"))
            modifier = int(resolution.get("modifier") or 0)
            dc = int(resolution.get("dc") or 10)
            reported_raw_roll = raw_roll
            skill_name = str(resolution.get("skill") or "")
            character = session.get(Character, item.character_id)
            reliable_talent = bool(
                character is not None
                and skill_name
                and self._reliable_talent_applies(character, skill_name)
            )
            if reliable_talent:
                raw_roll = max(raw_roll, 10)
            total = raw_roll + modifier
            resolution.update(
                raw_roll=raw_roll,
                reported_raw_roll=reported_raw_roll,
                **(
                    {"applied_features": ["可靠才能"]}
                    if reliable_talent
                    else {}
                ),
                total=total,
                success=total >= dc,
                instruction=(
                    (
                        f"报告裸骰 {reported_raw_roll}；可靠才能按 10 计入；"
                        if reliable_talent
                        else f"裸骰 {raw_roll} "
                    )
                    + f"{modifier:+d} = {total}；"
                    f"DC {dc}，{'成功' if total >= dc else '失败'}。"
                ),
            )
            payload["phase"] = "resolved"
            payload["resolution"] = resolution
            proposal = json_dict(payload.get("proposal"))
            automation = json_dict(payload.get("automation"))
            if not total >= dc and proposal.get("kind") == "object_state":
                proposal = {
                    "kind": "narrative",
                    "summary": "检定失败；不改变物体状态，DM 可描述代价、时间或暴露风险。",
                }
                automation.update(
                    status="failed",
                    apply_on_dm_accept=False,
                    reason="检定失败，已取消待确认的物体状态变更。",
                )
            elif total >= dc and automation.get("status") == "pending_player_roll":
                automation["status"] = "ready_for_dm_confirmation"
            payload["proposal"] = proposal
            payload["automation"] = automation
            item.payload_json = payload
            item.version += 1
            item.updated_at = _now()
            session.flush()
            return serialize(item)

    def summon(
        self,
        principal: PlayerPrincipal,
        companion_id: str,
        action_name: str,
        count: int,
        position: dict[str, int] | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Use an existing player-owned creature template in the current combat."""
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            companion = session.get(CharacterCompanion, companion_id)
            if (
                companion is None
                or companion.campaign_id != principal.campaign_id
                or companion.owner_character_id != principal.character_id
                or not companion.active
            ):
                raise ValueError("只能召唤当前角色自己的有效伙伴模板")
            fighters = self._ordered_fighters(session, combat.id)
            active = (
                fighters[combat.current_turn_index]
                if fighters and combat.current_turn_index < len(fighters)
                else None
            )
            source = self._controlled_actor(fighters, active, principal.character_id)
            if source is None:
                raise ValueError("现在还没有轮到你的角色或你的召唤单位")
            character = session.get(Character, principal.character_id)
            if character is None:
                raise StateNotFoundError("character not found")
            action = (
                self._action_data(session, character, action_name)
                if source.entity_type == "character"
                else self._companion_action_data(source, action_name)
            )
            plan = action.get("rule_plan")
            blocks = plan.get("blocks", []) if isinstance(plan, dict) else []
            summon_block = next(
                (
                    block
                    for block in blocks
                    if isinstance(block, dict) and block.get("kind") == "summon"
                ),
                None,
            )
            if not isinstance(summon_block, dict):
                raise ValueError("当前动作没有明确的召唤积木")
            if summon_block.get("controller") not in {None, "caster"}:
                raise ValueError("该召唤积木不是玩家可直接控制的召唤；请由 DM 按模板处理")
            declared_count = summon_block.get("count")
            if isinstance(declared_count, int) and not isinstance(declared_count, bool):
                if count != declared_count:
                    raise ValueError("该召唤的数量已在规则积木中明确，必须按明确数量执行")
            elif summon_block.get("count_expression") and not isinstance(count, int):
                raise ValueError("数量表达式的召唤必须由玩家明确提交实际数量")
            elif summon_block.get("count_expression"):
                allowed_counts = explicit_count_outcomes(
                    str(summon_block["count_expression"])
                )
                if allowed_counts and count not in allowed_counts:
                    formatted = "、".join(str(value) for value in allowed_counts)
                    raise ValueError(f"该召唤的明确数量只能是：{formatted}")
            raw_initiative_mode = summon_block.get("initiative_mode") or "independent"
            if raw_initiative_mode == "independent":
                initiative_mode: Literal["independent", "shared_with_source", "not_applicable"] = (
                    "independent"
                )
            elif raw_initiative_mode == "shared_with_source":
                initiative_mode = "shared_with_source"
            elif raw_initiative_mode == "not_applicable":
                initiative_mode = "not_applicable"
            else:
                raise ValueError("召唤积木的先攻模式无效")
            if summon_block.get("enters_combat") is False or initiative_mode == "not_applicable":
                raise ValueError("该召唤效果不是独立战斗单位，不能加入先攻")
            duration_block = next(
                (
                    block
                    for block in blocks
                    if isinstance(block, dict) and block.get("kind") == "duration"
                ),
                None,
            )
            raw_duration_unit = (
                str(duration_block.get("unit") or "until_removed")
                if isinstance(duration_block, dict)
                else "until_removed"
            )
            raw_duration_value = (
                int(duration_block.get("value") or 0) if isinstance(duration_block, dict) else 0
            )
            duration_unit: Literal["rounds", "minutes", "until_save", "until_removed"]
            duration_value: int | None
            if raw_duration_unit == "round":
                duration_unit, duration_value = "rounds", raw_duration_value
            elif raw_duration_unit == "minute":
                duration_unit, duration_value = "minutes", raw_duration_value
            elif raw_duration_unit == "hour":
                duration_unit, duration_value = "minutes", raw_duration_value * 60
            elif raw_duration_unit == "day":
                duration_unit, duration_value = "minutes", raw_duration_value * 24 * 60
            elif raw_duration_unit == "until_save":
                duration_unit, duration_value = "until_save", None
            else:
                duration_unit, duration_value = "until_removed", None
            requires_concentration = bool(action.get("concentration")) or bool(
                duration_block.get("concentration") if isinstance(duration_block, dict) else False
            )
            resource_key = str(action.get("resource_key") or "") or None
            resource_cost = int(action.get("resource_cost") or 0)
            combat_id = combat.id
            source_id = source.id
        return self.combat.add_summon(
            principal.campaign_id,
            combat_id,
            CombatSummonCommand(
                companion_id=companion_id,
                position=position,
                controller="player",
                owner_character_id=principal.character_id,
                disposition="ally",
                source_combatant_id=source_id,
                initiative_mode=initiative_mode,
                count=count,
                template_json={
                    "action_name": action_name,
                    "source_type": source.entity_type,
                    "rule_template_ref": summon_block.get("template_ref"),
                    "requires_template_choice": bool(
                        summon_block.get("requires_template_choice", True)
                    ),
                },
                action_cost="action",
                resource_key=resource_key,
                resource_cost=resource_cost,
                duration_unit=duration_unit,
                duration_value=duration_value,
                requires_concentration=requires_concentration,
            ),
            idempotency_key=idempotency_key,
        )

    def dismiss_summon(
        self,
        principal: PlayerPrincipal,
        summon_combatant_id: str,
        summon_version: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Let a player end only their own active summoned unit."""
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            summon = session.get(Combatant, summon_combatant_id)
            if (
                summon is None
                or summon.combat_id != combat.id
                or summon.entity_type != "companion"
                or not self._is_player_controlled(summon, principal.character_id)
            ):
                raise ValueError("只能结束自己控制的召唤物")
            fighters = self._ordered_fighters(session, combat.id)
            active = (
                fighters[combat.current_turn_index]
                if fighters and combat.current_turn_index < len(fighters)
                else None
            )
            if self._controlled_actor(fighters, active, principal.character_id) is None:
                raise ValueError("只能在自己的角色或召唤物回合结束召唤")
            combat_id = combat.id
        return self.combat.end_summon(
            principal.campaign_id,
            combat_id,
            summon_combatant_id,
            CombatSummonEndCommand(summon_version=summon_version, reason=reason, actor="player"),
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _ordered_fighters(session: Session, combat_id: str) -> list[Combatant]:
        return list(
            session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat_id, Combatant.is_active.is_(True))
                .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
            ).all()
        )

    @staticmethod
    def _opportunity_damage_expression(action: dict[str, Any]) -> object:
        for key in ("damage", "damage_expression", "damage_dice"):
            value = action.get(key)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _opportunity_attack_action(actions: object) -> dict[str, Any] | None:
        """Choose a structured melee action eligible for an opportunity attack.

        Older imported monsters often omit ``range_ft``; those actions remain
        usable as a compatibility fallback.  Once a range or area is declared,
        fail closed for ranged/area actions instead of borrowing the first
        damage-bearing action (which could be a bow, spell, or breath attack).
        """

        if not isinstance(actions, list):
            return None
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        for index, raw in enumerate(actions):
            if (
                not isinstance(raw, dict)
                or PlayerRoomService._opportunity_damage_expression(raw) is None
            ):
                continue
            action_type = str(raw.get("action_type") or "action").strip().lower()
            if action_type in {"lair_action", "legendary_action", "spellcasting"}:
                continue
            if raw.get("area_shape") or raw.get("affects_multiple_targets"):
                continue
            if raw.get("ranged") is True or str(raw.get("attack_type") or "").lower() == "ranged":
                continue
            raw_range = raw.get("range_ft")
            if isinstance(raw_range, bool):
                continue
            if raw_range is not None:
                try:
                    if int(raw_range) > 5:
                        continue
                except (TypeError, ValueError):
                    continue
            explicit_reaction = action_type in {"reaction", "opportunity_attack"}
            candidates.append((0 if explicit_reaction else 1, index, raw))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    @staticmethod
    def _rule_expression_supported(expression: object) -> bool:
        """Validate a dice expression without consuming a random roll."""

        raw = str(expression or "").replace(" ", "")
        if raw.isdigit():
            return True
        match = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", raw, re.IGNORECASE)
        if not match:
            return False
        count = int(match.group(1) or "1")
        sides = int(match.group(2))
        modifier = int(match.group(3) or "0")
        return count > 0 and sides > 0 and count + modifier >= 0

    @classmethod
    def _automatic_opportunity_supported(cls, action: dict[str, Any]) -> bool:
        """Return whether an opportunity attack can be fully auto-resolved.

        This is intentionally a pure qualification check.  Calling the roll
        implementation here would consume random dice before the attack is
        actually executed, changing gameplay results for no user-visible
        reason.
        """

        attack_bonus = action.get("attack_bonus")
        if not isinstance(attack_bonus, int) or isinstance(attack_bonus, bool):
            return False
        raw_components = action.get("damage_components")
        if isinstance(raw_components, list) and raw_components:
            for raw in raw_components:
                if not isinstance(raw, dict):
                    return False
                expression = raw.get("expression") or cls._opportunity_damage_expression(raw)
                damage_type = str(raw.get("damage_type") or "").strip()
                if not cls._rule_expression_supported(expression) or not damage_type:
                    return False
            return True
        return cls._rule_expression_supported(
            cls._opportunity_damage_expression(action)
        ) and bool(
            str(action.get("damage_type") or "").strip()
        )

    @classmethod
    def _automatic_opportunity_roll(cls, action: dict[str, Any]) -> dict[str, Any] | None:
        """Roll only a completely structured one-target melee attack.

        Opportunity attacks must not guess an attack bonus, damage type, or a
        dice expression.  Imported actions that do not satisfy this contract
        remain on the existing DM adjudication path.
        """

        if not cls._automatic_opportunity_supported(action):
            return None
        attack_bonus = action["attack_bonus"]
        raw_components = action.get("damage_components")
        components: list[dict[str, Any]] = []
        if isinstance(raw_components, list) and raw_components:
            for raw in raw_components:
                if not isinstance(raw, dict):
                    return None
                expression = raw.get("expression") or cls._opportunity_damage_expression(raw)
                damage_type = str(raw.get("damage_type") or "").strip()
                amount = CombatEngineService._roll_rule_expression(expression)
                if amount is None or amount < 0 or not damage_type:
                    return None
                components.append(
                    {
                        "amount": amount,
                        "damage_type": damage_type,
                        "damage_tags": [
                            str(tag).strip()
                            for tag in raw.get("damage_tags", [])
                            if str(tag).strip()
                        ]
                        if isinstance(raw.get("damage_tags"), list)
                        else [],
                    }
                )
        else:
            amount = CombatEngineService._roll_rule_expression(
                cls._opportunity_damage_expression(action)
            )
            damage_type = str(action.get("damage_type") or "").strip()
            if amount is None or amount < 0 or not damage_type:
                return None
            components = [{"amount": amount, "damage_type": damage_type, "damage_tags": []}]
        attack_roll = secrets.randbelow(20) + 1
        attack_total = attack_roll + attack_bonus
        return {
            "attack_roll": attack_roll,
            "attack_total": attack_total,
            "damage_total": sum(int(item["amount"]) for item in components),
            "damage_components": components,
        }

    def _confirm_automatic_opportunity(
        self,
        campaign_id: str,
        request: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        action = request.get("action")
        if not isinstance(action, dict):
            raise ValueError("借机攻击缺少结构化攻击积木")
        roll = self._automatic_opportunity_roll(action)
        if roll is None:
            raise ValueError("借机攻击缺少可靠的攻击加值、伤害骰或伤害类型")
        source_id = str(request["source_combatant_id"])
        target_id = str(request["target_combatant_id"])
        with Session(self.engine) as session:
            source = session.get(Combatant, source_id)
            target = session.get(Combatant, target_id)
            if source is None or target is None or source.combat_id != target.combat_id:
                raise StateNotFoundError("借机攻击的战斗单位已不存在")
            action_name = str(action.get("name") or request.get("source_action_name") or "近战攻击")
            damage_type = (
                roll["damage_components"][0]["damage_type"]
                if len(roll["damage_components"]) == 1
                else "mixed"
            )
            command = CombatActionCommand(
                action_type="damage",
                target_combatant_id=target.id,
                target_version=target.version,
                actor_combatant_id=source.id,
                actor_version=source.version,
                action_cost="reaction",
                action_name=action_name,
                resolution_note=(
                    f"d20({roll['attack_roll']}) + {action.get('attack_bonus')} = "
                    f"{roll['attack_total']}；"
                    f"{'命中' if roll['attack_total'] >= target.armor_class else '未命中'}"
                    f" AC {target.armor_class}"
                ),
                amount=(roll["damage_total"] if roll["attack_total"] >= target.armor_class else 0),
                damage_type=damage_type,
                damage_components=(
                    roll["damage_components"]
                    if roll["attack_total"] >= target.armor_class
                    else []
                ),
                is_attack=True,
                attack_roll_mode="normal",
                attack_roll_total=roll["attack_total"],
                attack_adjudication_note="结构化借机攻击自动结算",
                reaction_trigger=str(request["reaction_trigger"]),
                reaction_event="leaves_reach",
            )
            combat_id = source.combat_id
        return self.combat.confirm(
            campaign_id,
            combat_id,
            command,
            idempotency_key=idempotency_key,
        )

    def move(
        self,
        principal: PlayerPrincipal,
        row: int,
        col: int,
        combatant_version: int,
        disengage: bool = False,
    ) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session, session.begin():
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            fighters = session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
                .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
            ).all()
            active = fighters[combat.current_turn_index] if fighters else None
            actor = self._controlled_actor(fighters, active, principal.character_id)
            if actor is None:
                raise ValueError("现在还没有轮到你的角色或你的召唤单位")
            if CombatEngineService._movement_is_blocked(actor):
                raise ValueError("当前状态不能移动")
            if disengage and not actor.action_available:
                raise ValueError("撤离需要本回合尚未使用的动作")
            if actor.version != combatant_version:
                raise VersionConflict("combatant", actor.id, combatant_version, actor.version)
            snapshot = dict(actor.snapshot_json)
            current = snapshot.get("grid_position")
            scene_id = combat.scene_id or room.current_scene_id if room else combat.scene_id
            grid = (
                session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))
                if scene_id
                else None
            )
            if grid is not None and not (1 <= row <= grid.height and 1 <= col <= grid.width):
                raise ValueError("目的地超出当前战斗地图边界")
            if isinstance(current, dict):
                start = (int(current["row"]), int(current["col"]))
            else:
                token = (
                    session.scalar(
                        select(SceneToken).where(
                            SceneToken.scene_id == scene_id,
                            SceneToken.entity_type == "character",
                            SceneToken.entity_id == principal.character_id,
                        )
                    )
                    if scene_id
                    else None
                )
                if token is None:
                    raise ValueError("角色尚未设置战斗地图起始位置")
                start = (token.row, token.col)
            # Frightened is not a blanket movement lock: the 2014/2024 rule
            # forbids willingly moving closer to the structured source.  Keep
            # this before path/terrain mutation and share it with AI movement.
            CombatEngineService._validate_frightened_movement(
                session,
                combat,
                actor,
                start,
                (row, col),
            )
            objects = (
                session.scalars(select(SceneObject).where(SceneObject.scene_id == scene_id)).all()
                if scene_id
                else []
            )
            blocked: set[tuple[int, int]] = set()
            difficult: set[tuple[int, int]] = set()
            for item in objects:
                cells = _object_cells(item)
                if item.object_type == "terrain" and item.state == "active":
                    difficult.update(cells)
                if (
                    item.object_type == "wall"
                    or (item.object_type == "door" and item.state in {"active", "closed"})
                    or (item.object_type in {"cover", "furniture"} and item.state == "active")
                ):
                    blocked.update(cells)
            path = _grid_line(start, (row, col))
            if any(cell in blocked for cell in path[1:]):
                raise ValueError("移动路径被墙壁、关闭的门或障碍物阻挡")
            cell_size = grid.cell_size_ft if grid is not None else 5
            standing_cost = 0
            stood_from_prone = False
            if self.combat._has_condition(actor, "prone"):
                standing_cost = (actor.speed_ft + 1) // 2
                if actor.speed_ft <= 0:
                    raise ValueError("倒地单位没有足够速度起身")
                stood_from_prone = True
                # Ending a structured prone effect also restores any state it
                # owns.  A hand-entered condition has no effect row and is
                # simply removed below; neither path invents a free stand.
                active_effects = session.scalars(
                    select(CombatEffect).where(
                        CombatEffect.combat_id == combat.id,
                        CombatEffect.target_combatant_id == actor.id,
                        CombatEffect.status == "active",
                    )
                ).all()
                for effect in active_effects:
                    block = dict(effect.details_json or {}).get("rule_block")
                    if not isinstance(block, dict) or str(block.get("kind") or "") != "condition":
                        continue
                    if self.combat._canonical_condition(block.get("condition")) != "prone":
                        continue
                    self.combat._reverse_compiled_effect(session, actor, effect)
                    effect.status = "ended"
                    effect.ended_at = _now()
                    effect.end_reason = "单位起身"
                    effect.version += 1
                self.combat._remove_condition(actor, "prone")
            path_cost = movement_cost_ft(path, difficult, cell_size_ft=cell_size)
            cost = standing_cost + path_cost
            if cost > actor.movement_remaining_ft:
                raise ValueError("目的地超出本回合剩余移动范围")
            occupied = {
                tuple((int(pos["row"]), int(pos["col"])))
                for other in fighters
                if other.id != actor.id
                for pos in [other.snapshot_json.get("grid_position")]
                if isinstance(pos, dict)
            }
            if (row, col) in occupied:
                raise ValueError("目的地已被其他单位占据")
            opportunity_requests: list[dict[str, Any]] = []
            automatic_opportunities: list[dict[str, Any]] = []
            if not disengage and isinstance(current, dict):
                start_point = start
                end_point = (row, col)
                for enemy in fighters:
                    if enemy.id == actor.id or not enemy.reaction_available:
                        continue
                    hostile = self._combatant_faction(enemy) != self._combatant_faction(actor)
                    if not hostile:
                        continue
                    enemy_position = enemy.snapshot_json.get("grid_position")
                    if not isinstance(enemy_position, dict):
                        continue
                    enemy_point = (int(enemy_position["row"]), int(enemy_position["col"]))
                    if (
                        grid_distance_ft(start_point, enemy_point, cell_size_ft=cell_size) <= 5
                        and grid_distance_ft(end_point, enemy_point, cell_size_ft=cell_size) > 5
                    ):
                        action = self._opportunity_attack_action(
                            self._combatant_actions(session, enemy)
                        )
                        if action is None:
                            continue
                        damage_expression = str(
                            self._opportunity_damage_expression(action) or "按 DM 指定"
                        )
                        opportunity = {
                                "source_combatant_id": enemy.id,
                                "source_name": enemy.display_name,
                                "source_action_name": str(
                                    action.get("name") or "近战攻击"
                                ),
                                "source_action_type": str(
                                    action.get("action_type") or "action"
                                ),
                                "source_attack_range_ft": action.get("range_ft"),
                                "damage_expression": damage_expression,
                                "damage_type": str(action.get("damage_type") or "slashing"),
                                "target_combatant_id": actor.id,
                                "target_name": actor.display_name,
                                "reaction_trigger": (
                                    f"{actor.display_name} 离开 {enemy.display_name} 的近战威胁范围"
                                ),
                                "action": action,
                            }
                        if not self._automatic_opportunity_supported(action):
                            opportunity_requests.append(opportunity)
                        else:
                            automatic_opportunities.append(opportunity)
            snapshot["grid_position"] = _merge_grid_position(
                current,
                row=row,
                col=col,
            )
            actor.snapshot_json = snapshot
            actor.movement_remaining_ft -= cost
            if disengage:
                actor.action_available = False
            if start != (row, col):
                session.add(
                    CombatAction(
                        campaign_id=combat.campaign_id,
                        combat_id=combat.id,
                        actor_combatant_id=actor.id,
                        action_type="move",
                        target_combatant_ids=[actor.id],
                        request_json={
                            "action_name": "撤离并移动" if disengage else "移动",
                            "from_position": {"row": start[0], "col": start[1]},
                            "to_position": {"row": row, "col": col},
                            "movement_spent_ft": cost,
                            "standing_from_prone_ft": standing_cost,
                            "disengage": disengage,
                        },
                        result_json={
                            "from_position": {"row": start[0], "col": start[1]},
                            "to_position": {"row": row, "col": col},
                            "movement_remaining_ft": actor.movement_remaining_ft,
                        },
                        explanation="战斗地图移动已公开同步",
                        round_number=combat.round_number,
                        turn_index=combat.current_turn_index,
                        summary=(
                            f"{actor.display_name} 从"
                            f"（{start[0]},{start[1]}）移动到（{row},{col}）"
                            f"；消耗 {cost} 尺移动力"
                            + (f"（起身消耗 {standing_cost} 尺）" if stood_from_prone else "")
                            + ("；本次移动不会触发借机攻击" if disengage else "")
                        ),
                        idempotency_key=f"combatant-move:{actor.id}:{combatant_version}",
                        status="confirmed",
                    )
                )
            elif stood_from_prone:
                session.add(
                    CombatAction(
                        campaign_id=combat.campaign_id,
                        combat_id=combat.id,
                        actor_combatant_id=actor.id,
                        action_type="stand",
                        target_combatant_ids=[actor.id],
                        request_json={
                            "action_name": "起身",
                            "movement_spent_ft": standing_cost,
                        },
                        result_json={
                            "from_position": {"row": start[0], "col": start[1]},
                            "to_position": {"row": row, "col": col},
                            "movement_remaining_ft": actor.movement_remaining_ft,
                        },
                        explanation="倒地单位起身并消耗一半速度",
                        round_number=combat.round_number,
                        turn_index=combat.current_turn_index,
                        summary=f"{actor.display_name} 起身；消耗 {standing_cost} 尺移动力",
                        idempotency_key=f"combatant-stand:{actor.id}:{combatant_version}",
                        status="confirmed",
                    )
                )
            actor.version += 1
            actor.updated_at = _now()
            if start != (row, col):
                self.combat._persist_eligible_enters_reach_reaction_windows(
                    session,
                    combat=combat,
                    moving_combatant=actor,
                    from_position=start,
                    to_position=(row, col),
                    movement_key=f"combatant-move:{actor.id}:{combatant_version}",
                )
                self.combat._persist_eligible_leaves_reach_reaction_windows(
                    session,
                    combat=combat,
                    moving_combatant=actor,
                    from_position=start,
                    to_position=(row, col),
                    movement_key=f"combatant-move:{actor.id}:{combatant_version}",
                )
            ended_movement_effects: list[CombatEffect] = []
            ended_movement_summons: list[Combatant] = []
            if start != (row, col) or stood_from_prone:
                ended_movement_effects, ended_movement_summons = (
                    self.combat._end_predicated_effects(
                        session,
                        combat,
                        now=_now(),
                        event_combatant_ids={actor.id},
                        event_kinds={"movement"},
                        event_only=True,
                    )
                )
                if ended_movement_effects:
                    result_effect_ids = [
                        effect.id for effect in ended_movement_effects
                    ]
                else:
                    result_effect_ids = []
            else:
                result_effect_ids = []
            for index, request in enumerate(opportunity_requests):
                session.add(
                    PlayerActionRequest(
                        campaign_id=principal.campaign_id,
                        character_id=principal.character_id,
                        player_key=principal.session_id,
                        action_type="opportunity_attack",
                        message=(
                            f"{request['source_name']} 可以对离开其近战范围的"
                            f"{request['target_name']} 发起借机攻击。"
                        ),
                        payload_json={
                            "schema_version": "1.0",
                            "phase": "awaiting_dm",
                            "combat_id": combat.id,
                            **request,
                        },
                        character_version=actor.version,
                        idempotency_key=(
                            f"opportunity:{combat.id}:{actor.id}:"
                            f"{request['source_combatant_id']}:{actor.version}:{index}"
                        ),
                        status="pending",
                    )
                )
            if scene_id:
                token = (
                    session.scalar(
                        select(SceneToken).where(
                            SceneToken.scene_id == scene_id,
                            SceneToken.entity_type == "character",
                            SceneToken.entity_id == principal.character_id,
                        )
                    )
                    if actor.entity_type == "character"
                    else None
                )
                if token is not None:
                    token.row = row
                    token.col = col
                    token.version += 1
                    token.updated_at = _now()
                scene = session.get(Scene, scene_id)
                if scene is not None and grid is not None:
                    visibility = self._visibility_for(
                        session,
                        scene,
                        principal,
                        grid,
                        origin_override=(row, col),
                    )
                    viewer_key = f"character:{principal.character_id}"
                    state = session.scalar(
                        select(VisibilityState).where(
                            VisibilityState.scene_id == scene.id,
                            VisibilityState.viewer_key == viewer_key,
                        )
                    )
                    if state is None:
                        state = VisibilityState(
                            scene_id=scene.id,
                            viewer_key=viewer_key,
                            version=1,
                        )
                        session.add(state)
                    else:
                        state.version += 1
                    state.explored_cells = [
                        {"row": point[0], "col": point[1]}
                        for point in sorted(visibility["explored"])
                    ]
                    state.visible_cells = [
                        {"row": point[0], "col": point[1]}
                        for point in sorted(visibility["visible"])
                    ]
                    state.updated_at = _now()
            session.flush()
            result = serialize(actor)
        automatic_results: list[dict[str, Any]] = []
        for index, opportunity in enumerate(automatic_opportunities):
            resolved = self._confirm_automatic_opportunity(
                principal.campaign_id,
                opportunity,
                idempotency_key=(
                    f"opportunity-auto:{opportunity['source_combatant_id']}"
                    f":{opportunity['target_combatant_id']}:{combatant_version}:{index}"
                ),
            )
            automatic_results.append(
                {
                    **opportunity,
                    "automatic": True,
                    "attack_result": resolved,
                }
            )
        result["opportunity_attacks"] = [*opportunity_requests, *automatic_results]
        result["automatic_opportunity_attacks"] = automatic_results
        result["ended_predicated_effect_ids"] = result_effect_ids
        result["ended_predicated_summon_ids"] = [
            summon.id for summon in ended_movement_summons
        ]
        return result

    def move_monster(
        self,
        campaign_id: str,
        combat_id: str,
        combatant_id: str,
        row: int,
        col: int,
        combatant_version: int,
        movement_remaining_ft: int,
        request_id: str,
    ) -> dict[str, Any]:
        """Persist an AI monster step and open player reaction choices.

        The DM grid used to patch a monster directly, which meant movement
        never passed through the reaction rules.  This endpoint is deliberately
        narrow: only the AI movement writer calls it, and only a structured
        melee attack can create a player-facing opportunity choice.
        """

        if movement_remaining_ft < 0:
            raise ValueError("剩余移动力不能为负数")
        with Session(self.engine) as session, session.begin():
            room = self._room(session, campaign_id)
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            monster = session.get(Combatant, combatant_id)
            if (
                monster is None
                or monster.combat_id != combat_id
                or monster.entity_type != "monster"
                or not monster.is_active
            ):
                raise ValueError("只能由战斗 AI 移动活跃怪物")
            if monster.version != combatant_version:
                raise VersionConflict("combatant", monster.id, combatant_version, monster.version)
            current = monster.snapshot_json.get("grid_position")
            if not isinstance(current, dict):
                raise ValueError("怪物没有战斗地图位置")
            start = (int(current["row"]), int(current["col"]))
            grid = (
                session.scalar(select(SceneGrid).where(SceneGrid.scene_id == combat.scene_id))
                if combat.scene_id
                else None
            )
            if grid is not None and not (1 <= row <= grid.height and 1 <= col <= grid.width):
                raise ValueError("怪物目的地超出当前战斗地图边界")
            if start == (row, col):
                return {**serialize(monster), "reaction_requests": []}
            CombatEngineService._validate_frightened_movement(
                session,
                combat,
                monster,
                start,
                (row, col),
            )
            previous_movement_remaining = int(monster.movement_remaining_ft)
            fighters = list(
                session.scalars(
                    select(Combatant).where(
                        Combatant.combat_id == combat_id,
                        Combatant.is_active.is_(True),
                    )
                ).all()
            )
            cell_size = grid.cell_size_ft if grid is not None else 5
            snapshot = dict(monster.snapshot_json or {})
            snapshot["grid_position"] = _merge_grid_position(current, row=row, col=col)
            monster.snapshot_json = snapshot
            monster.movement_remaining_ft = movement_remaining_ft
            monster.version += 1
            monster.updated_at = _now()
            session.add(
                CombatAction(
                    campaign_id=campaign_id,
                    combat_id=combat_id,
                    actor_combatant_id=monster.id,
                    action_type="move",
                    target_combatant_ids=[monster.id],
                    request_json={
                        "action_name": "移动",
                        "from_position": {"row": start[0], "col": start[1]},
                        "to_position": {"row": row, "col": col},
                        "movement_spent_ft": max(
                            0, previous_movement_remaining - movement_remaining_ft
                        ),
                    },
                    result_json={
                        "from_position": {"row": start[0], "col": start[1]},
                        "to_position": {"row": row, "col": col},
                        "movement_remaining_ft": movement_remaining_ft,
                    },
                    explanation="怪物 AI 移动已公开同步",
                    round_number=combat.round_number,
                    turn_index=combat.current_turn_index,
                    summary=(
                        f"{monster.display_name} 从（{start[0]},{start[1]}）移动到"
                        f"（{row},{col}）；剩余 {movement_remaining_ft} 尺移动力"
                    ),
                    idempotency_key=f"monster-move:{monster.id}:{combatant_version}",
                    status="confirmed",
                )
            )
            self.combat._persist_eligible_enters_reach_reaction_windows(
                session,
                combat=combat,
                moving_combatant=monster,
                from_position=start,
                to_position=(row, col),
                movement_key=f"monster-move:{monster.id}:{combatant_version}",
            )
            self.combat._persist_eligible_leaves_reach_reaction_windows(
                session,
                combat=combat,
                moving_combatant=monster,
                from_position=start,
                to_position=(row, col),
                movement_key=f"monster-move:{monster.id}:{combatant_version}",
            )
            reaction_requests: list[dict[str, Any]] = []
            for target in fighters:
                    if target.id == monster.id or target.hp <= 0:
                        continue
                    if self._combatant_faction(target) == self._combatant_faction(monster):
                        continue
                    target_position = target.snapshot_json.get("grid_position")
                    if not isinstance(target_position, dict):
                        continue
                    target_point = (int(target_position["row"]), int(target_position["col"]))
                    if not (
                        grid_distance_ft(start, target_point, cell_size_ft=cell_size) <= 5
                        and grid_distance_ft((row, col), target_point, cell_size_ft=cell_size) > 5
                    ):
                        continue
                    character_id = self._combatant_owner(target)
                    if character_id is None:
                        continue
                    character = session.get(Character, character_id)
                    player_session = session.scalar(
                        select(PlayerSession).where(
                            PlayerSession.room_id == room.id,
                            PlayerSession.character_id == character_id,
                            PlayerSession.status == "active",
                        )
                    )
                    if character is None or player_session is None:
                        continue
                    action = self._opportunity_attack_action(
                        self._combatant_actions(session, target)
                    )
                    if action is None or not self._automatic_opportunity_supported(action):
                        continue
                    payload = {
                        "schema_version": "1.0",
                        "phase": "awaiting_player_choice",
                        "combat_id": combat_id,
                        "source_combatant_id": target.id,
                        "source_name": target.display_name,
                        "source_action_name": str(action.get("name") or "近战攻击"),
                        "damage_expression": str(
                            self._opportunity_damage_expression(action) or "分段伤害"
                        ),
                        "damage_type": str(action.get("damage_type") or ""),
                        "target_combatant_id": monster.id,
                        "target_name": monster.display_name,
                        "reaction_trigger": (
                            f"{monster.display_name} 离开 {target.display_name} 的近战威胁范围"
                        ),
                        "action": action,
                    }
                    idempotency_key = (
                        f"opportunity-choice:{combat_id}:{monster.id}:{target.id}:"
                        f"{combatant_version}"
                    )
                    existing = session.scalar(
                        select(PlayerActionRequest).where(
                            PlayerActionRequest.campaign_id == campaign_id,
                            PlayerActionRequest.idempotency_key == idempotency_key,
                        )
                    )
                    if existing is not None:
                        reaction_requests.append(serialize(existing))
                        continue
                    item = PlayerActionRequest(
                        campaign_id=campaign_id,
                        character_id=character_id,
                        player_key=player_session.id,
                        action_type="opportunity_reaction",
                        message=(
                            f"{monster.display_name} 离开你的近战范围；是否发动一次借机攻击？"
                        ),
                        payload_json=payload,
                        character_version=character.version,
                        idempotency_key=idempotency_key,
                        status="pending",
                    )
                    session.add(item)
                    session.flush()
                    reaction_requests.append(serialize(item))
            session.flush()
            result = serialize(monster)
        result["reaction_requests"] = reaction_requests
        return result

    def resolve_player_reaction(
        self,
        principal: PlayerPrincipal,
        request_id_value: str,
        expected_version: int,
        decision: str,
        request_id: str,
    ) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session:
            item = session.get(PlayerActionRequest, request_id_value)
            if (
                item is None
                or item.campaign_id != principal.campaign_id
                or item.character_id != principal.character_id
                or item.player_key != principal.session_id
                or item.action_type != "opportunity_reaction"
            ):
                raise StateNotFoundError("玩家借机攻击请求不存在")
            if item.version != expected_version:
                raise VersionConflict(
                    "player_action_request", item.id, expected_version, item.version
                )
            if item.status != "pending":
                return serialize(item)
            if decision == "reject":
                session.rollback()
                session.begin()
                try:
                    item.status = "rejected"
                    item.dm_note = "玩家选择不发动借机攻击"
                    item.resolved_at = _now()
                    item.version += 1
                    item.updated_at = _now()
                    self.player._audit(
                        session,
                        principal.campaign_id,
                        "player_reaction_rejected",
                        item,
                        request_id,
                    )
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                return serialize(item)
            payload = dict(item.payload_json or {})
        if decision != "accept":
            raise ValueError("借机攻击选择必须是 accept 或 reject")
        attack_result = self._confirm_automatic_opportunity(
            principal.campaign_id,
            payload,
            idempotency_key=f"player-reaction:{request_id_value}",
        )
        with Session(self.engine) as session, session.begin():
            item = session.get(PlayerActionRequest, request_id_value)
            if item is None:
                raise StateNotFoundError("玩家借机攻击请求不存在")
            if item.status != "pending":
                return serialize(item)
            item.status = "accepted"
            item.dm_note = "玩家选择发动；系统自动执行结构化攻击积木"
            item.payload_json = {
                **dict(item.payload_json or {}),
                "phase": "confirmed",
                "choice": "accept",
                "attack_result": attack_result,
            }
            item.resolved_at = _now()
            item.version += 1
            item.updated_at = _now()
            self.player._audit(
                session,
                principal.campaign_id,
                "player_reaction_accepted",
                item,
                request_id,
            )
            session.flush()
            return serialize(item)

    def maneuver(self, principal: PlayerPrincipal, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a typed standard action for the player's current unit.

        The player session selects only public maneuver fields. The server
        resolves the active character or player-controlled summon and injects
        its authoritative combatant id/version before using the same engine
        as the DM maneuver endpoint.
        """

        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        requested_version = int(payload.get("actor_version") or 0)
        if requested_version < 1:
            raise ValueError("actor_version is required")
        command_payload = dict(payload)
        command_payload.pop("actor_version", None)
        idempotency_key = str(command_payload.pop("idempotency_key", "") or "")
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            fighters = self._ordered_fighters(session, combat.id)
            active = (
                fighters[combat.current_turn_index]
                if fighters and combat.current_turn_index < len(fighters)
                else None
            )
            actor = self._controlled_actor(fighters, active, principal.character_id)
            if actor is None:
                raise ValueError("现在还没有轮到你的角色或你的召唤单位")
            if actor.version != requested_version:
                raise VersionConflict("combatant", actor.id, requested_version, actor.version)
            combat_id = combat.id
            campaign_id = combat.campaign_id
            actor_id = actor.id
        command = CombatManeuverCommand(
            actor_combatant_id=actor_id,
            actor_version=requested_version,
            **command_payload,
        )
        return self.combat.confirm_maneuver(
            campaign_id,
            combat_id,
            command,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _action_data(session: Session, character: Character, action_name: str) -> dict[str, Any]:
        feature_grants = [
            item for item in character.features
            if isinstance(item, dict)
        ]
        scaling_values = {
            str(item.get("scaling_key")): item.get("value")
            for item in feature_grants
            if item.get("kind") == "class_scaling"
            and isinstance(item.get("scaling_key"), str)
        }
        feature_registry = compile_feature_runtime_registry(
            feature_grants,
            resources=character.resources if isinstance(character.resources, dict) else {},
            scalings={key: {"value": value} for key, value in scaling_values.items()},
            class_levels=character.class_levels if isinstance(character.class_levels, dict) else {},
            total_level=character.level,
        )
        runtime_actions = feature_runtime_action_projections(feature_registry)
        for raw in [*character.actions, *character.spells, *runtime_actions]:
            if isinstance(raw, dict) and str(raw.get("name")) == action_name:
                action = dict(raw)
                PlayerRoomService._attach_attack_riders(action, feature_registry)
                known_spell = session.scalar(
                    select(KnownSpell).where(
                        KnownSpell.character_id == character.id,
                        KnownSpell.name == action_name,
                    )
                )
                if known_spell is not None:
                    metadata = dict(known_spell.metadata_json or {})
                    source = metadata.get("character_spell")
                    source_fields = dict(source) if isinstance(source, dict) else metadata
                    for key in (
                        "damage",
                        "damage_expression",
                        "damage_dice",
                        "damage_type",
                        "save_ability",
                        "save_dc",
                        "half_damage_on_save",
                        "range",
                        "description",
                        "cost",
                        "resource_key",
                        "resource_cost",
                        "resolution_kind",
                        "rule_plan",
                    ):
                        if action.get(key) in (None, "") and source_fields.get(key) not in (
                            None,
                            "",
                        ):
                            action[key] = source_fields[key]
                return action
        raise ValueError("该动作不在你的角色卡中")

    @staticmethod
    def _attach_attack_riders(
        action: dict[str, Any],
        registry: dict[str, Any] | None,
    ) -> None:
        """Expose compiled rider contracts alongside the action they may modify."""

        if not isinstance(registry, dict):
            return
        raw_riders = registry.get("attack_riders")
        if not isinstance(raw_riders, list) or not raw_riders:
            return
        action_text = " ".join(
            str(action.get(key) or "") for key in ("name", "description", "damage")
        )
        if not (
            action.get("is_weapon_attack") is True
            or "武器攻击" in action_text
            or "近战攻击" in action_text
            or "远程攻击" in action_text
        ):
            return
        action["attack_riders"] = [
            dict(rider) for rider in raw_riders if isinstance(rider, dict)
        ]

    @staticmethod
    def _companion_action_data(companion: Combatant, action_name: str) -> dict[str, Any]:
        raw_actions = companion.snapshot_json.get("actions")
        actions = raw_actions if isinstance(raw_actions, list) else []
        for raw in actions:
            if isinstance(raw, dict) and str(raw.get("name") or "") == action_name:
                return dict(raw)
        raise ValueError("该动作不在当前召唤物的战斗模板中")

    @staticmethod
    def _block_applies_for_outcome(
        block: dict[str, Any],
        *,
        target_id: str,
        effect_targets: dict[str, bool],
        target_outcomes: dict[str, str],
    ) -> bool:
        """Apply an explicit branch guard without changing legacy block semantics."""

        applies_on = block.get("applies_on")
        if applies_on is None:
            return effect_targets.get(target_id, True)
        if applies_on == "always":
            return True
        return target_outcomes.get(target_id) == applies_on

    @staticmethod
    def _selected_choice_block_ids(
        blocks: list[dict[str, Any]], execution_inputs: dict[str, Any]
    ) -> set[str]:
        """Resolve only player-submitted ChoiceBlock keys; never choose a branch by name."""

        choice_blocks = [block for block in blocks if block.get("kind") == "choice"]
        if not choice_blocks:
            return set()
        raw_selections = execution_inputs.get("choice_selections")
        if not isinstance(raw_selections, dict):
            raise ValueError("该动作包含分支效果，必须明确提交 choice_selections")
        selected_ids: set[str] = set()
        for choice in choice_blocks:
            choice_id = str(choice.get("id") or "")
            raw_value = raw_selections.get(choice_id)
            values = [raw_value] if isinstance(raw_value, str) else raw_value
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise ValueError("每个规则分支都必须选择有效选项")
            keys = list(dict.fromkeys(values))
            minimum = int(choice.get("minimum_choices") or 1)
            maximum = int(choice.get("maximum_choices") or 1)
            if not minimum <= len(keys) <= maximum:
                raise ValueError("选择的分支数量不符合该规则的限制")
            options = choice.get("options")
            if not isinstance(options, list):
                raise ValueError("规则分支选项无效")
            by_key = {
                str(option.get("key")): option
                for option in options
                if isinstance(option, dict) and isinstance(option.get("key"), str)
            }
            if any(key not in by_key for key in keys):
                raise ValueError("提交的规则分支选项不存在")
            for key in keys:
                option = by_key[key]
                child_ids = option.get("block_ids")
                if not isinstance(child_ids, list) or not all(
                    isinstance(block_id, str) and block_id for block_id in child_ids
                ):
                    raise ValueError("规则分支缺少可执行效果")
                selected_ids.update(child_ids)
        return selected_ids

    @staticmethod
    def _reaction_trigger_for_support_cast(
        action: dict[str, Any],
        blocks: list[dict[str, Any]],
        submitted_trigger: str,
    ) -> str:
        """Keep the engine's reaction accounting without inventing an event.

        The combat engine requires a non-empty trigger whenever it consumes a
        reaction.  Legacy self/ally support entries sometimes carry only the
        UI cost ``反应`` and no trigger contract at all.  They are not allowed
        to manufacture a fictional event: an explicit contract still requires
        player input, while the narrow legacy-support case records a stable
        compatibility marker that says the rule data omitted that contract.
        """

        trigger = submitted_trigger.strip()
        if trigger:
            return trigger
        if action.get("requires_reaction_trigger") is True:
            raise ValueError("该反应法术必须明确填写 reaction_trigger")
        support_kinds = {
            "target",
            "duration",
            "resource",
            "heal",
            "condition",
            "modifier",
            "defense",
            "repeat",
            "choice",
            "narrative",
        }
        if all(str(block.get("kind") or "") in support_kinds for block in blocks):
            return "legacy_support_without_declared_trigger"
        raise ValueError("该反应法术必须明确填写 reaction_trigger")

    def _apply_compiled_combat_blocks(
        self,
        principal: PlayerPrincipal,
        combat_id: str,
        actor_id: str,
        action: dict[str, Any],
        target_ids: list[str],
        effect_targets: dict[str, bool],
        idempotency_key: str,
        execution_inputs: dict[str, Any] | None = None,
        target_outcomes: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Turn accepted combat blocks into authoritative CombatEffect rows."""

        raw_plan = action.get("rule_plan")
        execution_inputs = dict(execution_inputs or {})
        if not isinstance(raw_plan, dict):
            return []
        raw_blocks = raw_plan.get("blocks")
        if not isinstance(raw_blocks, list):
            return []
        blocks = [block for block in raw_blocks if isinstance(block, dict)]
        duration = next((block for block in blocks if block.get("kind") == "duration"), None)
        by_id = {str(block.get("id")): block for block in blocks if block.get("id")}
        target_outcomes = dict(target_outcomes or {})
        selected_choice_ids = self._selected_choice_block_ids(blocks, execution_inputs)
        choice_child_ids = {
            str(child_id)
            for choice in blocks
            if choice.get("kind") == "choice"
            for option in (choice.get("options") if isinstance(choice.get("options"), list) else [])
            if isinstance(option, dict)
            for child_id in (
                option.get("block_ids") if isinstance(option.get("block_ids"), list) else []
            )
            if isinstance(child_id, str) and child_id
        }
        repeat_child_ids = {
            str(child_id)
            for repeat in blocks
            if repeat.get("kind") == "repeat"
            for child_id in (
                repeat.get("block_ids") if isinstance(repeat.get("block_ids"), list) else []
            )
            if isinstance(child_id, str) and child_id
        }
        trigger_child_ids = {
            str(child_id)
            for trigger in blocks
            if trigger.get("kind") == "trigger"
            for child_id in (
                trigger.get("block_ids") if isinstance(trigger.get("block_ids"), list) else []
            )
            if isinstance(child_id, str) and child_id
        }
        area_child_ids = {
            str(child_id)
            for area in blocks
            if area.get("kind") == "area_effect"
            for child_id in (
                area.get("effect_block_ids")
                if isinstance(area.get("effect_block_ids"), list)
                else []
            )
            if isinstance(child_id, str) and child_id
        }

        def duration_args() -> tuple[str, int | None, bool]:
            if duration is None:
                return "until_removed", None, False
            unit = str(duration.get("unit") or "until_removed")
            if unit == "round":
                return (
                    "rounds",
                    int(duration.get("value") or 0),
                    bool(duration.get("concentration")),
                )
            if unit == "minute":
                return (
                    "minutes",
                    int(duration.get("value") or 0),
                    bool(duration.get("concentration")),
                )
            if unit == "hour":
                return (
                    "minutes",
                    int(duration.get("value") or 0) * 60,
                    bool(duration.get("concentration")),
                )
            if unit == "day":
                return (
                    "minutes",
                    int(duration.get("value") or 0) * 24 * 60,
                    bool(duration.get("concentration")),
                )
            if unit == "until_save":
                return "until_save", None, bool(duration.get("concentration"))
            return "until_removed", None, bool(duration.get("concentration"))

        duration_unit, duration_value, concentration = duration_args()
        executable: list[dict[str, Any]] = []
        for block in blocks:
            kind = str(block.get("kind") or "")
            block_id = str(block.get("id") or "")
            if kind in {"condition", "modifier", "defense"} or (
                kind == "heal" and block.get("temporary_hp") is True
            ):
                if block_id in choice_child_ids and block_id not in selected_choice_ids:
                    continue
                if block_id in repeat_child_ids | trigger_child_ids | area_child_ids:
                    continue
                executable.append(block)
            elif kind == "repeat":
                for child_id in block.get("block_ids", []):
                    child = by_id.get(str(child_id))
                    if child is not None and child.get("kind") in {
                        "damage",
                        "heal",
                        "condition",
                        "modifier",
                        "defense",
                    }:
                        executable.append({**child, "repeat": block})

        applied: list[dict[str, Any]] = []
        movement_results: list[dict[str, Any]] = []
        for target_id in target_ids:
            for block in executable:
                kind = str(block.get("kind") or "")
                if not self._block_applies_for_outcome(
                    block,
                    target_id=target_id,
                    effect_targets=effect_targets,
                    target_outcomes=target_outcomes,
                ):
                    continue
                if kind == "condition" and str(block.get("operation") or "apply") == "remove":
                    effect_type = "condition"
                elif kind == "condition":
                    effect_type = "condition"
                elif kind == "defense":
                    effect_type = "buff"
                elif kind == "modifier":
                    operation = str(block.get("operation") or "")
                    effect_type = "debuff" if operation == "disadvantage" else "buff"
                elif kind == "heal" and block.get("temporary_hp") is True:
                    effect_type = "buff"
                elif kind in {"damage", "heal"} and isinstance(block.get("repeat"), dict):
                    effect_type = "damage_over_time" if kind == "damage" else "buff"
                else:
                    continue
                details: dict[str, Any] = {
                    "rule_block": block,
                    "rule_plan_source": action.get("name"),
                }
                if isinstance(block.get("repeat"), dict):
                    details["repeat"] = block["repeat"]
                if kind == "damage":
                    details["damage_expression"] = block.get("expression")
                    details["damage_type"] = block.get("damage_type")
                if kind == "heal":
                    details["healing_expression"] = block.get("expression")
                    if block.get("temporary_hp") is True:
                        details["temporary_hp"] = True
                save_block = next((item for item in blocks if item.get("kind") == "save"), None)
                save_dc = int(action.get("save_dc") or 0) or None
                save_ability = str(action.get("save_ability") or "") or None
                if isinstance(save_block, dict):
                    save_ability = save_ability or str(save_block.get("ability") or "") or None
                    raw_dc = save_block.get("dc")
                    save_dc = save_dc or (int(raw_dc) if isinstance(raw_dc, int) else None)
                trigger_timing = None
                if isinstance(block.get("repeat"), dict):
                    raw_timing = str(block["repeat"].get("timing") or "")
                    trigger_timing = (
                        raw_timing
                        if raw_timing in {"turn_start", "turn_end", "round_start", "round_end"}
                        else None
                    )
                with Session(self.engine) as session:
                    target = session.get(Combatant, target_id)
                    actor = session.get(Combatant, actor_id)
                    if target is None or actor is None:
                        continue
                    condition = str(block.get("condition") or "").strip()
                    if kind == "defense" and condition:
                        raw_defense_conditions = execution_inputs.get("defense_conditions")
                        explicit_active = (
                            raw_defense_conditions.get(str(block.get("id")))
                            if isinstance(raw_defense_conditions, dict)
                            else None
                        )
                        if explicit_active is not None and not isinstance(explicit_active, bool):
                            raise ValueError("defense_conditions values must be booleans")
                        active_conditions = {str(value) for value in target.conditions or []}
                        if explicit_active is False or (
                            explicit_active is None and condition not in active_conditions
                        ):
                            continue
                    command = CombatEffectCommand(
                        target_combatant_id=target.id,
                        target_version=target.version,
                        source_combatant_id=actor.id,
                        source_version=actor.version,
                        name=str(action.get("name") or "规则效果"),
                        effect_type=effect_type,  # type: ignore[arg-type]
                        details_json=details,
                        duration_unit=duration_unit,  # type: ignore[arg-type]
                        duration_value=duration_value,
                        requires_concentration=concentration,
                        save_dc=save_dc,
                        save_ability=save_ability,
                        trigger_timing=trigger_timing,  # type: ignore[arg-type]
                    )
                result = self.combat.confirm_effect(
                    principal.campaign_id,
                    combat_id,
                    command,
                    idempotency_key=f"{idempotency_key}:effect:{target_id}:{block.get('id')}",
                )
                applied.append(
                    {
                        "target_combatant_id": target_id,
                        "block_id": block.get("id"),
                        "effect": result.get("effect"),
                    }
                )
        for block in blocks:
            if block.get("kind") != "move":
                continue
            block_id = str(block.get("id") or "")
            if block_id in choice_child_ids and block_id not in selected_choice_ids:
                continue
            if block_id in (repeat_child_ids | trigger_child_ids | area_child_ids):
                continue
            if block.get("movement_type") != "forced":
                continue
            direction = str(block.get("direction") or "chosen")
            if direction not in {"away", "push", "toward", "pull"}:
                continue
            distance_ft = int(block.get("distance_ft") or 0)
            for target_id in target_ids:
                if not self._block_applies_for_outcome(
                    block,
                    target_id=target_id,
                    effect_targets=effect_targets,
                    target_outcomes=target_outcomes,
                ):
                    continue
                with Session(self.engine) as session:
                    target = session.get(Combatant, target_id)
                    actor = session.get(Combatant, actor_id)
                    if target is None or actor is None:
                        continue
                    target_version = target.version
                movement = self.combat.apply_forced_movement(
                    principal.campaign_id,
                    combat_id,
                    target_combatant_id=target_id,
                    source_combatant_id=actor_id,
                    distance_ft=distance_ft,
                    direction=direction,
                    target_version=target_version,
                    idempotency_key=(f"{idempotency_key}:move:{target_id}:{block.get('id')}"),
                )
                movement_results.append(
                    {
                        "target_combatant_id": target_id,
                        "block_id": block.get("id"),
                        "result": movement,
                    }
                )

        # Destination/form/template-sensitive effects are deterministic only
        # after the player submits the missing choice.  Do not turn a spell name,
        # loose prose, or a generic five-foot default into a target or template.
        special_results: list[dict[str, Any]] = []

        def block_is_selected(block: dict[str, Any]) -> bool:
            block_id = str(block.get("id") or "")
            return not (block_id in choice_child_ids and block_id not in selected_choice_ids)

        def applicable_target_ids(block: dict[str, Any]) -> list[str]:
            return [
                target_id
                for target_id in target_ids
                if self._block_applies_for_outcome(
                    block,
                    target_id=target_id,
                    effect_targets=effect_targets,
                    target_outcomes=target_outcomes,
                )
            ]

        def blocked_cell(grid: SceneGrid, row: int, col: int) -> bool:
            raw_cells = grid.layers_json.get("cells", [])
            return bool(
                isinstance(raw_cells, list)
                and any(
                    isinstance(cell, dict)
                    and cell.get("row") == row
                    and cell.get("col") == col
                    and cell.get("kind") in {"wall", "void"}
                    for cell in raw_cells
                )
            )

        for block in blocks:
            kind = str(block.get("kind") or "")
            block_id = str(block.get("id") or "")
            if not block_is_selected(block):
                continue
            if kind == "teleport":
                teleport_input = execution_inputs.get("teleport")
                if not isinstance(teleport_input, dict):
                    raise ValueError("该传送效果需要玩家明确选择目的地")
                active_targets = applicable_target_ids(block)
                if not active_targets:
                    continue
                destination_kind = str(block.get("destination_kind") or "")
                raw_destinations = teleport_input.get("destinations")
                destinations = raw_destinations if isinstance(raw_destinations, dict) else None
                if len(active_targets) > 1 and destinations is None:
                    raise ValueError("传送多个目标时必须为每个目标明确提交 destinations")
                scene_id = self._combat_scene_id(principal, combat_id)
                with Session(self.engine) as session, session.begin():
                    grid = (
                        session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))
                        if scene_id
                        else None
                    )
                    if grid is None:
                        raise ValueError("传送需要当前战斗的明确地图网格")

                    common_destination: dict[str, int] | None = None
                    if destination_kind == "object":
                        object_id = teleport_input.get("object_id")
                        scene_object = (
                            session.get(SceneObject, object_id)
                            if isinstance(object_id, str)
                            else None
                        )
                        if scene_object is None or scene_object.scene_id != scene_id:
                            raise ValueError("传送到物件必须明确选择当前场景中的 object_id")
                        common_destination = {"row": scene_object.row, "col": scene_object.col}
                    elif destination_kind == "creature":
                        combatant_id = teleport_input.get("combatant_id")
                        destination_actor = (
                            session.get(Combatant, combatant_id)
                            if isinstance(combatant_id, str)
                            else None
                        )
                        raw_position = (
                            destination_actor.snapshot_json.get("grid_position")
                            if destination_actor is not None
                            else None
                        )
                        if (
                            destination_actor is None
                            or destination_actor.combat_id != combat_id
                            or not isinstance(raw_position, dict)
                            or not isinstance(raw_position.get("row"), int)
                            or not isinstance(raw_position.get("col"), int)
                        ):
                            raise ValueError(
                                "传送到生物必须明确选择当前战斗中有位置的 combatant_id"
                            )
                        common_destination = {
                            "row": int(raw_position["row"]),
                            "col": int(raw_position["col"]),
                        }

                    for target_id in active_targets:
                        raw_destination = (
                            destinations.get(target_id)
                            if destinations is not None
                            else common_destination
                        )
                        if raw_destination is None and destination_kind in {
                            "chosen_space",
                            "known_location",
                        }:
                            raw_destination = teleport_input
                        if not isinstance(raw_destination, dict):
                            raise ValueError("每个传送目标都需要明确的网格目的地")
                        row = raw_destination.get("row")
                        col = raw_destination.get("col")
                        if (
                            not isinstance(row, int)
                            or isinstance(row, bool)
                            or not isinstance(col, int)
                            or isinstance(col, bool)
                        ):
                            raise ValueError("传送目的地必须提供有效的网格行列")
                        if not (1 <= row <= grid.height and 1 <= col <= grid.width):
                            raise ValueError("传送目的地不在当前战斗地图内")
                        if blocked_cell(grid, row, col):
                            raise ValueError("传送目的地被墙体或不可通行格阻挡")
                        target = session.get(Combatant, target_id)
                        if target is None or target.combat_id != combat_id:
                            raise ValueError("传送目标不存在于当前战斗")
                        current_position = target.snapshot_json.get("grid_position")
                        maximum_distance = block.get("max_distance_ft")
                        if maximum_distance is not None:
                            if (
                                not isinstance(current_position, dict)
                                or not isinstance(current_position.get("row"), int)
                                or not isinstance(current_position.get("col"), int)
                            ):
                                raise ValueError("传送距离已明确，但目标尚未设置地图位置")
                            distance = grid_distance_ft(
                                (int(current_position["row"]), int(current_position["col"])),
                                (row, col),
                                cell_size_ft=grid.cell_size_ft,
                            )
                            if distance > int(maximum_distance):
                                raise ValueError("传送目的地超出该效果的明确距离")
                        marker = f"{idempotency_key}:teleport:{block_id}"
                        snapshot = dict(target.snapshot_json or {})
                        markers = snapshot.get("compiled_special_effect_keys")
                        marker_list = list(markers) if isinstance(markers, list) else []
                        if marker in marker_list:
                            special_results.append(
                                {
                                    "kind": "teleport",
                                    "target_combatant_id": target.id,
                                    "row": row,
                                    "col": col,
                                    "already_applied": True,
                                }
                            )
                            continue
                        marker_list.append(marker)
                        snapshot["compiled_special_effect_keys"] = marker_list[-100:]
                        snapshot["grid_position"] = _merge_grid_position(
                            current_position,
                            row=row,
                            col=col,
                            requested=raw_destination,
                        )
                        target.snapshot_json = snapshot
                        target.version += 1
                        target.updated_at = _now()
                        special_results.append(
                            {
                                "kind": "teleport",
                                "target_combatant_id": target.id,
                                "row": row,
                                "col": col,
                            }
                        )
            elif kind == "transformation":
                transformation_input = execution_inputs.get("transformation")
                form = (
                    transformation_input.get("form")
                    if isinstance(transformation_input, dict)
                    else None
                )
                if not isinstance(form, dict):
                    raise ValueError("该变形效果需要明确的形态数据")
                form_ref = str(form.get("form_ref") or "").strip()
                if not form_ref or form_ref == "dm_chosen_form":
                    raise ValueError("变形效果必须提交明确的 form_ref")
                mode = str(block.get("mode") or "polymorph")
                if mode in {"polymorph", "shapechange", "alter"}:
                    required_stats = ("armor_class", "hp", "max_hp", "speed_ft")
                    if any(
                        not isinstance(form.get(key), int) or isinstance(form.get(key), bool)
                        for key in required_stats
                    ):
                        raise ValueError("战斗变形必须明确提交 AC、当前 HP、最大 HP 和速度")
                for target_id in applicable_target_ids(block):
                    with Session(self.engine) as session:
                        target = session.get(Combatant, target_id)
                        actor = session.get(Combatant, actor_id)
                        if target is None or actor is None:
                            continue
                        command = CombatEffectCommand(
                            target_combatant_id=target.id,
                            target_version=target.version,
                            source_combatant_id=actor.id,
                            source_version=actor.version,
                            name=str(action.get("name") or "变形效果"),
                            effect_type="buff",
                            details_json={
                                "rule_block": block,
                                "transformation_form": {**form, "form_ref": form_ref},
                            },
                            duration_unit=(
                                duration_unit
                                if duration_unit
                                in {"rounds", "minutes", "until_save", "until_removed"}
                                else "until_removed"
                            ),
                            duration_value=duration_value,
                            requires_concentration=concentration,
                        )
                    result = self.combat.confirm_effect(
                        principal.campaign_id,
                        combat_id,
                        command,
                        idempotency_key=f"{idempotency_key}:transformation:{target_id}:{block_id}",
                    )
                    special_results.append(
                        {
                            "kind": "transformation",
                            "target_combatant_id": target_id,
                            "result": result,
                        }
                    )
            elif kind == "creation":
                creation_input = execution_inputs.get("creation")
                if not isinstance(creation_input, dict):
                    raise ValueError("该创造效果需要明确选择模板和数量")
                input_template = str(creation_input.get("template_ref") or "").strip()
                template_ref = (
                    input_template
                    if block.get("requires_template_choice", True)
                    else input_template or str(block.get("template_ref") or "").strip()
                )
                if not template_ref or template_ref == "dm_chosen_template":
                    raise ValueError("创造效果必须提供明确的模板")
                count = creation_input.get("count")
                if count is None and isinstance(block.get("count"), int):
                    count = block.get("count")
                if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                    raise ValueError("创造效果必须提供明确的数量")
                creation_kind = str(block.get("creation_kind") or "object")
                if creation_kind == "creature":
                    raise ValueError("创造生物必须使用明确的召唤模板和召唤入口，不能伪造为场景物件")
                scene_id = self._combat_scene_id(principal, combat_id)
                with Session(self.engine) as session, session.begin():
                    scene = session.get(Scene, scene_id) if scene_id else None
                    if scene is None:
                        raise ValueError("当前战斗没有可写入创造物的场景")
                    marker = f"{idempotency_key}:creation:{block_id}"
                    if creation_kind == "item":
                        existing = next(
                            (
                                item
                                for item in session.scalars(
                                    select(WorldItem).where(
                                        WorldItem.campaign_id == principal.campaign_id
                                    )
                                ).all()
                                if item.metadata_json.get("compiled_effect_key") == marker
                            ),
                            None,
                        )
                        if existing is None:
                            existing = WorldItem(
                                campaign_id=principal.campaign_id,
                                name=template_ref,
                                description=f"由{action.get('name') or '法术'}创造",
                                category="created",
                                quantity=count,
                                location_id=scene.location_id,
                                source_label="custom",
                                metadata_json={
                                    "created_by_spell": action.get("name"),
                                    "scene_id": scene.id,
                                    "rule_block_id": block_id,
                                    "compiled_effect_key": marker,
                                },
                            )
                            session.add(existing)
                            session.flush()
                        special_results.append(
                            {
                                "kind": "creation",
                                "entity_type": "world_item",
                                "entity_id": existing.id,
                                "count": count,
                            }
                        )
                    else:
                        row = creation_input.get("row")
                        col = creation_input.get("col")
                        if (
                            not isinstance(row, int)
                            or isinstance(row, bool)
                            or not isinstance(col, int)
                            or isinstance(col, bool)
                        ):
                            raise ValueError("创造场景物件必须提供有效的网格位置")
                        grid = session.scalar(
                            select(SceneGrid).where(SceneGrid.scene_id == scene.id)
                        )
                        if grid is None or not (1 <= row <= grid.height and 1 <= col <= grid.width):
                            raise ValueError("创造物件的位置不在当前地图内")
                        if blocked_cell(grid, row, col):
                            raise ValueError("创造物件不能放置在墙体或不可通行格")
                        existing = next(
                            (
                                item
                                for item in session.scalars(
                                    select(SceneObject).where(SceneObject.scene_id == scene.id)
                                ).all()
                                if item.metadata_json.get("compiled_effect_key") == marker
                            ),
                            None,
                        )
                        if existing is None:
                            object_type = (
                                creation_kind
                                if creation_kind in {"portal", "terrain"}
                                else "furniture"
                            )
                            existing = SceneObject(
                                scene_id=scene.id,
                                object_type=object_type,
                                label=template_ref,
                                row=row,
                                col=col,
                                state="active",
                                visibility="public",
                                metadata_json={
                                    "created_by_spell": action.get("name"),
                                    "count": count,
                                    "rule_block_id": block_id,
                                    "compiled_effect_key": marker,
                                },
                            )
                            session.add(existing)
                            session.flush()
                        special_results.append(
                            {
                                "kind": "creation",
                                "entity_type": "scene_object",
                                "entity_id": existing.id,
                                "count": count,
                            }
                        )
            elif kind == "area_effect":
                raw_areas = execution_inputs.get("areas")
                area_input = (
                    raw_areas.get(block_id)
                    if isinstance(raw_areas, dict)
                    else execution_inputs.get("area")
                )
                if block.get("origin") == "self" and area_input is None:
                    # A self-origin zone is already an explicit rule choice.  It
                    # must not force a redundant coordinate input that can drift
                    # away from the caster's live position.
                    area_input = {}
                if not isinstance(area_input, dict):
                    raise ValueError("持续区域必须在 areas 中为每个 area_effect 提供明确原点")
                scene_id = self._combat_scene_id(principal, combat_id)
                with Session(self.engine) as session, session.begin():
                    scene = session.get(Scene, scene_id) if scene_id else None
                    actor = session.get(Combatant, actor_id)
                    grid = (
                        session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))
                        if scene_id
                        else None
                    )
                    if scene is None or actor is None or grid is None:
                        raise ValueError("持续区域需要当前战斗的场景、施法者和地图")
                    if block.get("origin") == "self":
                        raw_origin = actor.snapshot_json.get("grid_position")
                    else:
                        raw_origin = area_input
                    row = raw_origin.get("row") if isinstance(raw_origin, dict) else None
                    col = raw_origin.get("col") if isinstance(raw_origin, dict) else None
                    if (
                        not isinstance(row, int)
                        or isinstance(row, bool)
                        or not isinstance(col, int)
                        or isinstance(col, bool)
                    ):
                        raise ValueError("持续区域原点必须提供有效的网格行列")
                    if not (1 <= row <= grid.height and 1 <= col <= grid.width) or blocked_cell(
                        grid, row, col
                    ):
                        raise ValueError("持续区域原点不在可用地图格内")
                    marker = f"{idempotency_key}:area:{block_id}"
                    scene_object = next(
                        (
                            item
                            for item in session.scalars(
                                select(SceneObject).where(SceneObject.scene_id == scene.id)
                            ).all()
                            if item.metadata_json.get("compiled_effect_key") == marker
                        ),
                        None,
                    )
                    if scene_object is None:
                        scene_object = SceneObject(
                            scene_id=scene.id,
                            object_type="terrain",
                            label=f"{action.get('name') or '持续区域'}区域",
                            row=row,
                            col=col,
                            state="active",
                            visibility="public",
                            metadata_json={
                                "compiled_effect_key": marker,
                                "area_effect": True,
                                "rule_block_id": block_id,
                                "shape": block.get("shape"),
                                "size_ft": block.get("size_ft"),
                                "width_ft": block.get("width_ft"),
                                "trigger_timing": block.get("trigger_timing"),
                                "effect_block_ids": block.get("effect_block_ids"),
                                "source_combatant_id": actor_id,
                            },
                        )
                        session.add(scene_object)
                        session.flush()
                with Session(self.engine) as session:
                    actor = session.get(Combatant, actor_id)
                    if actor is None:
                        raise ValueError("持续区域的施法者已不在当前战斗")
                    command = CombatEffectCommand(
                        target_combatant_id=actor.id,
                        target_version=actor.version,
                        source_combatant_id=actor.id,
                        source_version=actor.version,
                        name=str(action.get("name") or "持续区域"),
                        effect_type="aura",
                        details_json={
                            "rule_block": block,
                            "rule_plan_source": action.get("name"),
                            "scene_object_id": scene_object.id,
                            "area_origin": {"row": row, "col": col},
                        },
                        duration_unit=duration_unit,  # type: ignore[arg-type]
                        duration_value=duration_value,
                        requires_concentration=concentration,
                        trigger_timing=(
                            str(block.get("trigger_timing"))
                            if str(block.get("trigger_timing"))
                            in {"turn_start", "turn_end", "round_start", "round_end"}
                            else None
                        ),
                    )
                result = self.combat.confirm_effect(
                    principal.campaign_id,
                    combat_id,
                    command,
                    idempotency_key=f"{idempotency_key}:area-effect:{block_id}",
                )
                special_results.append(
                    {
                        "kind": "area_effect",
                        "scene_object_id": scene_object.id,
                        "origin": {"row": row, "col": col},
                        "effect": result.get("effect"),
                    }
                )
            elif kind == "dispel":
                effect_ids = execution_inputs.get("effect_ids")
                if not isinstance(effect_ids, list) or not effect_ids:
                    raise ValueError("驱散/反制效果必须明确选择要结束的效果")
                if len(set(effect_ids)) != len(effect_ids) or not all(
                    isinstance(effect_id, str) and effect_id for effect_id in effect_ids
                ):
                    raise ValueError("驱散目标效果 ID 必须是不重复的有效字符串")
                raw_checks = execution_inputs.get("dispel_checks")
                for effect_id in effect_ids:
                    with Session(self.engine) as session:
                        effect = session.get(CombatEffect, effect_id)
                        target = (
                            session.get(Combatant, effect.target_combatant_id) if effect else None
                        )
                        details = dict(effect.details_json or {}) if effect else {}
                    if effect is None or target is None or effect.combat_id != combat_id:
                        raise ValueError("驱散目标效果不存在或不属于当前战斗")
                    allowed_types = {
                        str(value) for value in block.get("effect_types", []) if str(value)
                    }
                    is_spell = isinstance(details.get("rule_plan_source"), str)
                    is_magical = is_spell or details.get("magical_effect") is True
                    if allowed_types and not (
                        ("spell" in allowed_types and is_spell)
                        or ("magical_effect" in allowed_types and is_magical)
                    ):
                        raise ValueError("所选效果不符合该驱散/反制积木允许的效果类型")
                    if block.get("check_required") is True:
                        check = raw_checks.get(effect_id) if isinstance(raw_checks, dict) else None
                        if not isinstance(check, dict):
                            raise ValueError("该驱散需要为每个效果提交明确的检定 total 和 dc")
                        total = check.get("total")
                        dc = check.get("dc")
                        if (
                            not isinstance(total, int)
                            or isinstance(total, bool)
                            or not isinstance(dc, int)
                            or isinstance(dc, bool)
                            or total < -100
                            or dc < 0
                        ):
                            raise ValueError("驱散检定 total 和 dc 必须是有效整数")
                        if total < dc:
                            special_results.append(
                                {
                                    "kind": "dispel",
                                    "effect_id": effect.id,
                                    "success": False,
                                    "total": total,
                                    "dc": dc,
                                    "effect_remains": True,
                                }
                            )
                            continue
                    result = self.combat.end_effect(
                        principal.campaign_id,
                        combat_id,
                        effect.id,
                        CombatEffectEndCommand(
                            target_version=target.version,
                            reason=f"{action.get('name') or '法术'}结束效果",
                        ),
                        idempotency_key=f"{idempotency_key}:dispel:{effect.id}:{block_id}",
                    )
                    special_results.append(
                        {
                            "kind": "dispel",
                            "effect_id": effect.id,
                            "success": True,
                            "result": result,
                        }
                    )
        return [*applied, *movement_results, *special_results]

    def _write_temporary_hp(
        self,
        *,
        action_results: list[dict[str, Any]],
        amount: int,
    ) -> list[dict[str, Any]]:
        """Persist non-stacking temporary HP against the confirmed action rows.

        ``CombatActionCommand`` intentionally models ordinary healing only.  The
        command still spends the action/resource and gives us an idempotent audit
        row; this write records the distinct temporary-HP rule on that confirmed
        action, rather than treating it as normal healing or silently adding it to
        current HP.
        """

        applied: list[dict[str, Any]] = []
        with Session(self.engine) as session, session.begin():
            for raw_result in action_results:
                raw_action = raw_result.get("action")
                action_id = raw_action.get("id") if isinstance(raw_action, dict) else None
                action = (
                    session.get(CombatAction, action_id) if isinstance(action_id, str) else None
                )
                if action is None or not action.target_combatant_ids:
                    continue
                target = session.get(Combatant, action.target_combatant_ids[0])
                if target is None:
                    continue
                result_json = dict(action.result_json or {})
                existing = result_json.get("temporary_hp_application")
                if isinstance(existing, dict):
                    granted = int(existing.get("resulting_temporary_hp") or target.temporary_hp)
                    applied.append(
                        {
                            "target_combatant_id": target.id,
                            "temporary_hp": granted,
                            "already_applied": True,
                        }
                    )
                    continue
                before = target.temporary_hp
                resulting = max(before, amount)
                target.temporary_hp = resulting
                target.version += 1
                target.updated_at = _now()
                result_json["temporary_hp_application"] = {
                    "reported_amount": amount,
                    "previous_temporary_hp": before,
                    "resulting_temporary_hp": resulting,
                    "replaced": amount > before,
                }
                action.result_json = result_json
                action.summary = f"{action.summary}；临时生命 {before} → {resulting}"
                action.version += 1
                action.updated_at = _now()
                if isinstance(raw_result.get("target"), dict):
                    raw_result["target"] = {
                        **raw_result["target"],
                        "temporary_hp": resulting,
                        "version": target.version,
                    }
                applied.append(
                    {
                        "target_combatant_id": target.id,
                        "temporary_hp": resulting,
                        "replaced": amount > before,
                    }
                )
        return applied

    def _spend_character_resource(
        self,
        character_id: str,
        resource_key: str,
        resource_cost: int,
    ) -> None:
        """Persist a confirmed combat resource cost after its effects are written."""

        if not resource_key or resource_cost <= 0:
            return
        with Session(self.engine) as session, session.begin():
            character = session.get(Character, character_id)
            if character is None:
                raise StateNotFoundError("character not found")
            resources = dict(character.resources or {})
            resource = json_dict(resources.get(resource_key))
            resource["current"] = max(0, int(resource.get("current") or 0) - resource_cost)
            resources[resource_key] = resource
            # Assign through the loaded row so the JSON value is flushed by the
            # same session that validated and spent the resource.  A bulk
            # UPDATE here can be overwritten by a stale JSON attribute when a
            # concurrent combat-effect transaction expires/refreshes the same
            # Character row between the cast and the spend.
            character.resources = resources
            character.version += 1
            character.updated_at = _now()

    def _consume_bardic_inspiration_after_attack(
        self,
        actor_id: str,
        context: dict[str, Any],
        operation_id: str,
    ) -> dict[str, Any]:
        """Consume an attack-roll die after the authoritative damage event succeeds."""

        with Session(self.engine) as session, session.begin():
            actor = session.get(Combatant, actor_id)
            if actor is None:
                raise StateNotFoundError("攻击者不存在")
            return CombatEngineService._consume_bardic_inspiration(
                actor,
                context,
                operation_id=operation_id,
            )

    def attack(
        self,
        principal: PlayerPrincipal,
        target_id: str,
        target_ids: list[str],
        action_name: str,
        slot_level: int | None,
        attack_total: int,
        damage_total: int,
        critical_hit: bool,
        end_turn_after: bool,
        idempotency_key: str,
        damage_component_totals: dict[str, int] | None = None,
        target_damage_component_totals: dict[str, dict[str, int]] | None = None,
        reaction_trigger: str | None = None,
        special_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        damage_component_totals = dict(damage_component_totals or {})
        target_damage_component_totals = dict(target_damage_component_totals or {})
        special_inputs = dict(special_inputs or {})
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            fighters = session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
                .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
            ).all()
            target = next((item for item in fighters if item.id == target_id), None)
            active = fighters[combat.current_turn_index] if fighters else None
            character = session.get(Character, principal.character_id)
            actor = self._controlled_actor(fighters, active, principal.character_id)
            if actor is None or target is None or character is None:
                raise ValueError("当前角色、目标或回合无效")
            CombatEngineService._validate_can_act(actor)
            if CombatEngineService._has_condition(actor, "charmed"):
                charmer_ids = CombatEngineService._condition_source_ids(
                    session,
                    combat.id,
                    actor,
                    "charmed",
                )
                if target.id in charmer_ids:
                    raise ValueError("魅惑状态下不能攻击魅惑来源")
            action = (
                self._action_data(session, character, action_name)
                if actor.entity_type == "character"
                else self._companion_action_data(actor, action_name)
            )
            if action.get("resolution_kind") == "weapon_attack":
                input_key = str(action.get("feature_attack_profile_input_key") or "").strip()
                selected_name = str(special_inputs.get(input_key) or "").strip()
                if not input_key or not selected_name or selected_name == action_name:
                    raise ValueError("该职业特性攻击必须提交一个不同的武器或徒手动作名")
                selected = self._action_data(session, character, selected_name)
                selected_text = " ".join(
                    str(selected.get(key) or "")
                    for key in ("name", "description", "attack_type")
                )
                selected_is_spell = bool(
                    selected.get("kind") == "spell"
                    or selected.get("is_spell") is True
                    or selected.get("spell_level") is not None
                    or selected.get("action_type") == "spellcasting"
                )
                selected_is_melee = bool(
                    selected.get("melee_weapon_attack") is True
                    or selected.get("is_unarmed_attack") is True
                    or "近战" in selected_text
                    or "徒手" in selected_text
                )
                selected_is_weapon = bool(
                    selected.get("is_weapon_attack") is True
                    or "武器攻击" in selected_text
                    or "weapon attack" in selected_text.lower()
                )
                selected_is_unarmed = bool(
                    selected.get("is_unarmed_attack") is True or "徒手" in selected_text
                )
                if selected_is_spell or not selected_is_melee or not (
                    selected_is_weapon or selected_is_unarmed
                ):
                    raise ValueError("战争祭司只能选择近战武器攻击或徒手打击")
                if selected.get("area_shape") or selected.get("affects_multiple_targets"):
                    raise ValueError("职业特性攻击不能选择区域或多目标动作")
                preserved = {
                    key: action.get(key)
                    for key in ("name", "cost", "resource_key", "resource_cost")
                }
                action = {
                    **action,
                    **{
                        key: selected.get(key)
                        for key in (
                            "damage",
                            "damage_expression",
                            "damage_dice",
                            "damage_type",
                            "range",
                            "description",
                            "rule_plan",
                            "attack_ability",
                            "ability",
                            "is_weapon_attack",
                            "melee_weapon_attack",
                            "damage_tags",
                        )
                        if selected.get(key) not in (None, "")
                    },
                    "is_unarmed_attack": selected_is_unarmed,
                    **preserved,
                }
            # Ritual-only grants are resolved through the noncombat ritual
            # planner.  They are not combat actions: allowing them here would
            # silently turn a ten-minute ritual into an instantaneous cast.
            if action.get("ritual_only") is True:
                raise ValueError("仪式法术不能在战斗中施放")
            if slot_level is not None:
                base_level = int(action.get("spell_level") or 0)
                if base_level <= 0 or slot_level < base_level:
                    raise ValueError("该动作不是可升环法术，或施法环阶低于法术本环")
                action = upcast_spell_action(action, slot_level)
            blocks = self._action_rule_blocks(action)
            self._selected_choice_block_ids(blocks, special_inputs)
            range_text = str(action.get("range") or "").strip()
            target_block = next(
                (block for block in blocks if block.get("kind") == "target"),
                None,
            )
            if target_block is None:
                raise ValueError("该动作缺少结构化目标规则，无法自动结算")
            try:
                target_rule = TargetBlock.model_validate(target_block)
            except ValueError as exc:
                raise ValueError("该动作的目标规则无效，无法自动结算") from exc
            area_block = next(
                (block for block in blocks if block.get("kind") == "area_effect"),
                None,
            )
            # Older compiled projections represented an instantaneous area as
            # `target: point/self` plus a separate area_effect block.  For
            # damage/save resolution it must behave like one multi-target
            # area target, otherwise the UI can preview the shape but the
            # executor rejects every target except the caster.
            if (
                target_rule.mode in {"self", "point"}
                and isinstance(area_block, dict)
                and any(
                    block.get("kind") in {"damage", "save", "move"}
                    and str(block.get("id")) in {
                        str(child_id)
                        for child_id in area_block.get("effect_block_ids", [])
                        if isinstance(child_id, str)
                    }
                    for block in blocks
                )
            ):
                target_rule = TargetBlock.model_validate({
                    **target_block,
                    "mode": "area",
                    "shape": area_block.get("shape"),
                    "size_ft": area_block.get("size_ft"),
                    "width_ft": area_block.get("width_ft"),
                    "height_ft": area_block.get("height_ft"),
                    "anchor_height_ft": area_block.get("anchor_height_ft", 0),
                    "requires_explicit_elevation": area_block.get(
                        "requires_explicit_elevation", False
                    ),
                })
            plan_range = target_block.get("range_ft")
            plan_size = target_rule.size_ft or (
                area_block.get("size_ft") if isinstance(area_block, dict) else None
            )
            plan_height = target_rule.height_ft or (
                area_block.get("height_ft") if isinstance(area_block, dict) else None
            )
            plan_anchor_height = target_rule.anchor_height_ft or (
                area_block.get("anchor_height_ft", 0) if isinstance(area_block, dict) else 0
            )
            requires_explicit_elevation = bool(
                target_rule.requires_explicit_elevation
                or (
                    area_block.get("requires_explicit_elevation", False)
                    if isinstance(area_block, dict)
                    else False
                )
            )
            plan_mode = target_rule.mode
            plan_shape = target_rule.shape or (
                area_block.get("shape") if isinstance(area_block, dict) else None
            )
            if not range_text and isinstance(plan_range, int) and plan_range >= 0:
                range_text = "自身" if plan_mode == "self" else f"{plan_range}尺"
            if not range_text:
                raise ValueError("该动作的攻击范围未明确，请由 DM 裁定后再执行")
            range_numbers = [
                int(value)
                for value in re.findall(
                    r"(\d+)\s*(?:尺|英尺|ft\.?|feet|foot)",
                    range_text,
                    flags=re.IGNORECASE,
                )
            ]
            if not range_numbers and isinstance(plan_range, int) and plan_range >= 0:
                range_numbers = [plan_range]
            if not range_numbers:
                raise ValueError("该动作的攻击范围未明确，请由 DM 裁定后再执行")
            maximum_range = (
                None
                if target_rule.mode == "area" and target_rule.range_ft == 0
                else range_numbers[0]
            )
            actor_pos = actor.snapshot_json.get("grid_position")
            target_pos = target.snapshot_json.get("grid_position")
            if not isinstance(actor_pos, dict) or not isinstance(target_pos, dict):
                raise ValueError("攻击者或目标尚未设置战斗地图位置")
            scene_id = combat.scene_id or (room.current_scene_id if room else None)
            grid = (
                session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))
                if scene_id
                else None
            )
            aim_pos = target_pos
            raw_aim = special_inputs.get("aim_point")
            if target_rule.mode == "area" and raw_aim is not None:
                if (
                    not isinstance(raw_aim, dict)
                    or isinstance(raw_aim.get("row"), bool)
                    or not isinstance(raw_aim.get("row"), int)
                    or isinstance(raw_aim.get("col"), bool)
                    or not isinstance(raw_aim.get("col"), int)
                ):
                    raise ValueError("区域法术必须提供有效的 aim_point 行列")
                aim_pos = raw_aim
            if grid is None:
                if target_rule.mode != "self":
                    raise ValueError("战斗地图网格未明确，不能默认距离结算法术目标")
                distance = 0
            else:
                distance = grid_distance_ft(
                    (int(actor_pos["row"]), int(actor_pos["col"])),
                    (int(aim_pos["row"]), int(aim_pos["col"])),
                    cell_size_ft=grid.cell_size_ft,
                )
                if not (
                    1 <= int(aim_pos["row"]) <= grid.height
                    and 1 <= int(aim_pos["col"]) <= grid.width
                ):
                    raise ValueError("区域法术瞄准点超出当前战斗地图")
            if maximum_range is not None and distance > maximum_range:
                raise ValueError("目标超出该动作的合法距离")
            sight_blockers: set[tuple[int, int]] = set()
            cover_cells: set[tuple[int, int]] = set()
            if grid is not None:
                raw_cells = grid.layers_json.get("cells", [])
                if isinstance(raw_cells, list):
                    for cell in raw_cells:
                        if not isinstance(cell, dict):
                            continue
                        if not isinstance(cell.get("row"), int) or not isinstance(
                            cell.get("col"), int
                        ):
                            continue
                        point = (int(cell["row"]), int(cell["col"]))
                        cover_default = (
                            "translucent" if cell.get("kind") == "cover" else "transparent"
                        )
                        behavior = CombatEngineService._sight_transparency(
                            cell,
                            default=(
                                "opaque"
                                if cell.get("kind") == "wall"
                                or cell.get("blocks_sight") is True
                                else cover_default
                            ),
                        )
                        if behavior == "translucent":
                            cover_cells.add(point)
                        if behavior == "opaque":
                            sight_blockers.add(point)
                scene_objects = session.scalars(
                    select(SceneObject).where(SceneObject.scene_id == grid.scene_id)
                ).all()
                for scene_object in scene_objects:
                    if scene_object.state in {"destroyed", "picked_up"}:
                        continue
                    object_cells = {
                        (row, col)
                        for row in range(
                            scene_object.row,
                            scene_object.row + scene_object.height_cells,
                        )
                        for col in range(
                            scene_object.col,
                            scene_object.col + scene_object.width_cells,
                        )
                    }
                    metadata = dict(scene_object.metadata_json or {})
                    if (scene_object.object_type == "cover" and scene_object.state == "active") or (
                        scene_object.object_type == "furniture"
                        and scene_object.state == "active"
                        and metadata.get("provides_cover") is True
                    ):
                        if CombatEngineService._sight_transparency(
                            metadata,
                            default="translucent",
                        ) != "transparent":
                            cover_cells.update(object_cells)
                    blocks_sight = scene_object.object_type == "wall" or (
                        scene_object.object_type == "door"
                        and scene_object.state in {"active", "closed"}
                    )
                    if not blocks_sight:
                        continue
                    behavior = CombatEngineService._sight_transparency(
                        metadata,
                        default="opaque",
                    )
                    if behavior == "translucent":
                        cover_cells.update(object_cells)
                    elif behavior == "opaque":
                        sight_blockers.update(object_cells)
            actor_point = (int(actor_pos["row"]), int(actor_pos["col"]))
            target_point = (int(aim_pos["row"]), int(aim_pos["col"]))

            def explicit_elevation(
                position: dict[str, Any],
                label: str,
            ) -> int | None:
                for key in ("elevation_ft", "height_ft", "z"):
                    value = position.get(key)
                    if isinstance(value, int) and not isinstance(value, bool):
                        return value
                if requires_explicit_elevation:
                    raise ValueError(
                        f"高级三维区域需要{label}记录 grid_position.elevation_ft"
                    )
                return None

            actor_elevation = explicit_elevation(actor_pos, "施法者")

            def sight_check(
                start: tuple[int, int],
                end: tuple[int, int],
                end_position: dict[str, Any],
                label: str,
                end_combatant: Combatant | None = None,
            ) -> tuple[bool, str]:
                """Use the combat engine's authoritative 2-D/3-D sight rule."""

                if grid is None:
                    return line_of_sight(start, end, sight_blockers), "2d"
                end_elevation = explicit_elevation(end_position, label)
                start_elevation = actor_elevation if start == actor_point else (
                    int(plan_anchor_height or 0)
                    if requires_explicit_elevation
                    else None
                )
                if (
                    end_combatant is not None
                    and start == actor_point
                    and end == CombatEngineService._grid_point(end_combatant)
                ):
                    has_sight, sight_mode, _ = CombatEngineService._grid_footprint_line_of_sight(
                        session,
                        grid,
                        CombatEngineService._grid_footprint(actor),
                        CombatEngineService._grid_footprint(end_combatant),
                        sight_blockers,
                        start_height_ft=start_elevation,
                        end_height_ft=end_elevation,
                    )
                    return has_sight, sight_mode
                return CombatEngineService._grid_line_of_sight(
                    session,
                    grid,
                    start,
                    end,
                    sight_blockers,
                    start_height_ft=start_elevation,
                    end_height_ft=end_elevation,
                )

            def combatant_position(item: Combatant) -> tuple[int, int] | None:
                raw_position = item.snapshot_json.get("grid_position")
                if (
                    not isinstance(raw_position, dict)
                    or "row" not in raw_position
                    or "col" not in raw_position
                ):
                    return None
                return int(raw_position["row"]), int(raw_position["col"])

            visible_cells: set[tuple[int, int]] | None = None
            if grid is not None and scene_id is not None:
                scene = session.get(Scene, scene_id)
                if scene is not None:
                    visible_cells = self._visibility_for(
                        session,
                        scene,
                        principal,
                        grid,
                        origin_override=actor_point,
                    )["visible"]
            if visible_cells is not None and target_point not in visible_cells:
                raise ValueError("目标处于战争迷雾中，当前不可见")
            has_sight, sight_mode = sight_check(
                actor_point,
                target_point,
                target_pos,
                f"目标 {target.display_name}",
                target,
            )
            if not has_sight:
                raise ValueError("目标被墙体或关闭的门完全遮挡，无法建立攻击视线")
            cover_kind = cover_between(
                actor_point,
                target_point,
                cover_cells,
                sight_blockers if sight_mode == "2d" else set(),
            )
            cover_bonus = 2 if cover_kind == "half" else 0
            cost_text = str(action.get("cost") or "动作")
            cost: Literal["action", "bonus_action", "reaction"] = (
                "bonus_action"
                if "附赠" in cost_text
                else "reaction"
                if "反应" in cost_text
                else "action"
            )
            if cost == "reaction" and not (reaction_trigger or "").strip():
                raise ValueError("反应动作必须由玩家明确填写 reaction_trigger")
            damage_rules = [
                DamageBlock.model_validate(block)
                for block in blocks
                if block.get("kind") == "damage"
            ]
            if not damage_rules:
                raise ValueError("该动作缺少可验证的伤害规则，不能自动结算")
            shared_damage_rules = [block for block in damage_rules if block.shared_roll]
            target_damage_rules = [block for block in damage_rules if not block.shared_roll]
            combat_id = combat.id
            save_rule = next((block for block in blocks if block.get("kind") == "save"), None)
            save_ability = str(
                (save_rule.get("ability") if isinstance(save_rule, dict) else None)
                or action.get("save_ability")
                or ""
            )
            raw_save_dc = (
                save_rule.get("dc") if isinstance(save_rule, dict) else action.get("save_dc")
            )
            save_dc = int(raw_save_dc) if isinstance(raw_save_dc, int) else 0
            spell_save_dc_bonus = self._feature_additive_modifier(
                actor,
                "spell_save_dc",
                scope="outgoing",
            )
            if spell_save_dc_bonus:
                save_dc += spell_save_dc_bonus
            save_on_success = str(
                (save_rule.get("on_success") if isinstance(save_rule, dict) else None)
                or ("half" if action.get("half_damage_on_save") else "none")
            )
            if save_on_success not in {"none", "half", "full"}:
                raise ValueError("该法术的豁免成功效果需要 DM 裁定")
            saving_throw_action = bool(save_ability and save_dc)
            auto_hit_action = bool(action.get("auto_hit") is True)
            bardic_inspiration: dict[str, Any] | None = None
            combat_inspiration_mode: str | None = None
            raw_combat_mode = special_inputs.get("bardic_inspiration_mode")
            if raw_combat_mode is not None:
                combat_inspiration_mode = str(raw_combat_mode).strip().lower()
                if combat_inspiration_mode not in {"defense", "offense"}:
                    raise ValueError("战斗激励模式必须是 defense 或 offense")
            raw_bardic_total = special_inputs.get("bardic_inspiration_total")
            if raw_bardic_total is not None:
                if (
                    isinstance(raw_bardic_total, bool)
                    or not isinstance(raw_bardic_total, int)
                ):
                    raise ValueError("吟游诗人激励骰结果必须是整数")
                if saving_throw_action or auto_hit_action:
                    raise ValueError("吟游诗人激励骰只能用于攻击检定")
                inspiration_command = PlayerRollResolutionCommand(
                    action_version=1,
                    roll_total=0,
                    bardic_inspiration_total=raw_bardic_total,
                )
                inspiration_target = actor
                if combat_inspiration_mode == "defense":
                    inspiration_target = target
                    raw_die = (
                        (target.snapshot_json.get("feature_dice") or {}).get(
                            "bardic_inspiration_die"
                        )
                        if isinstance(target.snapshot_json.get("feature_dice"), dict)
                        else None
                    )
                    modes = raw_die.get("mode_options") if isinstance(raw_die, dict) else None
                    if not isinstance(modes, list) or "defense" not in modes:
                        raise ValueError("目标持有的激励骰不支持战斗激励防御选项")
                elif combat_inspiration_mode == "offense":
                    raw_die = (
                        (actor.snapshot_json.get("feature_dice") or {}).get(
                            "bardic_inspiration_die"
                        )
                        if isinstance(actor.snapshot_json.get("feature_dice"), dict)
                        else None
                    )
                    modes = raw_die.get("mode_options") if isinstance(raw_die, dict) else None
                    if not isinstance(modes, list) or "offense" not in modes:
                        raise ValueError("攻击者持有的激励骰不支持战斗激励进攻选项")
                    inspiration_target = actor
                bardic_inspiration = CombatEngineService._bardic_inspiration_context(
                    inspiration_target,
                    inspiration_command,
                    operation_id=idempotency_key,
                )
                if bardic_inspiration is not None:
                    bardic_inspiration["mode"] = combat_inspiration_mode or "attack_roll"
            requested_targets, target_resolution = self._resolve_combat_targets(
                target_rule=target_rule,
                actor=actor,
                primary_target_id=target.id,
                requested_target_ids=target_ids,
                fighters=fighters,
            )
            if visible_cells is not None and any(
                combatant_position(item) not in visible_cells for item in requested_targets
            ):
                raise ValueError("区域内有目标处于战争迷雾中，当前不可见")

            if target_rule.mode == "multiple":
                if grid is None:
                    raise ValueError("多目标法术需要明确的战斗地图网格")
                if target_rule.range_ft is None:
                    raise ValueError("多目标法术的首目标距离未明确，请由 DM 裁定")
                for candidate in requested_targets[1:]:
                    candidate_pos = candidate.snapshot_json.get("grid_position")
                    if not isinstance(candidate_pos, dict):
                        raise ValueError("多目标法术目标尚未设置战斗地图位置")
                    secondary_point = (int(candidate_pos["row"]), int(candidate_pos["col"]))
                    if target_rule.secondary_range_ft is not None:
                        legal_distance = grid_distance_ft(
                            target_point,
                            secondary_point,
                            cell_size_ft=grid.cell_size_ft,
                        )
                        legal_maximum = target_rule.secondary_range_ft
                    else:
                        legal_distance = grid_distance_ft(
                            actor_point,
                            secondary_point,
                            cell_size_ft=grid.cell_size_ft,
                        )
                        legal_maximum = target_rule.range_ft
                    if legal_distance > legal_maximum:
                        raise ValueError(f"{candidate.display_name}超出该法术的多目标合法距离")
                    secondary_sight, _ = sight_check(
                        actor_point,
                        secondary_point,
                        candidate_pos,
                        f"目标 {candidate.display_name}",
                        candidate,
                    )
                    if target_rule.requires_line_of_sight and not secondary_sight:
                        raise ValueError(f"{candidate.display_name}无法建立法术视线")
            elif target_rule.mode == "area":
                if grid is None:
                    raise ValueError("区域法术需要明确的战斗地图网格")
                # ``target_point`` is the explicit map aim point when the UI
                # sends special_inputs.aim_point. Do not replace it with the
                # primary affected creature: that would rotate self-origin
                # cubes toward whichever target happened to be listed first.
                aim_point = target_point
                cell_size = grid.cell_size_ft
                shape = str(plan_shape)
                if shape not in {"cone", "cube", "line", "sphere", "cylinder"}:
                    raise ValueError("区域法术的形状未明确，请由 DM 裁定")
                if not isinstance(plan_size, int) or plan_size <= 0:
                    raise ValueError("区域法术的尺寸未明确，请由 DM 裁定")
                if shape == "line" and target_rule.width_ft is None:
                    raise ValueError("线状区域的宽度未明确，请由 DM 裁定")
                if shape == "cylinder" and not isinstance(plan_height, int):
                    raise ValueError("圆柱区域的高度未明确，请由 DM 裁定")
                radius = plan_size
                width = target_rule.width_ft if shape == "line" else plan_size
                if width is None:
                    raise ValueError("区域法术的宽度未明确，请由 DM 裁定")
                actor_row, actor_col = actor_point
                aim_row, aim_col = aim_point
                vector_row = aim_row - actor_row
                vector_col = aim_col - actor_col
                length_squared = vector_row**2 + vector_col**2
                for candidate in requested_targets:
                    candidate_pos = candidate.snapshot_json.get("grid_position")
                    if not isinstance(candidate_pos, dict):
                        raise ValueError("区域目标尚未设置战斗地图位置")
                    candidate_point = (
                        int(candidate_pos["row"]),
                        int(candidate_pos["col"]),
                    )
                    candidate_elevation = explicit_elevation(
                        candidate_pos,
                        f"目标 {candidate.display_name}",
                    )
                    candidate_height = candidate_elevation if candidate_elevation is not None else 0
                    origin_height = actor_elevation if actor_elevation is not None else 0
                    legal = candidate.id == target.id
                    if shape == "sphere":
                        horizontal_ft = grid_distance_ft(
                            aim_point,
                            candidate_point,
                            cell_size_ft=cell_size,
                        )
                        vertical_ft = candidate_height - int(plan_anchor_height or 0)
                        legal = (
                            horizontal_ft**2 + vertical_ft**2
                        ) ** 0.5 <= radius + 0.01 and sight_check(
                            aim_point,
                            candidate_point,
                            candidate_pos,
                            f"目标 {candidate.display_name}",
                        )[0]
                    elif shape == "cylinder":
                        legal = grid_distance_ft(
                            aim_point,
                            candidate_point,
                            cell_size_ft=cell_size,
                        ) <= radius and sight_check(
                            aim_point,
                            candidate_point,
                            candidate_pos,
                            f"目标 {candidate.display_name}",
                        )[0] and int(plan_anchor_height or 0) <= candidate_height < int(
                            plan_anchor_height or 0
                        ) + int(plan_height)
                    elif shape == "cube":
                        size_cells = max(0.5, width / cell_size)
                        if target_rule.range_ft == 0 and aim_point != actor_point:
                            direction_row = aim_row - actor_row
                            direction_col = aim_col - actor_col
                            direction_length = (direction_row**2 + direction_col**2) ** 0.5
                            relative_row = candidate_point[0] - actor_row
                            relative_col = candidate_point[1] - actor_col
                            forward = (
                                relative_row * direction_row + relative_col * direction_col
                            ) / direction_length
                            lateral = abs(
                                relative_row * direction_col - relative_col * direction_row
                            ) / direction_length
                            legal = (
                                forward >= -0.01
                                and forward <= size_cells + 0.01
                                and lateral <= size_cells / 2 + 0.01
                                and (
                                    not requires_explicit_elevation
                                    or int(plan_anchor_height or 0)
                                    <= candidate_height
                                    < int(plan_anchor_height or 0) + width
                                )
                                and sight_check(
                                    actor_point,
                                    candidate_point,
                                    candidate_pos,
                                    f"目标 {candidate.display_name}",
                                )[0]
                            )
                        else:
                            center = actor_point if target_rule.range_ft == 0 else aim_point
                            legal = max(
                                abs(candidate_point[0] - center[0]),
                                abs(candidate_point[1] - center[1]),
                            ) <= size_cells / 2 + 0.01 and (
                                not requires_explicit_elevation
                                or int(plan_anchor_height or 0)
                                <= candidate_height
                                < int(plan_anchor_height or 0) + width
                            ) and sight_check(
                                center,
                                candidate_point,
                                candidate_pos,
                                f"目标 {candidate.display_name}",
                            )[0]
                    elif shape == "cone" and length_squared > 0:
                        candidate_row = candidate_point[0] - actor_row
                        candidate_col = candidate_point[1] - actor_col
                        candidate_distance = (candidate_row**2 + candidate_col**2) ** 0.5
                        forward = (candidate_row * vector_row + candidate_col * vector_col) / (
                            length_squared**0.5
                        )
                        legal = (
                            candidate_distance <= width / cell_size + 0.01
                            and forward >= 0
                            and (
                                candidate_distance == 0
                                or forward / candidate_distance >= 2**-0.5 - 0.01
                            )
                            and (
                                not requires_explicit_elevation
                                or abs(candidate_height - origin_height)
                                <= forward * cell_size + 0.01
                            )
                            and sight_check(
                                actor_point,
                                candidate_point,
                                candidate_pos,
                                f"目标 {candidate.display_name}",
                            )[0]
                        )
                    elif shape == "line" and length_squared > 0:
                        candidate_range = grid_distance_ft(
                            actor_point,
                            candidate_point,
                            cell_size_ft=cell_size,
                        )
                        candidate_row = candidate_point[0] - actor_row
                        candidate_col = candidate_point[1] - actor_col
                        projection = (
                            candidate_row * vector_row + candidate_col * vector_col
                        ) / length_squared
                        closest_row = actor_row + projection * vector_row
                        closest_col = actor_col + projection * vector_col
                        perpendicular_ft = (
                            (
                                (candidate_point[0] - closest_row) ** 2
                                + (candidate_point[1] - closest_col) ** 2
                            )
                            ** 0.5
                        ) * cell_size
                        legal = (
                            0 <= projection
                            and candidate_range <= maximum_range
                            and perpendicular_ft <= max(cell_size / 2, width / 2)
                            and (
                                not requires_explicit_elevation
                                or abs(candidate_height - origin_height) <= width / 2 + 0.01
                            )
                            and sight_check(
                                actor_point,
                                candidate_point,
                                candidate_pos,
                                f"目标 {candidate.display_name}",
                            )[0]
                        )
                    if not legal:
                        raise ValueError(f"{candidate.display_name}不在玩家选择的技能范围内")
            elif target_rule.mode not in {"multiple", "area"} and not saving_throw_action:
                requested_targets = [target]

            resource_key = str(action.get("resource_key") or "")
            resource_cost = int(action.get("resource_cost") or 0)
            if actor.entity_type != "character":
                resource_key = ""
                resource_cost = 0
            if resource_key and resource_cost and actor.entity_type == "character":
                resource = (character.resources or {}).get(resource_key)
                current = int(resource.get("current") or 0) if isinstance(resource, dict) else 0
                if current < resource_cost:
                    raise ValueError("对应法术位或资源不足")
            # Feature weapon attacks carry their primary resource through the
            # authoritative combat command.  Keep the final player-room
            # bookkeeping from spending that same resource a second time.
            primary_resource_consumed_by_combat = bool(
                action.get("resolution_kind") == "weapon_attack"
                and resource_key
                and resource_cost > 0
                and actor.entity_type == "character"
            )

            # A shared component is reported once; a non-shared component must
            # be reported for each resolved target.  No dice total is copied,
            # split, or inferred from another damage type.
            try:
                shared_components = (
                    resolve_damage_component_totals(
                        shared_damage_rules,
                        legacy_total=(
                            damage_total
                            if not damage_component_totals and len(shared_damage_rules) == 1
                            else None
                        ),
                        component_totals=damage_component_totals or None,
                    )
                    if shared_damage_rules
                    else ()
                )
            except ValueError as exc:
                raise ValueError(
                    "共用伤害段必须按 damage_component_totals 为每个伤害积木提交最终总值"
                ) from exc
            if target_damage_rules:
                expected_target_ids = {item.id for item in requested_targets}
                if set(target_damage_component_totals) != expected_target_ids:
                    raise ValueError(
                        "非共用伤害段必须在 target_damage_component_totals 中为每个目标分别提交"
                    )
            elif target_damage_component_totals:
                raise ValueError("该动作没有非共用伤害段，不能提交 target_damage_component_totals")

            def components_for(current_target: Combatant) -> list[Any]:
                if target_damage_rules:
                    raw_totals = target_damage_component_totals.get(current_target.id)
                    if not isinstance(raw_totals, dict):
                        raise ValueError("每个目标的非共用伤害段必须是对象")
                    try:
                        target_components = resolve_damage_component_totals(
                            target_damage_rules,
                            component_totals=raw_totals,
                        )
                    except ValueError as exc:
                        raise ValueError("目标伤害段必须精确匹配非共用伤害积木 ID") from exc
                else:
                    target_components = ()
                by_block_id = {
                    component.block_id: component
                    for component in (*shared_components, *target_components)
                }
                return [by_block_id[rule.id] for rule in damage_rules]

            effect_targets: dict[str, bool] = {}
            target_outcome_codes: dict[str, str] = {}
            target_outcomes: list[dict[str, Any]] = []
            damage_specs: list[dict[str, Any]] = []
            rider_turn_key = f"{combat.round_number}:{combat.current_turn_index}"
            raw_rider_usage = actor.snapshot_json.get("attack_rider_uses")
            rider_usage = (
                raw_rider_usage.get(rider_turn_key, [])
                if isinstance(raw_rider_usage, dict)
                else []
            )
            riders_used_this_turn = {
                str(value) for value in rider_usage if isinstance(value, str)
            }
            riders_applied_this_call: set[str] = set()
            rider_results_by_target: dict[str, list[dict[str, Any]]] = {}
            attack_bonus, _, _ = self._rule_modifier(
                actor,
                "attack_roll",
                scope="outgoing",
            )
            damage_bonus, _, _ = self._rule_modifier(
                actor,
                "damage_roll",
                scope="outgoing",
            )
            first_damage_block_id = damage_rules[0].id
            for current_target in requested_targets:
                components = components_for(current_target)
                current_target_position = current_target.snapshot_json.get("grid_position")
                current_distance = (
                    grid_distance_ft(
                        actor_point,
                        (
                            int(current_target_position["row"]),
                            int(current_target_position["col"]),
                        ),
                        cell_size_ft=grid.cell_size_ft,
                    )
                    if grid is not None
                    and isinstance(current_target_position, dict)
                    and isinstance(current_target_position.get("row"), int)
                    and isinstance(current_target_position.get("col"), int)
                    else None
                )
                condition_attack_roll_mode, _, _, condition_automatic_critical = (
                    self._condition_attack_context(
                        actor,
                        current_target,
                        distance_ft=current_distance,
                        action=action,
                        session=session,
                        combat_id=combat.id,
                    )
                )
                # Saving throws and auto-hit effects do not make attack rolls;
                # conditions on their targets must not force two d20 inputs or
                # turn Magic Missile-style damage into a critical hit.
                attack_roll_mode = (
                    condition_attack_roll_mode
                    if not saving_throw_action and not auto_hit_action
                    else "normal"
                )
                automatic_critical = (
                    condition_automatic_critical
                    if not saving_throw_action and not auto_hit_action
                    else False
                )
                reported_attack_rolls = special_inputs.get("attack_roll_totals")
                attack_rolls = (
                    [int(value) for value in reported_attack_rolls]
                    if isinstance(reported_attack_rolls, list)
                    and all(
                        isinstance(value, (int, float)) and not isinstance(value, bool)
                        for value in reported_attack_rolls
                    )
                    else []
                )
                if attack_roll_mode != "normal" and len(attack_rolls) < 2:
                    raise ValueError(
                        f"该攻击受到{attack_roll_mode}影响，必须提交 "
                        "attack_roll_totals 中的两个 d20 结果"
                    )
                if attack_roll_mode == "advantage":
                    effective_attack_roll = max(attack_rolls[:2])
                elif attack_roll_mode == "disadvantage":
                    effective_attack_roll = min(attack_rolls[:2])
                else:
                    effective_attack_roll = attack_total
                if bardic_inspiration is not None and bardic_inspiration.get("mode") != "offense":
                    effective_attack_roll += int(bardic_inspiration["value"])
                save: dict[str, Any] | None = None
                if saving_throw_action:
                    scores = current_target.snapshot_json.get("ability_scores")
                    save_bonus, save_advantage, save_disadvantage = self._rule_modifier(
                        current_target,
                        "saving_throw",
                        scope="self",
                        skill=save_ability,
                        session=session,
                        combat_id=combat.id,
                    )
                    rolls = [secrets.randbelow(20) + 1, secrets.randbelow(20) + 1]
                    if save_advantage and not save_disadvantage:
                        selected_roll = max(rolls)
                    elif save_disadvantage and not save_advantage:
                        selected_roll = min(rolls)
                    else:
                        selected_roll = rolls[0]
                    save = roll_save(
                        scores if isinstance(scores, dict) else {},
                        save_ability,
                        save_dc,
                        roller=lambda _low, _high, value=selected_roll: value,
                    )
                    if save_bonus:
                        save["modifier"] += save_bonus
                        save["total"] += save_bonus
                        save["formula"] += f"{save_bonus:+d}"
                        save["success"] = save["total"] >= save_dc
                        save["note"] = f"已应用结构化豁免熟练/修正 {save_bonus:+d}。"
                    if save_advantage != save_disadvantage:
                        save["rolls"] = rolls
                        save["advantage"] = save_advantage and not save_disadvantage
                        save["disadvantage"] = save_disadvantage and not save_advantage
                    outcome_code = "save_success" if save["success"] else "save_failure"
                    effect_targets[current_target.id] = not save["success"]
                    note = (
                        f"{current_target.display_name}{save['ability_label']}豁免 "
                        f"{save['raw_roll']} {save['modifier']:+d} = {save['total']} "
                        f"vs DC {save_dc}：{'成功' if save['success'] else '失败'}"
                    )
                else:
                    effective_armor_class = current_target.armor_class + cover_bonus
                    if (
                        bardic_inspiration is not None
                        and bardic_inspiration.get("mode") == "defense"
                        and current_target.id == target.id
                    ):
                        effective_armor_class += int(bardic_inspiration["value"])
                    effective_attack_total = effective_attack_roll + attack_bonus
                    hit = (
                        auto_hit_action
                        or automatic_critical
                        or critical_hit
                        or effective_attack_total >= effective_armor_class
                    )
                    outcome_code = "hit" if hit else "miss"
                    effect_targets[current_target.id] = hit
                    cover_note = (
                        f"（基础 AC {current_target.armor_class}；半掩体 +{cover_bonus}）"
                        if cover_bonus
                        else ""
                    )
                    note = (
                        "特殊技能自动命中："
                        if auto_hit_action
                        else (
                            f"玩家掷骰 {effective_attack_total} 对抗 AC {effective_armor_class}"
                            f"{cover_note}"
                            f"{'（自动暴击）' if automatic_critical else ''}"
                            f"{'（天然 20 暴击）' if critical_hit else ''}："
                        )
                    ) + ("命中" if hit else "未命中")
                target_outcome_codes[current_target.id] = outcome_code
                component_outcomes: list[dict[str, Any]] = []
                rider_results: list[dict[str, Any]] = []
                effective_critical = critical_hit or automatic_critical
                if outcome_code == "hit":
                    eligible_riders = self._eligible_attack_riders(
                        actor,
                        {
                            **action,
                            "attack_roll_mode": attack_roll_mode,
                            "damage_types": [
                                str(component.damage_type).strip().lower()
                                for component in components
                            ],
                        },
                        current_target,
                        special_inputs=special_inputs,
                        critical_hit=effective_critical,
                        used_this_turn=(
                            riders_used_this_turn | riders_applied_this_call
                        ),
                        event_id=f"{idempotency_key}:{current_target.id}",
                        turn_id=rider_turn_key,
                    )
                    for rider in eligible_riders:
                        rider_results.append(rider)
                        if (
                            rider.get("frequency") == "once_per_turn"
                            and rider.get("post_hit_status") is None
                        ):
                            riders_applied_this_call.add(str(rider["rider_id"]))
                rider_results_by_target[current_target.id] = rider_results
                rider_bonus_by_block: dict[str, int] = {}
                if rider_results:
                    rider_bonus_by_block[first_damage_block_id] = sum(
                        int(item.get("total") or 0) for item in rider_results
                    )
                for component in components:
                    rule = next(rule for rule in damage_rules if rule.id == component.block_id)
                    critical_expression = (
                        critical_damage_expression(rule.expression)
                        if effective_critical
                        else None
                    )
                    reported_total = max(
                        0,
                        component.total
                        + (
                            damage_bonus
                            + (
                                int(bardic_inspiration["value"])
                                if (
                                    bardic_inspiration is not None
                                    and bardic_inspiration.get("mode") == "offense"
                                )
                                else 0
                            )
                            if component.block_id == first_damage_block_id
                            else 0
                        )
                        + rider_bonus_by_block.get(component.block_id, 0),
                    )
                    if saving_throw_action:
                        assert save is not None
                        amount = (
                            reported_total // 2
                            if save["success"] and save_on_success == "half"
                            else reported_total
                            if save["success"] and save_on_success == "full"
                            else 0
                            if save["success"]
                            else reported_total
                        )
                    else:
                        amount = reported_total if outcome_code == "hit" else 0
                    component_outcomes.append(
                        {
                            "block_id": component.block_id,
                            "damage_type": component.damage_type,
                            "damage_expression": rule.expression,
                            "reported_total": component.total,
                            "adjusted_total": reported_total,
                            "damage_total": amount,
                            "shared_roll": rule.shared_roll,
                            "critical_hit": effective_critical,
                            **(
                                {"critical_damage_expression": critical_expression}
                                if critical_expression is not None
                                else {}
                            ),
                        }
                    )
                    damage_specs.append(
                        {
                            "target_id": current_target.id,
                            "target_version": current_target.version,
                            "block_id": component.block_id,
                            "damage_type": component.damage_type,
                            "damage_tags": list(rule.damage_tags),
                            "amount": amount,
                            "critical_hit": effective_critical,
                            "note": (
                            f"{note}；伤害段 {component.block_id} "
                                f"({component.damage_type}) 报告 {reported_total}，结算 {amount}"
                                + (
                                    f"；暴击伤害骰应为 {critical_expression}"
                                    if critical_expression is not None
                                    else ""
                                )
                                + (
                                    "；附伤："
                                    + "、".join(
                                        f"{item['source']} {item['expression']} +{item['total']}"
                                        for item in rider_results
                                        if item.get("total")
                                    )
                                    if component.block_id == first_damage_block_id
                                    and rider_results
                                    else ""
                                )
                            ),
                        }
                    )
                target_outcomes.append(
                    {
                        "target_combatant_id": current_target.id,
                        "save": save,
                        "attack_roll_mode": attack_roll_mode if not saving_throw_action else None,
                        "reported_attack_rolls": attack_rolls if not saving_throw_action else [],
                        "attack_roll_bonus": (
                            {
                                "source": bardic_inspiration["source"],
                                "die": bardic_inspiration["die"],
                                "value": bardic_inspiration["value"],
                            }
                            if bardic_inspiration is not None and not saving_throw_action
                            else None
                        ),
                        "combat_inspiration_mode": (
                            bardic_inspiration.get("mode")
                            if bardic_inspiration is not None
                            and bardic_inspiration.get("mode") in {"defense", "offense"}
                            else None
                        ),
                        "effective_attack_roll": (
                            effective_attack_roll if not saving_throw_action else None
                        ),
                        "automatic_critical": (
                            automatic_critical if not saving_throw_action else False
                        ),
                        "save_outcome": ("success" if outcome_code == "save_success" else "failure")
                        if saving_throw_action
                        else None,
                        "attack_outcome": outcome_code if not saving_throw_action else None,
                        "damage_total": sum(item["damage_total"] for item in component_outcomes),
                        "damage_components": component_outcomes,
                        "attack_riders": rider_results,
                        "effect_applied": effect_targets[current_target.id],
                    }
                )

        divine_smite_riders = [
            rider
            for riders in rider_results_by_target.values()
            for rider in riders
            if rider.get("rider_id") == "divine_smite:bonus_damage"
        ]
        if len(divine_smite_riders) > 1:
            raise ValueError("一次攻击只能使用一次圣武斩")
        if divine_smite_riders:
            divine_smite = divine_smite_riders[0]
            resource_key = str(divine_smite.get("resource_key") or "")
            resource = character.resources.get(resource_key)
            current = int(resource.get("current") or 0) if isinstance(resource, dict) else 0
            if current < int(divine_smite.get("resource_cost") or 1):
                raise ValueError(f"对应法术位不足：{resource_key}")

        commands: list[tuple[CombatActionCommand, str]] = []
        target_versions = {item.id: item.version for item in requested_targets}
        action_damage_tags = [
            str(value)
            for value in action.get("damage_tags", [])
            if isinstance(value, str)
        ] if isinstance(action.get("damage_tags"), list) else []

        # One attack/spell against one target is one damage event, even when
        # its rule plan contains several independently resisted segments.  The
        # old path emitted one CombatAction per segment.  That made a single
        # compound hit apply 0-HP death-save failures, concentration checks,
        # and damage-triggered effect expiry once per segment.  Keep every
        # segment typed, but submit them together so the combat engine can
        # apply the event lifecycle exactly once.
        grouped_specs = [
            [spec for spec in damage_specs if spec["target_id"] == current_target.id]
            for current_target in requested_targets
        ]
        for index, target_specs in enumerate(grouped_specs):
            if not target_specs:
                continue
            target_id = str(target_specs[0]["target_id"])
            target_version = target_versions[target_id]
            components = [
                {
                    "amount": int(spec["amount"]),
                    "damage_type": str(spec["damage_type"]),
                    "damage_tags": list(dict.fromkeys([
                        *action_damage_tags,
                        *[
                            str(tag)
                            for tag in spec.get("damage_tags", [])
                            if str(tag).strip()
                        ],
                    ])),
                }
                for spec in target_specs
            ]
            total_amount = sum(int(component["amount"]) for component in components)
            critical = any(bool(spec.get("critical_hit")) for spec in target_specs)
            command = CombatActionCommand(
                action_type="damage",
                target_combatant_id=target_id,
                target_version=target_version,
                actor_combatant_id=actor.id if index == 0 else None,
                actor_version=actor.version if index == 0 else None,
                action_cost=cost if index == 0 else "none",
                action_name=action_name,
                resolution_note="；".join(str(spec["note"]) for spec in target_specs),
                amount=total_amount,
                damage_type=(
                    str(components[0]["damage_type"])
                    if len(components) == 1
                    else "mixed"
                ),
                damage_components=components if len(components) > 1 else [],
                critical_hit=critical and not saving_throw_action,
                is_attack=not saving_throw_action and not auto_hit_action,
                attack_ability=(
                    str(action.get("attack_ability") or action.get("ability") or "").strip()
                    or None
                ),
                is_weapon_attack=bool(
                    action.get("is_weapon_attack") is True
                    or "武器攻击" in str(action.get("description") or "")
                    or "近战攻击" in str(action.get("name") or "")
                ),
                is_unarmed_attack=bool(action.get("is_unarmed_attack") is True),
                is_spell_attack=bool(
                    not saving_throw_action
                    and not auto_hit_action
                    and (
                        action.get("is_spell_attack") is True
                        or action.get("is_spell") is True
                        or action.get("kind") == "spell"
                        or action.get("spell_level") is not None
                    )
                ),
                is_sorcerer_spell=bool(
                    not saving_throw_action
                    and not auto_hit_action
                    and str(
                        action.get("spellcasting_class")
                        or action.get("class_name")
                        or (character.class_name if actor.entity_type == "character" else "")
                    ).strip().lower()
                    in {"术士", "sorcerer"}
                ),
                attack_roll_total=(
                    int(
                        next(
                            outcome["effective_attack_roll"]
                            for outcome in target_outcomes
                            if outcome["target_combatant_id"] == target_id
                        )
                    )
                    if not saving_throw_action and not auto_hit_action
                    else None
                ),
                attack_roll_mode=(
                    attack_roll_mode
                    if not saving_throw_action and not auto_hit_action
                    else None
                ),
                damage_tags=action_damage_tags,
                resource_key=(
                    str(action.get("resource_key") or "").strip() or None
                    if index == 0 and action.get("resolution_kind") == "weapon_attack"
                    else None
                ),
                resource_cost=(
                    int(action.get("resource_cost") or 0)
                    if index == 0 and action.get("resolution_kind") == "weapon_attack"
                    else 0
                ),
                reaction_trigger=reaction_trigger.strip()
                if cost == "reaction" and index == 0
                else None,
            )
            command_key = (
                idempotency_key
                if index == 0
                else f"{idempotency_key}:damage:{target_id}"
            )
            commands.append((command, command_key))
            target_versions[target_id] = target_version + 1
        results = self.combat.confirm_action_batch(
            principal.campaign_id,
            combat_id,
            commands,
        )
        # A post-hit Eldritch Strike-style rider is source-bound and applies
        # only to the source's next spell save.  Player-room spell saves are
        # resolved in this service rather than through CombatEngine's prompt
        # endpoint, so consume the persisted one-shot effect only after the
        # authoritative damage action has committed.
        is_spell_action = bool(
            action.get("kind") == "spell"
            or action.get("action_type") == "spellcasting"
            or int(action.get("spell_level") or 0) > 0
        )
        if saving_throw_action and is_spell_action:
            for outcome in target_outcomes:
                raw_save = outcome.get("save")
                target_combatant_id = outcome.get("target_combatant_id")
                if not isinstance(raw_save, dict) or not isinstance(target_combatant_id, str):
                    continue
                consumed_ids = self.combat.consume_post_hit_save_modifiers(
                    principal.campaign_id,
                    combat_id,
                    target_id=target_combatant_id,
                    source_combatant_id=actor.id,
                )
                if consumed_ids:
                    applied = list(raw_save.get("applied_defenses") or [])
                    applied.extend(f"post_hit_save:{effect_id}" for effect_id in consumed_ids)
                    raw_save["applied_defenses"] = applied
                    raw_save["consumed_post_hit_effect_ids"] = consumed_ids
        bardic_inspiration_consumed = None
        if bardic_inspiration is not None:
            inspiration_owner_id = (
                target.id
                if bardic_inspiration.get("mode") == "defense"
                else actor.id
            )
            bardic_inspiration_consumed = self._consume_bardic_inspiration_after_attack(
                inspiration_owner_id,
                bardic_inspiration,
                idempotency_key,
            )
        self._mark_attack_rider_usage(
            self.engine,
            actor.id,
            rider_turn_key,
            riders_applied_this_call,
        )
        if divine_smite_riders:
            divine_smite = divine_smite_riders[0]
            resource_key = str(divine_smite.get("resource_key") or "")
            self._spend_character_resource(
                principal.character_id,
                resource_key,
                int(divine_smite.get("resource_cost") or 1),
            )
        generic_rider_spends: dict[str, int] = {}
        for rider in (
            item
            for values in rider_results_by_target.values()
            for item in values
            if isinstance(item, dict)
        ):
            for spend in rider.get("resource_spends") or ():
                if not isinstance(spend, dict):
                    continue
                key = str(spend.get("key") or "").strip()
                amount = int(spend.get("amount") or 0)
                if key and amount > 0:
                    generic_rider_spends[key] = generic_rider_spends.get(key, 0) + amount
        for key, amount in generic_rider_spends.items():
            self._spend_character_resource(principal.character_id, key, amount)
        compiled_effects = self._apply_compiled_combat_blocks(
            principal,
            combat_id,
            actor.id,
            action,
            [item.id for item in requested_targets],
            effect_targets,
            idempotency_key,
            special_inputs,
            target_outcome_codes,
        )
        post_hit_rider_requests = self._persist_post_hit_rider_requests(
            principal,
            combat_id=combat_id,
            actor_id=actor.id,
            rider_results_by_target=rider_results_by_target,
            attack_idempotency_key=idempotency_key,
        )
        if not primary_resource_consumed_by_combat:
            self._spend_character_resource(
                principal.character_id,
                resource_key,
                resource_cost,
            )
        turn_advance = (
            self._advance_player_room_turn(
                principal,
                combat_id,
                f"{idempotency_key}:advance",
                require_non_character=False,
            )
            if end_turn_after and not post_hit_rider_requests
            else None
        )
        return {
            "action_name": action_name,
            "target_count": len(requested_targets),
            "results": results,
            "target_resolution": target_resolution,
            "target_outcomes": target_outcomes,
            "attack_riders": [
                rider
                for values in rider_results_by_target.values()
                for rider in values
            ],
            "post_hit_rider_requests": post_hit_rider_requests,
            "bardic_inspiration_consumed": bardic_inspiration_consumed,
            "compiled_effects": compiled_effects,
            "turn_advance": turn_advance,
        }

    def resolve_post_hit_rider(
        self,
        principal: PlayerPrincipal,
        request_id: str,
        expected_version: int,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        return self.combat.resolve_post_hit_rider_request(
            principal.campaign_id,
            request_id,
            expected_version=expected_version,
            inputs=inputs,
            character_id=principal.character_id,
        )

    def cast(
        self,
        principal: PlayerPrincipal,
        target_id: str,
        target_ids: list[str],
        action_name: str,
        slot_level: int | None,
        healing_total: int,
        end_turn_after: bool,
        idempotency_key: str,
        special_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve a typed non-attack combat spell for the player.

        This endpoint handles friendly effects plus destination/template-sensitive
        special blocks. Damage/save/forced-movement spells continue through
        ``attack`` so their enemy targeting and save geometry cannot be bypassed.
        """

        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        special_inputs = dict(special_inputs or {})
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            fighters = session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
                .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
            ).all()
            active = fighters[combat.current_turn_index] if fighters else None
            character = session.get(Character, principal.character_id)
            actor = self._controlled_actor(fighters, active, principal.character_id)
            if actor is None or character is None:
                raise ValueError("当前不是你的可控单位回合")
            action = (
                self._action_data(session, character, action_name)
                if actor.entity_type == "character"
                else self._companion_action_data(actor, action_name)
            )
            if slot_level is not None:
                base_level = int(action.get("spell_level") or 0)
                if base_level <= 0 or slot_level < base_level:
                    raise ValueError("该动作不是可升环法术，或施法环阶低于法术本环")
                action = upcast_spell_action(action, slot_level)
            raw_plan = action.get("rule_plan")
            blocks = (
                [block for block in raw_plan.get("blocks", []) if isinstance(block, dict)]
                if isinstance(raw_plan, dict)
                else []
            )
            selected_choice_ids = self._selected_choice_block_ids(blocks, special_inputs)
            choice_child_ids = {
                str(child_id)
                for choice in blocks
                if choice.get("kind") == "choice"
                for option in (
                    choice.get("options") if isinstance(choice.get("options"), list) else []
                )
                if isinstance(option, dict)
                for child_id in (
                    option.get("block_ids") if isinstance(option.get("block_ids"), list) else []
                )
                if isinstance(child_id, str) and child_id
            }
            area_child_ids = {
                str(child_id)
                for area in blocks
                if area.get("kind") == "area_effect"
                for child_id in (
                    area.get("effect_block_ids")
                    if isinstance(area.get("effect_block_ids"), list)
                    else []
                )
                if isinstance(child_id, str) and child_id
            }

            def direct_block(block: dict[str, Any]) -> bool:
                block_id = str(block.get("id") or "")
                return block_id not in area_child_ids and (
                    block_id not in choice_child_ids or block_id in selected_choice_ids
                )

            supported_kinds = {
                "heal",
                "condition",
                "modifier",
                "defense",
                "repeat",
                "teleport",
                "transformation",
                "creation",
                "dispel",
                "area_effect",
                "choice",
            }
            if not any(str(block.get("kind") or "") in supported_kinds for block in blocks):
                raise ValueError("该法术没有可自动执行的友方战斗效果，请由 DM 裁定")
            if any(
                str(block.get("kind") or "") in {"damage", "save", "move", "summon"}
                and direct_block(block)
                for block in blocks
            ):
                raise ValueError("该法术同时包含敌对目标或位移效果，请使用攻击/范围法术入口")
            direct_heal_blocks = [
                block
                for block in blocks
                if str(block.get("kind") or "") == "heal" and direct_block(block)
            ]
            has_heal = bool(direct_heal_blocks)
            has_temporary_hp = any(
                block.get("temporary_hp") is True for block in direct_heal_blocks
            )
            has_ordinary_heal = any(
                block.get("temporary_hp") is not True for block in direct_heal_blocks
            )
            if has_temporary_hp and has_ordinary_heal:
                raise ValueError(
                    "同时恢复生命和给予临时生命的法术需要按积木分别提交总值，请由 DM 裁定"
                )
            if has_heal and healing_total <= 0:
                raise ValueError("请先掷治疗骰，并填写治疗骰最终总值")
            has_area_effect = any(block.get("kind") == "area_effect" for block in blocks)

            requested_ids = list(dict.fromkeys(target_ids or [target_id]))
            if target_id not in requested_ids:
                requested_ids.insert(0, target_id)
            requested_targets = [item for item in fighters if item.id in requested_ids]
            if len(requested_targets) != len(requested_ids):
                raise ValueError("目标包含不存在或不在当前战斗的单位")
            has_dispel = any(str(block.get("kind") or "") == "dispel" for block in blocks)
            if has_area_effect and any(item.id != actor.id for item in requested_targets):
                raise ValueError(
                    "持续区域不以生物为目标；请以施法者自身作为确认目标并在 areas 中选择原点"
                )
            if (
                not has_dispel
                and not has_area_effect
                and any(
                    self._combatant_faction(item) != self._combatant_faction(actor)
                    for item in requested_targets
                )
            ):
                raise ValueError("战斗增益和治疗只能选择友方单位")

            target_block = next(
                (block for block in blocks if str(block.get("kind") or "") == "target"),
                {},
            )
            target_mode = str(target_block.get("mode") or "")
            if target_mode == "self" and any(item.id != actor.id for item in requested_targets):
                raise ValueError("该法术只能以施法者自身为目标")
            range_value = target_block.get("range_ft")
            range_numbers = [
                int(value)
                for value in re.findall(
                    r"(\d+)\s*(?:尺|英尺|ft\.?|feet|foot)",
                    str(action.get("range") or ""),
                    flags=re.IGNORECASE,
                )
            ]
            maximum_range = (
                int(range_value)
                if isinstance(range_value, int) and range_value >= 0
                else range_numbers[0]
                if range_numbers
                else None
            )
            if maximum_range is None and any(item.id != actor.id for item in requested_targets):
                raise ValueError("该法术的友方目标距离未明确，请由 DM 裁定")
            actor_pos = actor.snapshot_json.get("grid_position")
            if maximum_range is not None and maximum_range > 0:
                if not isinstance(actor_pos, dict):
                    raise ValueError("施法者尚未设置战斗地图位置")
                scene_id = combat.scene_id or (room.current_scene_id if room else None)
                grid = (
                    session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))
                    if scene_id
                    else None
                )
                cell_size = grid.cell_size_ft if grid is not None else 5
                actor_point = (int(actor_pos["row"]), int(actor_pos["col"]))
                for target in requested_targets:
                    target_pos = target.snapshot_json.get("grid_position")
                    if not isinstance(target_pos, dict):
                        raise ValueError("友方目标尚未设置战斗地图位置")
                    distance = grid_distance_ft(
                        actor_point,
                        (int(target_pos["row"]), int(target_pos["col"])),
                        cell_size_ft=cell_size,
                    )
                    if distance > maximum_range:
                        raise ValueError(f"{target.display_name}超出该法术的合法距离")

            cost_text = str(action.get("cost") or "动作")
            cost: Literal["action", "bonus_action", "reaction", "none"] = (
                "bonus_action"
                if "附赠" in cost_text
                else "reaction"
                if "反应" in cost_text
                else "none"
                if "无" in cost_text
                else "action"
            )
            reaction_trigger = str(special_inputs.get("reaction_trigger") or "").strip()
            if cost == "reaction":
                reaction_trigger = self._reaction_trigger_for_support_cast(
                    action,
                    blocks,
                    reaction_trigger,
                )
            resource_key = str(action.get("resource_key") or "")
            resource_cost = int(action.get("resource_cost") or 0)
            if actor.entity_type != "character":
                resource_key = ""
                resource_cost = 0
            if resource_key and resource_cost:
                resource = (character.resources or {}).get(resource_key)
                current = int(resource.get("current") or 0) if isinstance(resource, dict) else 0
                if current < resource_cost:
                    raise ValueError("对应法术位或资源不足")
            combat_id = combat.id
            actor_id = actor.id

        commands: list[tuple[CombatActionCommand, str]] = []
        for index, target in enumerate(requested_targets):
            command = CombatActionCommand(
                action_type="heal",
                target_combatant_id=target.id,
                target_version=target.version,
                actor_combatant_id=actor_id if index == 0 else None,
                actor_version=actor.version if index == 0 else None,
                action_cost=cost if index == 0 else "none",
                action_name=action_name,
                resolution_note=(
                    f"玩家施放友方效果；{target.display_name}"
                    + (
                        f"获得 {healing_total} 点临时生命"
                        if has_temporary_hp
                        else f"恢复 {healing_total} 点生命"
                        if has_ordinary_heal
                        else "获得规则积木效果"
                    )
                ),
                amount=healing_total if has_ordinary_heal else 0,
                reaction_trigger=reaction_trigger if cost == "reaction" else None,
            )
            commands.append(
                (
                    command,
                    idempotency_key if index == 0 else f"{idempotency_key}:{index}",
                )
            )
        results = self.combat.confirm_action_batch(
            principal.campaign_id,
            combat_id,
            commands,
        )
        temporary_hp_results = (
            self._write_temporary_hp(action_results=results, amount=healing_total)
            if has_temporary_hp
            else []
        )
        compiled_effects = self._apply_compiled_combat_blocks(
            principal,
            combat_id,
            actor_id,
            action,
            [item.id for item in requested_targets],
            {item.id: True for item in requested_targets},
            idempotency_key,
            special_inputs,
            {item.id: "always" for item in requested_targets},
        )
        self._spend_character_resource(
            principal.character_id,
            resource_key,
            resource_cost,
        )
        turn_advance = (
            self._advance_player_room_turn(
                principal,
                combat_id,
                f"{idempotency_key}:advance",
                require_non_character=False,
            )
            if end_turn_after
            else None
        )
        return {
            "action_name": action_name,
            "target_count": len(results),
            "results": results,
            "temporary_hp": temporary_hp_results,
            "resource_spend": {
                "resource_key": resource_key or None,
                "amount": resource_cost,
            },
            "compiled_effects": compiled_effects,
            "turn_advance": turn_advance,
        }

    def resolve_pre_damage_reaction(
        self,
        principal: PlayerPrincipal,
        window_id: str,
        window_version: int,
        decision: Literal["accept", "reject"],
        feature_id: str | None,
        reduction_roll: int | None,
        request_id: str,
    ) -> dict[str, Any]:
        """Resolve only a pre-damage window belonging to this player."""

        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            window = session.get(CombatAction, window_id)
            fighters = self._ordered_fighters(session, combat.id)
            if (
                window is None
                or window.combat_id != combat.id
                or window.actor_combatant_id is None
                or not any(
                    item.id == window.actor_combatant_id
                    and self._is_player_controlled(item, principal.character_id)
                    for item in fighters
                )
            ):
                raise ValueError("该伤害前反应不属于你的可控单位")
            combat_id = combat.id
        return self.combat.resolve_pre_damage_reaction(
            principal.campaign_id,
            combat_id,
            CombatPreDamageReactionCommand(
                reaction_window_id=window_id,
                reaction_window_version=window_version,
                decision=decision,
                feature_id=feature_id,
                reduction_roll=reduction_roll,
            ),
            idempotency_key=request_id,
        )

    def resolve_deflect_redirect(
        self,
        principal: PlayerPrincipal,
        window_id: str,
        window_version: int,
        decision: Literal["accept", "reject"],
        target_id: str | None,
        target_version: int | None,
        saving_throw_roll: int | None,
        damage_rolls: list[int],
        request_id: str,
    ) -> dict[str, Any]:
        """Resolve a zero-damage Deflect Attacks branch for the owning player."""

        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            window = session.get(CombatAction, window_id)
            fighters = self._ordered_fighters(session, combat.id)
            if (
                window is None
                or window.combat_id != combat.id
                or window.actor_combatant_id is None
                or not any(
                    item.id == window.actor_combatant_id
                    and self._is_player_controlled(item, principal.character_id)
                    for item in fighters
                )
            ):
                raise ValueError("该偏转攻击反击不属于你的可控单位")
            combat_id = combat.id
        return self.combat.resolve_deflect_redirect(
            principal.campaign_id,
            combat_id,
            CombatDeflectRedirectCommand(
                redirect_window_id=window_id,
                redirect_window_version=window_version,
                decision=decision,
                target_combatant_id=target_id,
                target_version=target_version,
                saving_throw_roll=saving_throw_roll,
                damage_rolls=damage_rolls,
            ),
            idempotency_key=request_id,
        )

    def feature_action(
        self,
        principal: PlayerPrincipal,
        feature_id: str,
        target_id: str | None,
        selected_action: str | None,
        outcome: str | None,
        adjudication_note: str | None,
        healing_total: int | None,
        condition_to_cure: str | None,
        condition_to_remove: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Submit a compiled class feature from the player's active unit."""

        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            fighters = self._ordered_fighters(session, combat.id)
            active = (
                fighters[combat.current_turn_index]
                if fighters and combat.current_turn_index < len(fighters)
                else None
            )
            actor = self._controlled_actor(fighters, active, principal.character_id)
            if actor is None:
                raise ValueError("现在还没有轮到你的角色或你的召唤单位")
            target = next(
                (item for item in fighters if item.id == target_id),
                actor,
            )
            if target_id is not None and target.id != target_id:
                raise ValueError("职业特性目标不在当前战斗")
            command = CombatFeatureActionCommand(
                actor_combatant_id=actor.id,
                actor_version=actor.version,
                feature_id=feature_id,
                selected_action=selected_action,
                outcome=outcome,
                adjudication_note=adjudication_note,
                healing_total=healing_total,
                condition_to_cure=condition_to_cure,
                condition_to_remove=condition_to_remove,
                target_combatant_id=target.id,
                target_version=target.version,
            )
            campaign_id = combat.campaign_id
            combat_id = combat.id
        return self.combat.confirm_feature_action(
            campaign_id,
            combat_id,
            command,
            idempotency_key=idempotency_key,
        )

    def confirm_roll(
        self,
        principal: PlayerPrincipal,
        action_id: str,
        action_version: int,
        roll_total: int,
        bardic_inspiration_total: int | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            action = session.get(CombatAction, action_id)
            fighters = self._ordered_fighters(session, combat.id) if combat else []
            controlled_ids = {
                item.id
                for item in fighters
                if self._is_player_controlled(item, principal.character_id)
            }
            if (
                combat is None
                or combat.status != "active"
                or action is None
                or action.combat_id != combat.id
                or not controlled_ids.intersection(action.target_combatant_ids)
            ):
                raise ValueError("该骰子请求不属于你的当前角色")
            combat_id = combat.id
        roll_result = self.combat.confirm_player_roll(
            principal.campaign_id,
            combat_id,
            action_id,
            PlayerRollResolutionCommand(
                action_version=action_version,
                roll_total=roll_total,
                bardic_inspiration_total=bardic_inspiration_total,
                dm_note="由局域网玩家提交",
            ),
            idempotency_key=idempotency_key,
        )
        follow_up = roll_result.get("resolution", {}).get("follow_up_damage")
        damage_result: dict[str, Any] | None = None
        if isinstance(follow_up, dict):
            damage_key = hashlib.sha256(f"{idempotency_key}:damage".encode()).hexdigest()
            damage_result = self.combat.confirm(
                principal.campaign_id,
                combat_id,
                CombatActionCommand.model_validate(follow_up),
                idempotency_key=damage_key,
            )
        turn_advance = self._advance_player_room_turn(
            principal,
            combat_id,
            f"{idempotency_key}:advance",
            require_non_character=True,
        )
        return {
            "roll": roll_result,
            "damage": damage_result,
            "turn_advance": turn_advance,
        }

    def get_player_death_save(self, principal: PlayerPrincipal) -> dict[str, Any]:
        """Expose only the bound character's death-save track to the player."""

        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            fighters = self._ordered_fighters(session, combat.id)
            target = next(
                (
                    item
                    for item in fighters
                    if item.entity_type == "character"
                    and item.entity_id == principal.character_id
                    and self._is_player_controlled(item, principal.character_id)
                ),
                None,
            )
            if target is None:
                raise ValueError("当前角色没有对应的战斗单位")
            death_save = session.scalar(
                select(DeathSave).where(DeathSave.combatant_id == target.id)
            )
            return (
                serialize(death_save)
                if death_save is not None
                else {
                    "combatant_id": target.id,
                    "successes": 0,
                    "failures": 0,
                    "stable": False,
                    "dead": False,
                    "pending_death_confirmation": False,
                    "last_roll": None,
                    "version": 1,
                }
            )

    def submit_player_death_save(
        self,
        principal: PlayerPrincipal,
        target_version: int,
        roll: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Submit a death save for the bound character and pass the turn onward."""

        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            fighters = self._ordered_fighters(session, combat.id)
            active = (
                fighters[combat.current_turn_index]
                if fighters and combat.current_turn_index < len(fighters)
                else None
            )
            target = next(
                (
                    item
                    for item in fighters
                    if item.entity_type == "character"
                    and item.entity_id == principal.character_id
                    and self._is_player_controlled(item, principal.character_id)
                ),
                None,
            )
            if target is None:
                raise ValueError("当前角色没有对应的战斗单位")
            if active is None or active.id != target.id:
                raise ValueError("只有当前角色回合才能进行死亡豁免")
            if target.version != target_version:
                raise VersionConflict("combatant", target.id, target_version, target.version)
            combat_id = combat.id
            campaign_id = combat.campaign_id
        result = self.combat.confirm_death_save(
            campaign_id,
            combat_id,
            target.id,
            DeathSaveCommand(target_version=target_version, roll=roll),
            idempotency_key=idempotency_key,
        )
        death_save = result.get("death_save")
        turn_advance = None
        if isinstance(death_save, dict) and not (
            death_save.get("dead") or death_save.get("pending_death_confirmation")
        ):
            with Session(self.engine) as session:
                combat_row = session.get(Combat, combat_id)
                if combat_row is not None and combat_row.status == "active":
                    combat_version = combat_row.version
                else:
                    combat_version = None
            if combat_version is not None:
                turn_advance = self.combat.advance_turn(
                    principal.campaign_id,
                    combat_id,
                    TurnAdvanceCommand(combat_version=combat_version),
                    idempotency_key=f"{idempotency_key}:advance",
                )
        return {**result, "turn_advance": turn_advance}

    def _advance_player_room_turn(
        self,
        principal: PlayerPrincipal,
        combat_id: str,
        idempotency_key: str,
        *,
        require_non_character: bool,
    ) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            combat = session.get(Combat, combat_id)
            if combat is None or combat.status != "active":
                return None
            fighters = session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
                .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
            ).all()
            active = (
                fighters[combat.current_turn_index]
                if fighters and combat.current_turn_index < len(fighters)
                else None
            )
            if active is None:
                return None
            active_is_player_controlled = self._is_player_controlled(active, principal.character_id)
            if require_non_character and active_is_player_controlled:
                return None
            if not require_non_character and (not active_is_player_controlled):
                return None
            unresolved = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat.id,
                    CombatAction.status == "previewed",
                    CombatAction.action_type.in_(
                        ["player_roll_prompt", "concentration_check_prompt"]
                    ),
                )
            )
            if unresolved is not None:
                return None
            combat_version = combat.version
        return self.combat.advance_turn(
            principal.campaign_id,
            combat_id,
            TurnAdvanceCommand(combat_version=combat_version),
            idempotency_key=idempotency_key,
        )

    def end_turn(
        self, principal: PlayerPrincipal, combat_version: int, idempotency_key: str
    ) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        with Session(self.engine) as session:
            room = session.get(PlayerRoom, principal.room_id)
            combat = (
                session.get(Combat, room.current_combat_id)
                if room and room.current_combat_id
                else None
            )
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            fighters = session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
                .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
            ).all()
            active = fighters[combat.current_turn_index] if fighters else None
            if active is None or not self._is_player_controlled(active, principal.character_id):
                raise ValueError("现在还没有轮到你的角色或你的召唤单位")
            combat_id = combat.id
        return self.combat.advance_turn(
            principal.campaign_id,
            combat_id,
            TurnAdvanceCommand(combat_version=combat_version),
            idempotency_key=idempotency_key,
        )
