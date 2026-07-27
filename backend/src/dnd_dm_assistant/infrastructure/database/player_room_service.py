from __future__ import annotations

import hashlib
import os
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
from dnd_dm_assistant.domain.exploration import grid_distance_ft, movement_cost_ft
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import (
    Campaign,
    Character,
    Combat,
    CombatAction,
    Combatant,
    PlayerRoom,
    PlayerSession,
    Scene,
    SceneGrid,
    SceneObject,
    SceneToken,
)
from dnd_dm_assistant.infrastructure.database.player_service import PlayerService

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
    return "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))


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
                }
            ),
            "tokens": [
                {
                    "id": item.id,
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
                }
                for item in objects
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
                }
                for action in actions
            ],
            "pending_rolls": pending,
        }

    @staticmethod
    def _safe_combatant(item: Combatant, own: Combatant | None) -> dict[str, Any]:
        is_own = own is not None and item.id == own.id
        ally = item.entity_type in {"character", "npc"}
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
            # Players need the concrete hit threshold before rolling. Exact
            # enemy HP and private notes remain hidden, but AC is a public
            # combat target value in this assisted workflow.
            "armor_class": item.armor_class,
        }
        if is_own or ally:
            result.update(
                {
                    "hp": item.hp,
                    "max_hp": item.max_hp,
                    "conditions": item.conditions,
                }
            )
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
        action_name: str,
        attack_total: int,
        damage_total: int,
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
            normal_range = range_text.split("/", 1)[0]
            digits = "".join(char for char in normal_range if char.isdigit())
            maximum_range = int(digits or "5")
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
            hit = attack_total >= target.armor_class
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
            result_text = "命中" if hit else "未命中"
            command = CombatActionCommand(
                action_type="damage",
                target_combatant_id=target.id,
                target_version=target.version,
                actor_combatant_id=actor.id,
                actor_version=actor.version,
                action_cost=cost,
                action_name=action_name,
                resolution_note=(
                    f"玩家掷骰 {attack_total} 对抗 AC {target.armor_class}：{result_text}"
                ),
                amount=damage_total if hit else 0,
                damage_type=damage_type,
            )
            combat_id = combat.id
        return self.combat.confirm(
            principal.campaign_id, combat_id, command, idempotency_key=idempotency_key
        )

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
        return {"roll": roll_result, "damage": damage_result}

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
