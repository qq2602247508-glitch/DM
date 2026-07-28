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
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.schemas import (
    CombatActionCommand,
    PlayerRollResolutionCommand,
    TurnAdvanceCommand,
)
from dnd_dm_assistant.application.rule_block_compiler import (
    compile_rule_blocks_dict,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.equipment_rules import equipment_profile
from dnd_dm_assistant.domain.exploration import (
    grid_distance_ft,
    line_of_sight,
    movement_cost_ft,
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
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    Campaign,
    Character,
    Combat,
    CombatAction,
    Combatant,
    EquipmentInstance,
    MonsterInstance,
    PlayerActionRequest,
    PlayerRoom,
    PlayerSession,
    Scene,
    SceneGrid,
    SceneObject,
    SceneToken,
)
from dnd_dm_assistant.infrastructure.database.player_service import PlayerService
from dnd_dm_assistant.infrastructure.database.spell_economy_service import SpellEconomyService

ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
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
    def _active(room: PlayerRoom) -> None:
        if room.status != "active" or _aware(room.expires_at) <= _now():
            raise ValueError("player room is closed or expired")

    def open_room(self, campaign_id: str, *, hours: int = 12) -> dict[str, Any]:
        join_code = _code()
        join_code_salt = secrets.token_hex(16)
        now = _now()
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            room = session.scalar(select(PlayerRoom).where(PlayerRoom.campaign_id == campaign_id))
            if room is None:
                room = PlayerRoom(
                    campaign_id=campaign_id,
                    join_code_salt=join_code_salt,
                    join_code_hash=_code_digest(join_code, join_code_salt),
                    join_code_hint=join_code[-2:],
                    status="active",
                    expires_at=now + timedelta(hours=hours),
                )
                session.add(room)
            else:
                room.join_code_salt = join_code_salt
                room.join_code_hash = _code_digest(join_code, join_code_salt)
                room.join_code_hint = join_code[-2:]
                room.status = "active"
                room.expires_at = now + timedelta(hours=hours)
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
        self, campaign_id: str, scene_id: str | None, combat_id: str | None
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            room = self._room(session, campaign_id)
            if scene_id is not None:
                scene = session.get(Scene, scene_id)
                if scene is None or scene.campaign_id != campaign_id:
                    raise StateNotFoundError("scene not found")
            if combat_id is not None:
                combat = session.get(Combat, combat_id)
                if combat is None or combat.campaign_id != campaign_id:
                    raise StateNotFoundError("combat not found")
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

    def preview_equipment(
        self, principal: PlayerPrincipal, data: dict[str, Any]
    ) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        character = self.player.character_view(
            principal.campaign_id, principal.character_id
        )
        safe = {
            **data,
            "character_id": principal.character_id,
            "character_version": character["version"],
            "amount": 1,
            "preview_token": None,
            "idempotency_key": None,
        }
        return self.economy.equipment_preview(principal.campaign_id, safe)

    def confirm_equipment(
        self, principal: PlayerPrincipal, data: dict[str, Any]
    ) -> dict[str, Any]:
        if principal.character_id is None:
            raise ValueError("请先绑定角色")
        character = self.player.character_view(
            principal.campaign_id, principal.character_id
        )
        safe = {
            **data,
            "character_id": principal.character_id,
            "character_version": character["version"],
            "amount": 1,
        }
        return self.economy.equipment_confirm(principal.campaign_id, safe)

    def create_character(self, principal: PlayerPrincipal, data: dict[str, Any]) -> dict[str, Any]:
        race = str(data["race"])
        class_name = str(data["class_name"])
        background = str(data["background"])
        scores = {key: int(value) for key, value in dict(data["ability_scores"]).items()}
        if (
            race not in CORE_SPECIES
            or class_name not in CORE_CLASSES
            or background not in CORE_BACKGROUNDS
        ):
            raise ValueError("请选择 D&D 5e 2024 核心种族、职业与背景")
        if sorted(scores.values()) != [8, 10, 12, 13, 14, 15] or set(scores) != {
            "strength",
            "dexterity",
            "constitution",
            "intelligence",
            "wisdom",
            "charisma",
        }:
            raise ValueError("属性必须使用标准数组 15/14/13/12/10/8 且每项一次")
        con_mod = (scores["constitution"] - 10) // 2
        max_hp = max(1, CLASS_HIT_DIE[class_name] + con_mod)
        species_rule = SPECIES_RULES[race]
        background_rule = BACKGROUND_RULES[background]
        class_rule = CLASS_RULES[class_name]
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
            *list(data.get("equipment") or []),
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
                dict(equipped_armor["metadata_json"])["equipment_profile"].get(
                    "armor_type"
                )
                or ""
            )
            base_ac = int(equipped_armor["armor_class"])
            armor_class = (
                base_ac + dexterity_modifier
                if armor_type == "light"
                else base_ac + min(2, dexterity_modifier)
                if armor_type == "medium"
                else base_ac
            )
        if any(
            asset["equipped"] and asset["category"] == "shield"
            for asset in starter_assets
        ):
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
                proficiencies=[
                    *list(class_rule.get("proficiencies") or []),
                    *[f"{ability}豁免" for ability in list(class_rule.get("saves") or [])],
                ],
                skills={skill: {"proficient": True} for skill in sorted(skill_names)},
                features=[
                    *list(species_rule.get("features") or []),
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

    def snapshot(self, principal: PlayerPrincipal) -> dict[str, Any]:
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
                public["scene"] = self._safe_scene(session, scene)
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
                "character": self.player.character_view(
                    principal.campaign_id, principal.character_id
                )
                if principal.character_id
                else None,
                "available_characters": available_characters,
                "table": {
                    "scene": public.get("scene"),
                    "handouts": public.get("handouts", []),
                    "shared_log": public.get("shared_log", []),
                    "noncombat": self._noncombat_snapshot(session, room, principal),
                },
                "combat": self._combat_snapshot(session, room, principal),
            }

    @staticmethod
    def _safe_scene(session: Session, scene: Scene) -> dict[str, Any]:
        grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene.id))
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
                    "cells": public_cells(grid.layers_json),
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
                for item in tokens
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
                    "interaction": {
                        key: value
                        for key, value in (item.interaction_json or {}).items()
                        if key in {"action", "locked", "tool", "description"}
                    },
                }
                for item in objects
            ],
        }

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
                    "save_ability": raw.get("save_ability"),
                    "save_dc": raw.get("save_dc"),
                    "target_types": (
                        ["self"] if "隐形" in name else ["npc", "monster"] if "命令" in name else
                        ["self", "npc", "monster", "object", "area"]
                    ),
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
        own = next(
            (
                item
                for item in fighters
                if item.entity_type == "character" and item.entity_id == principal.character_id
            ),
            None,
        )
        actions = session.scalars(
            select(CombatAction)
            .where(CombatAction.combat_id == combat.id)
            .order_by(CombatAction.created_at.desc())
            .limit(80)
        ).all()
        fighters_by_id = {item.id: item for item in fighters}
        pending = []
        for action in actions:
            if (
                combat.status != "active"
                or action.status != "previewed"
                or own is None
                or own.id not in action.target_combatant_ids
            ):
                continue
            if action.request_json.get("resolution_type"):
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
                            action.target_combatant_ids[0]
                            if action.target_combatant_ids
                            else None
                        ),
                        "target_name": action.request_json.get("target_name"),
                        "damage_on_success": action.request_json.get(
                            "damage_on_success", 0
                        ),
                        "damage_on_failure": action.request_json.get(
                            "damage_on_failure", 0
                        ),
                        "damage_type": action.request_json.get("damage_type"),
                    }
                )
        return {
            "id": combat.id,
            "version": combat.version,
            "name": combat.name,
            "status": combat.status,
            "round_number": combat.round_number,
            "current_turn_index": combat.current_turn_index,
            "active_combatant_id": active.id if active else None,
            "is_my_turn": own is not None and active is not None and own.id == active.id,
            "own_combatant_id": own.id if own else None,
            "combatants": [self._safe_combatant(item, own) for item in fighters],
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
                    "target_combatant_ids": action.target_combatant_ids,
                    "target_names": [
                        fighters_by_id[target_id].display_name
                        for target_id in action.target_combatant_ids
                        if target_id in fighters_by_id
                    ],
                    "action_name": action.request_json.get("action_name"),
                    "from_position": action.request_json.get("from_position"),
                    "to_position": action.request_json.get("to_position"),
                    "movement_spent_ft": action.request_json.get(
                        "movement_spent_ft"
                    ),
                    "resolution_type": action.request_json.get(
                        "resolution_type"
                    ),
                    "dc": action.request_json.get("dc"),
                    "roll_formula": action.request_json.get("roll_formula"),
                    "damage": action.result_json.get(
                        "adjusted_damage",
                        action.result_json.get("damage"),
                    ),
                    "created_at": action.created_at.isoformat(),
                }
                for action in actions
            ],
            "pending_rolls": pending,
        }

    @staticmethod
    def _safe_combatant(item: Combatant, own: Combatant | None) -> dict[str, Any]:
        is_own = own is not None and item.id == own.id
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
            # The shared battle card exposes deterministic combat statistics
            # needed for assisted play. DM notes and unrevealed narrative
            # identity remain outside this snapshot.
            "armor_class": item.armor_class,
            "hp": item.hp,
            "max_hp": item.max_hp,
            "conditions": item.conditions,
            "speed_ft": item.speed_ft,
            "ability_scores": json_dict(item.snapshot_json.get("ability_scores")),
            "actions": (
                item.snapshot_json.get("actions")
                if isinstance(item.snapshot_json.get("actions"), list)
                else []
            ),
            "damage_resistances": item.damage_resistances,
            "damage_immunities": item.damage_immunities,
        }
        if is_own:
            result.update(
                {
                    "movement_remaining_ft": item.movement_remaining_ft,
                    "action_available": item.action_available,
                    "bonus_action_available": item.bonus_action_available,
                    "reaction_available": item.reaction_available,
                }
            )
        return result

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
        character = self.player.character_view(principal.campaign_id, principal.character_id)
        return self.player.submit_action(
            principal.campaign_id,
            {
                "character_id": principal.character_id,
                "character_version": character["version"],
                "player_key": principal.session_id,
                "action_type": action_type,
                "message": message,
                "payload_json": payload,
                "idempotency_key": idempotency_key,
            },
            request_id,
        )

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
                    desired_state = (
                        "disarmed" if target_object.object_type == "trap" else "open"
                    )
                    plan["proposal"] = {
                        "kind": "object_state",
                        "object_id": target_object.id,
                        "from_state": target_object.state,
                        "to_state": desired_state,
                        "summary": f"成功后将「{target_object.label}」标记为{desired_state}。",
                    }
            elif kind == "spell":
                resource_key = action.get("resource_key")
                resource_cost = int(action.get("resource_cost") or 0)
                if resource_key and resource_cost:
                    resource = (character.resources or {}).get(str(resource_key))
                    current = (
                        int(resource.get("current") or 0)
                        if isinstance(resource, dict)
                        else 0
                    )
                    if current < resource_cost:
                        raise ValueError("对应法术位或资源不足")
                    plan["cost"]["available_before"] = current
                    plan["cost"]["available_after"] = current - resource_cost
                if "命令" in str(action["name"]):
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
                elif "隐形" in str(action["name"]):
                    plan["proposal"] = {
                        "kind": "condition_advice",
                        "condition": "隐形",
                        "concentration": True,
                        "summary": "建议记录目标隐形与施法者专注；具体可见性由 DM 裁定。",
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
            total = raw_roll + modifier
            resolution.update(
                raw_roll=raw_roll,
                total=total,
                success=total >= dc,
                instruction=(
                    f"裸骰 {raw_roll} {modifier:+d} = {total}；"
                    f"DC {dc}，{'成功' if total >= dc else '失败'}。"
                ),
            )
            payload["phase"] = "resolved"
            payload["resolution"] = resolution
            proposal = json_dict(payload.get("proposal"))
            if not total >= dc and proposal.get("kind") == "object_state":
                proposal = {
                    "kind": "narrative",
                    "summary": "检定失败；不改变物体状态，DM 可描述代价、时间或暴露风险。",
                }
            payload["proposal"] = proposal
            item.payload_json = payload
            item.version += 1
            item.updated_at = _now()
            session.flush()
            return serialize(item)

    def move(
        self, principal: PlayerPrincipal, row: int, col: int, combatant_version: int
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
            actor = next(
                (
                    item
                    for item in fighters
                    if item.entity_type == "character" and item.entity_id == principal.character_id
                ),
                None,
            )
            active = fighters[combat.current_turn_index] if fighters else None
            if actor is None or active is None or actor.id != active.id:
                raise ValueError("现在还没有轮到你的角色")
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
            if grid is not None and (row > grid.height or col > grid.width):
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
            cost = movement_cost_ft(path, difficult, cell_size_ft=cell_size)
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
            snapshot["grid_position"] = {"row": row, "col": col}
            actor.snapshot_json = snapshot
            actor.movement_remaining_ft -= cost
            actor.version += 1
            actor.updated_at = _now()
            session.flush()
            return serialize(actor)

    @staticmethod
    def _action_data(character: Character, action_name: str) -> dict[str, Any]:
        for raw in [*character.actions, *character.spells]:
            if isinstance(raw, dict) and str(raw.get("name")) == action_name:
                return raw
        raise ValueError("该动作不在你的角色卡中")

    def attack(
        self,
        principal: PlayerPrincipal,
        target_id: str,
        target_ids: list[str],
        action_name: str,
        attack_total: int,
        damage_total: int,
        end_turn_after: bool,
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
            if combat is None or combat.status != "active":
                raise ValueError("当前没有进行中的战斗")
            fighters = session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
                .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
            ).all()
            actor = next(
                (
                    item
                    for item in fighters
                    if item.entity_type == "character" and item.entity_id == principal.character_id
                ),
                None,
            )
            target = next((item for item in fighters if item.id == target_id), None)
            active = fighters[combat.current_turn_index] if fighters else None
            character = session.get(Character, principal.character_id)
            if (
                actor is None
                or target is None
                or character is None
                or active is None
                or actor.id != active.id
            ):
                raise ValueError("当前角色、目标或回合无效")
            if target.entity_type in {"character", "npc"}:
                raise ValueError("玩家快捷攻击只能选择敌对怪物")
            action = self._action_data(character, action_name)
            range_text = str(action.get("range") or "5尺")
            range_numbers = [int(value) for value in re.findall(r"(\d+)\s*尺", range_text)]
            maximum_range = range_numbers[0] if range_numbers else 5
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
            distance = grid_distance_ft(
                (int(actor_pos["row"]), int(actor_pos["col"])),
                (int(target_pos["row"]), int(target_pos["col"])),
                cell_size_ft=grid.cell_size_ft if grid is not None else 5,
            )
            if distance > maximum_range:
                raise ValueError("目标超出该动作的合法距离")
            sight_blockers: set[tuple[int, int]] = set()
            if grid is not None:
                raw_cells = grid.layers_json.get("cells", [])
                if isinstance(raw_cells, list):
                    sight_blockers.update(
                        (int(cell["row"]), int(cell["col"]))
                        for cell in raw_cells
                        if isinstance(cell, dict)
                        and (
                            cell.get("kind") == "wall"
                            or cell.get("blocks_sight") is True
                        )
                        and isinstance(cell.get("row"), int)
                        and isinstance(cell.get("col"), int)
                    )
                scene_objects = session.scalars(
                    select(SceneObject).where(SceneObject.scene_id == grid.scene_id)
                ).all()
                for scene_object in scene_objects:
                    blocks_sight = scene_object.object_type == "wall" or (
                        scene_object.object_type == "door"
                        and scene_object.state in {"active", "closed"}
                    )
                    if not blocks_sight:
                        continue
                    sight_blockers.update(
                        (row, col)
                        for row in range(
                            scene_object.row,
                            scene_object.row + scene_object.height_cells,
                        )
                        for col in range(
                            scene_object.col,
                            scene_object.col + scene_object.width_cells,
                        )
                    )
            actor_point = (int(actor_pos["row"]), int(actor_pos["col"]))
            target_point = (int(target_pos["row"]), int(target_pos["col"]))
            if not line_of_sight(actor_point, target_point, sight_blockers):
                raise ValueError("目标被墙体或关闭的门完全遮挡，无法建立攻击视线")
            cost_text = str(action.get("cost") or "动作")
            cost: Literal["action", "bonus_action", "reaction"] = (
                "bonus_action"
                if "附赠" in cost_text
                else "reaction"
                if "反应" in cost_text
                else "action"
            )
            damage_text = str(action.get("damage") or "")
            known_damage_types = (
                "挥砍",
                "穿刺",
                "钝击",
                "火焰",
                "寒冷",
                "闪电",
                "雷鸣",
                "酸蚀",
                "毒素",
                "心灵",
                "黯蚀",
                "光耀",
                "力场",
            )
            damage_type = next(
                (kind for kind in known_damage_types if kind in damage_text),
                str(action.get("damage_type") or "钝击"),
            )
            combat_id = combat.id
            save_ability = str(action.get("save_ability") or "")
            save_dc = int(action.get("save_dc") or 0)
            saving_throw_action = bool(save_ability and save_dc)
            requested_ids = list(dict.fromkeys(target_ids or [target.id]))
            if target.id not in requested_ids:
                requested_ids.insert(0, target.id)
            requested_targets = [
                item
                for item in fighters
                if item.id in requested_ids and item.entity_type == "monster" and item.hp > 0
            ]
            if {item.id for item in requested_targets} != set(requested_ids):
                raise ValueError("区域目标包含不存在、倒地或非敌对单位")

            if saving_throw_action and len(requested_targets) > 1:
                aim_point = (int(target_pos["row"]), int(target_pos["col"]))
                cell_size = grid.cell_size_ft if grid is not None else 5
                shape = (
                    "line"
                    if re.search(r"直线|束", range_text)
                    else "circle"
                    if re.search(r"半径|球形|爆发|圆形", range_text)
                    else "single"
                )
                radius = range_numbers[1] if len(range_numbers) > 1 else 20
                width = range_numbers[1] if len(range_numbers) > 1 else cell_size
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
                    legal = candidate.id == target.id
                    if shape == "circle":
                        legal = (
                            grid_distance_ft(
                                aim_point,
                                candidate_point,
                                cell_size_ft=cell_size,
                            )
                            <= radius
                            and line_of_sight(
                                aim_point,
                                candidate_point,
                                sight_blockers,
                            )
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
                            and line_of_sight(
                                actor_point,
                                candidate_point,
                                sight_blockers,
                            )
                        )
                    if not legal:
                        raise ValueError(f"{candidate.display_name}不在玩家选择的技能范围内")
            elif not saving_throw_action:
                requested_targets = [target]

            resource_key = str(action.get("resource_key") or "")
            resource_cost = int(action.get("resource_cost") or 0)
            if resource_key and resource_cost:
                resource = (character.resources or {}).get(resource_key)
                current = int(resource.get("current") or 0) if isinstance(resource, dict) else 0
                if current < resource_cost:
                    raise ValueError("对应法术位或资源不足")

            commands: list[CombatActionCommand] = []
            for index, current_target in enumerate(requested_targets):
                if saving_throw_action:
                    scores = current_target.snapshot_json.get("ability_scores")
                    save = roll_save(
                        scores if isinstance(scores, dict) else {},
                        save_ability,
                        save_dc,
                    )
                    amount = (
                        damage_total // 2
                        if save["success"] and bool(action.get("half_damage_on_save"))
                        else 0
                        if save["success"]
                        else damage_total
                    )
                    note = (
                        f"玩家报告共用伤害骰 {damage_total}；"
                        f"{current_target.display_name}{save['ability_label']}豁免 "
                        f"{save['raw_roll']} {save['modifier']:+d} = {save['total']} "
                        f"vs DC {save_dc}：{'成功' if save['success'] else '失败'}"
                    )
                else:
                    hit = attack_total >= current_target.armor_class
                    amount = damage_total if hit else 0
                    note = (
                        f"玩家掷骰 {attack_total} 对抗 AC {current_target.armor_class}："
                        f"{'命中' if hit else '未命中'}"
                    )
                commands.append(
                    CombatActionCommand(
                        action_type="damage",
                        target_combatant_id=current_target.id,
                        target_version=current_target.version,
                        actor_combatant_id=actor.id if index == 0 else None,
                        actor_version=actor.version if index == 0 else None,
                        action_cost=cost if index == 0 else "none",
                        action_name=action_name,
                        resolution_note=note,
                        amount=amount,
                        damage_type=damage_type,
                    )
                )

        results = [
            self.combat.confirm(
                principal.campaign_id,
                combat_id,
                command,
                idempotency_key=(
                    idempotency_key if index == 0 else f"{idempotency_key}:{index}"
                ),
            )
            for index, command in enumerate(commands)
        ]
        if resource_key and resource_cost:
            with Session(self.engine) as session, session.begin():
                character = session.get(Character, principal.character_id)
                if character is None:
                    raise StateNotFoundError("character not found")
                resources = dict(character.resources or {})
                resource = json_dict(resources.get(resource_key))
                resource["current"] = max(0, int(resource.get("current") or 0) - resource_cost)
                resources[resource_key] = resource
                character.resources = resources
                character.version += 1
                character.updated_at = _now()
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
            "turn_advance": turn_advance,
        }

    def confirm_roll(
        self,
        principal: PlayerPrincipal,
        action_id: str,
        action_version: int,
        roll_total: int,
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
            actor = (
                session.scalar(
                    select(Combatant).where(
                        Combatant.combat_id == combat.id,
                        Combatant.entity_type == "character",
                        Combatant.entity_id == principal.character_id,
                    )
                )
                if combat
                else None
            )
            if (
                combat is None
                or combat.status != "active"
                or action is None
                or action.combat_id != combat.id
                or actor is None
                or actor.id not in action.target_combatant_ids
            ):
                raise ValueError("该骰子请求不属于你的当前角色")
            combat_id = combat.id
        roll_result = self.combat.confirm_player_roll(
            principal.campaign_id,
            combat_id,
            action_id,
            PlayerRollResolutionCommand(
                action_version=action_version, roll_total=roll_total, dm_note="由局域网玩家提交"
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
            if require_non_character and active.entity_type == "character":
                return None
            if not require_non_character and (
                active.entity_type != "character"
                or active.entity_id != principal.character_id
            ):
                return None
            unresolved = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat.id,
                    CombatAction.status == "previewed",
                    CombatAction.action_type == "player_roll_prompt",
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
            if (
                active is None
                or active.entity_type != "character"
                or active.entity_id != principal.character_id
            ):
                raise ValueError("现在还没有轮到你的角色")
            combat_id = combat.id
        return self.combat.advance_turn(
            principal.campaign_id,
            combat_id,
            TurnAdvanceCommand(combat_version=combat_version),
            idempotency_key=idempotency_key,
        )
