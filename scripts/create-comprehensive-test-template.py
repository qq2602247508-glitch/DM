#!/usr/bin/env python3
"""Create a disposable, comprehensive LAN Scene/combat acceptance campaign."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

BASE = os.getenv("DND_DM_ACCEPTANCE_BASE", "http://127.0.0.1:8000/api/v1")


def request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=payload,
        headers={"Content-Type": "application/json"} if payload else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc


def post(path: str, body: dict[str, Any]) -> Any:
    return request("POST", path, body)


def action(
    name: str,
    description: str,
    damage: str,
    range_text: str,
    *,
    attack_bonus: int | None = None,
    save_ability: str | None = None,
    save_dc: int | None = None,
    damage_type: str,
    resource_key: str | None = None,
    resource_cost: int = 0,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "damage": damage,
        "damage_type": damage_type,
        "range": range_text,
        "attack_bonus": attack_bonus,
        "save_ability": save_ability,
        "save_dc": save_dc,
        "half_damage_on_save": save_ability is not None,
        "cost": "动作",
        "resource_key": resource_key,
        "resource_cost": resource_cost,
        "resolution_kind": "damage",
    }


def monster_action(
    name: str,
    description: str,
    damage: str,
    range_text: str,
    *,
    attack_bonus: int | None = None,
    save_ability: str | None = None,
    save_dc: int | None = None,
    damage_type: str,
) -> dict[str, Any]:
    return action(
        name,
        description,
        damage,
        range_text,
        attack_bonus=attack_bonus,
        save_ability=save_ability,
        save_dc=save_dc,
        damage_type=damage_type,
    )


def main() -> None:
    suffix = datetime.now(UTC).astimezone().strftime("%m%d-%H%M")
    campaign = post(
        "/campaigns",
        {
            "name": f"综合规则验收团 · {suffix}",
            "description": (
                "一次性联机验收模板：先测试 Scene 探索、非战斗技能、目标和投骰，"
                "再从同一 Scene 发起战斗测试五类战斗能力与五种敌人。"
            ),
            "world_setting": "D&D 5e 2024 · 博德之门外的雾锁钟楼旅店",
            "ruleset": "dnd5e",
            "primary_rules_year": 2024,
            "allow_legacy": False,
        },
    )
    cid = campaign["id"]
    prefix = f"/campaigns/{cid}"

    location = post(
        f"{prefix}/locations",
        {
            "name": "雾锁钟楼旅店",
            "depth": 1,
            "description": (
                "一座建在废弃钟楼下的两层旅店。大厅、档案室、上锁酒窖、旧祭坛和"
                "排水沟相连，适合测试社交、调查、潜行、机关与战斗网格。"
            ),
            "interactive_objects": [
                {"name": "黄铜总钥匙", "weight_lb": 0.1, "price_gp": 5},
                {"name": "钟楼机关杆", "effect": "打开酒窖侧门"},
                {"name": "可疑账本", "effect": "提供邪教交易线索"},
            ],
            "secrets": "老板知道酒窖祭坛的来历；账本夹层藏着真正的钥匙。",
            "discovered": True,
        },
    )

    combat_actions = [
        action(
            "魔法飞弹",
            "自动命中的力场飞弹；默认产生3枚飞弹，可分配给一个或多个可见目标。",
            "3d4+3 力场",
            "120尺；最多3个可见目标",
            damage_type="force",
            resource_key="spell_slots_1",
            resource_cost=1,
        ),
        action(
            "迅捷刺剑",
            "近战武器攻击；单体、5尺，测试贴身攻击与AC命中。",
            "1d8+4 穿刺",
            "5尺",
            attack_bonus=8,
            damage_type="piercing",
        ),
        action(
            "精准长弓",
            "远程武器攻击；单体、150尺，测试远程距离与掩体。",
            "1d8+4 穿刺",
            "150尺",
            attack_bonus=8,
            damage_type="piercing",
        ),
        action(
            "火焰箭",
            "远程法术攻击；单体、120尺，测试法术攻击与火焰抗性。",
            "3d10 火焰",
            "120尺",
            attack_bonus=9,
            damage_type="fire",
        ),
        action(
            "冷冻射线",
            "远程法术攻击；命中后造成冷冻伤害，并由DM记录目标速度降低10尺。",
            "3d8 冷冻",
            "60尺",
            attack_bonus=9,
            damage_type="cold",
        ),
        action(
            "火球术",
            "150尺施法距离；以目标点为中心20尺半径球形爆发。",
            "8d6 火焰",
            "150尺；20尺半径球形爆发",
            save_ability="dexterity",
            save_dc=17,
            damage_type="fire",
            resource_key="spell_slots_3",
            resource_cost=1,
        ),
        action(
            "闪电束",
            "100尺长、5尺宽直线；测试方向选择和直线多目标。",
            "8d6 闪电",
            "100尺长直线；5尺宽",
            save_ability="dexterity",
            save_dc=17,
            damage_type="lightning",
            resource_key="spell_slots_3",
            resource_cost=1,
        ),
        action(
            "酸液飞溅",
            "目标进行敏捷豁免；用于测试无需攻击检定的单体戏法。",
            "3d6 酸蚀",
            "60尺",
            save_ability="dexterity",
            save_dc=17,
            damage_type="acid",
        ),
    ]
    noncombat_spells = [
        {
            "name": "隐形术",
            "source_record_id": "acceptance-invisibility",
            "spell_level": 2,
            "prepared": True,
            "range": "触及",
            "duration": "专注，至多1小时",
            "concentration": True,
            "description": "目标隐形；由DM根据场景决定隐匿、被发现和互动后果。",
            "resource_key": "spell_slots_2",
            "resource_cost": 1,
            "resolution_kind": "narrative",
        },
        {
            "name": "命令术",
            "source_record_id": "acceptance-command",
            "spell_level": 1,
            "prepared": True,
            "range": "60尺",
            "duration": "1轮",
            "concentration": False,
            "save_ability": "wisdom",
            "save_dc": 17,
            "description": "对可见且能理解语言的生物给出一个单词命令。",
            "resource_key": "spell_slots_1",
            "resource_cost": 1,
            "resolution_kind": "narrative",
        },
        {
            "name": "侦测魔法",
            "source_record_id": "acceptance-detect-magic",
            "spell_level": 1,
            "prepared": True,
            "range": "自身；30尺范围",
            "duration": "专注，至多10分钟",
            "concentration": True,
            "description": "感知附近魔法气息；结果由DM结合公开与隐藏物体裁定。",
            "resource_key": "spell_slots_1",
            "resource_cost": 1,
            "resolution_kind": "narrative",
        },
    ]
    character = post(
        f"{prefix}/characters",
        {
            "name": "艾琳·综合验收员",
            "race": "人类",
            "background": "罪犯",
            "class_name": "游荡者8 / 法师4",
            "level": 12,
            "experience": 100000,
            "armor_class": 17,
            "speed": 30,
            "ability_scores": {
                "strength": 10,
                "dexterity": 18,
                "constitution": 14,
                "intelligence": 18,
                "wisdom": 12,
                "charisma": 14,
            },
            "hp": 82,
            "max_hp": 82,
            "inventory": [
                {
                    "name": "盗贼工具",
                    "quantity": 1,
                    "unit_weight_lb": 1,
                    "price_gp": 25,
                },
                {
                    "name": "治疗药水",
                    "quantity": 2,
                    "unit_weight_lb": 0.5,
                    "price_gp": 50,
                },
                {
                    "name": "50尺丝绳",
                    "quantity": 1,
                    "unit_weight_lb": 5,
                    "price_gp": 10,
                },
            ],
            "equipment": ["+1刺剑", "长弓", "镶钉皮甲", "奥术法器", "盗贼工具"],
            "proficiencies": ["轻甲", "简易武器", "军用灵巧武器", "盗贼工具"],
            "skills": {
                "调查": {"proficient": True, "expertise": True},
                "察觉": {"proficient": True},
                "巧手": {"proficient": True, "expertise": True},
                "潜行": {"proficient": True, "expertise": True},
                "游说": {"proficient": True},
            },
            "features": [
                {"name": "偷袭", "description": "每回合一次满足条件时追加4d6伤害。"},
                {"name": "狡黠动作", "description": "附赠动作疾走、撤离或躲藏。"},
                {"name": "专精", "description": "调查、巧手和潜行使用双倍熟练加值。"},
                {"name": "闪避", "description": "敏捷豁免成功时不受伤，失败时伤害减半。"},
            ],
            "actions": combat_actions,
            "resources": {
                "spell_slots_1": {
                    "label": "1环法术位",
                    "current": 4,
                    "max": 4,
                    "recovery": "long_rest",
                },
                "spell_slots_2": {
                    "label": "2环法术位",
                    "current": 3,
                    "max": 3,
                    "recovery": "long_rest",
                },
                "spell_slots_3": {
                    "label": "3环法术位",
                    "current": 3,
                    "max": 3,
                    "recovery": "long_rest",
                },
                "sneak_attack": {
                    "label": "偷袭",
                    "current": 1,
                    "max": 1,
                    "recovery": "turn",
                },
            },
            "spells": noncombat_spells,
            "spellcasting": {
                "ability": "智力",
                "save_dc": 17,
                "attack_bonus": 9,
                "mode": "slots",
            },
            "class_levels": {"游荡者": 8, "法师": 4},
            "notes": (
                "验收角色。非战斗重点：调查、察觉、巧手、潜行、游说；"
                "战斗重点：近战、远程、单体法术攻击、圆形范围、直线范围。"
            ),
        },
    )

    npc_specs = [
        {
            "name": "旅店老板玛拉",
            "description": "友善但隐瞒酒窖秘密，适合游说与洞悉。",
            "attitude": "friendly",
            "goal": "保护旅店生意",
            "fear": "地下祭坛曝光",
            "armor_class": 11,
            "hp": 9,
            "max_hp": 9,
            "ability_scores": {"wisdom": 14, "charisma": 15},
            "known_information": "知道黄铜钥匙在账本夹层。",
            "secrets": "曾替邪教徒保管祭坛物资。",
            "location_id": location["id"],
        },
        {
            "name": "钟表匠奥杜",
            "description": "多疑的锁匠，能说明门锁结构，适合调查与游说。",
            "attitude": "neutral",
            "goal": "找回失窃的总钥匙",
            "fear": "被当成共犯",
            "armor_class": 12,
            "hp": 12,
            "max_hp": 12,
            "ability_scores": {"intelligence": 16, "wisdom": 13},
            "known_information": "铁门锁芯有一个会触发警铃的假销。",
            "location_id": location["id"],
        },
        {
            "name": "城卫军士蕾娜",
            "description": "保持警戒的守卫，适合命令术、欺瞒、游说和洞悉测试。",
            "attitude": "suspicious",
            "goal": "控制现场并保护平民",
            "fear": "怪物突破地窖",
            "armor_class": 16,
            "hp": 32,
            "max_hp": 32,
            "ability_scores": {
                "strength": 15,
                "dexterity": 12,
                "constitution": 14,
                "wisdom": 14,
                "charisma": 11,
            },
            "actions": [
                monster_action(
                    "长矛",
                    "近战或投掷武器攻击。",
                    "1d6+2 穿刺",
                    "5尺或20尺",
                    attack_bonus=4,
                    damage_type="piercing",
                )
            ],
            "location_id": location["id"],
        },
    ]
    npcs = [post(f"{prefix}/npcs", spec) for spec in npc_specs]

    monster_specs = [
        {
            "name": "地精弓手·验收",
            "source_name": "Goblin",
            "armor_class": 15,
            "hp": 21,
            "max_hp": 21,
            "speed": 30,
            "ability_scores": {
                "strength": 8,
                "dexterity": 16,
                "constitution": 10,
                "wisdom": 8,
            },
            "challenge_rating": "1/4",
            "actions": [
                monster_action(
                    "短弓",
                    "远程武器攻击；会寻找掩体。",
                    "1d6+3 穿刺",
                    "80尺",
                    attack_bonus=5,
                    damage_type="piercing",
                )
            ],
            "notes": "游击/远程型；用于测试掩体、移动和射程。",
        },
        {
            "name": "枭熊·验收",
            "source_name": "Owlbear",
            "armor_class": 13,
            "hp": 59,
            "max_hp": 59,
            "speed": 40,
            "ability_scores": {
                "strength": 20,
                "dexterity": 12,
                "constitution": 17,
                "wisdom": 12,
            },
            "challenge_rating": "3",
            "actions": [
                monster_action(
                    "喙击",
                    "蛮力近战攻击。",
                    "1d10+5 穿刺",
                    "5尺",
                    attack_bonus=7,
                    damage_type="piercing",
                ),
                monster_action(
                    "利爪",
                    "近战攻击。",
                    "2d8+5 挥砍",
                    "5尺",
                    attack_bonus=7,
                    damage_type="slashing",
                ),
            ],
            "notes": "高速蛮力型；用于测试接敌、移动和多动作资料。",
        },
        {
            "name": "邪教狂信徒·验收",
            "source_name": "Cult Fanatic",
            "armor_class": 13,
            "hp": 33,
            "max_hp": 33,
            "speed": 30,
            "ability_scores": {
                "strength": 11,
                "dexterity": 14,
                "constitution": 12,
                "wisdom": 16,
                "charisma": 14,
            },
            "challenge_rating": "2",
            "actions": [
                monster_action(
                    "神圣火焰",
                    "目标进行敏捷豁免。",
                    "2d8 光耀",
                    "60尺",
                    save_ability="dexterity",
                    save_dc=13,
                    damage_type="radiant",
                )
            ],
            "notes": "施法/豁免型；用于测试玩家输入豁免与怪物自动回合。",
        },
        {
            "name": "宝箱拟怪·验收",
            "source_name": "Mimic",
            "armor_class": 12,
            "hp": 58,
            "max_hp": 58,
            "speed": 15,
            "ability_scores": {
                "strength": 17,
                "dexterity": 12,
                "constitution": 15,
                "wisdom": 13,
            },
            "challenge_rating": "2",
            "actions": [
                monster_action(
                    "伪足",
                    "命中后建议附着目标。",
                    "1d8+3 钝击",
                    "5尺",
                    attack_bonus=5,
                    damage_type="bludgeoning",
                )
            ],
            "notes": "伏击/拟态型；场景中靠近宝箱，用于测试突发登场。",
        },
        {
            "name": "凝胶立方·验收",
            "source_name": "Gelatinous Cube",
            "armor_class": 6,
            "hp": 84,
            "max_hp": 84,
            "speed": 15,
            "ability_scores": {
                "strength": 14,
                "dexterity": 3,
                "constitution": 20,
                "wisdom": 6,
            },
            "challenge_rating": "2",
            "actions": [
                monster_action(
                    "吞噬",
                    "附近目标进行敏捷豁免；失败则受酸蚀并被吞入。",
                    "3d6 酸蚀",
                    "5尺",
                    save_ability="dexterity",
                    save_dc=12,
                    damage_type="acid",
                )
            ],
            "notes": "缓慢环境威胁型；用于测试低敏豁免、狭窄通道和酸蚀。",
        },
    ]
    monsters = [post(f"{prefix}/monsters", spec) for spec in monster_specs]

    scene = post(
        f"{prefix}/scenes",
        {
            "name": "Scene 1 · 雾锁钟楼综合验收场",
            "location_id": location["id"],
            "description": (
                "玩家从旅店大厅进入钟楼地下层。档案室、仪式室、卧室、军械室、"
                "秘密墓室与藏宝室由横向走廊和中央通道连接；每个出入口都有门。"
                "仪式室铁门带警铃假销，藏宝室附近潜伏拟怪，排水沟中有凝胶立方。"
                "DM可先按非战斗状态测试，随后从同一Scene发起战斗。"
            ),
            "status": "active",
            "notes": (
                "chapter=验收章;scene_order=1;objective=先完成探索、社交和撬锁，"
                "再从同一Scene进入五怪战斗。"
            ),
        },
    )
    sid = scene["id"]

    cells: list[dict[str, Any]] = []
    width, height = 20, 14
    occupied: dict[tuple[int, int], int] = {}

    def add_cell(
        row: int,
        col: int,
        kind: str,
        label: str,
        *,
        replace: bool = False,
        blocks_sight: bool = False,
    ) -> None:
        payload: dict[str, Any] = {"row": row, "col": col, "kind": kind, "label": label}
        if blocks_sight:
            payload["blocks_sight"] = True
        existing = occupied.get((row, col))
        if existing is not None:
            if replace:
                cells[existing] = payload
            return
        occupied[(row, col)] = len(cells)
        cells.append(payload)

    def line(
        start_row: int,
        start_col: int,
        end_row: int,
        end_col: int,
        label: str,
    ) -> None:
        row_step = 0 if start_row == end_row else (1 if end_row > start_row else -1)
        col_step = 0 if start_col == end_col else (1 if end_col > start_col else -1)
        row, col = start_row, start_col
        while True:
            add_cell(row, col, "wall", label)
            if row == end_row and col == end_col:
                break
            row += row_step
            col += col_step

    def room(top: int, left: int, bottom: int, right: int, label: str) -> None:
        line(top, left, top, right, f"{label}墙")
        line(bottom, left, bottom, right, f"{label}墙")
        line(top, left, bottom, left, f"{label}墙")
        line(top, right, bottom, right, f"{label}墙")

    # Six individually enclosed rooms joined by one horizontal corridor,
    # a vertical spine and two side branches. The remaining cells are dark,
    # blocked map void rather than an implausibly walkable mega-room.
    room(1, 1, 7, 7, "档案室")
    room(9, 1, 14, 7, "仪式室")
    room(1, 10, 3, 15, "卧室")
    room(1, 17, 7, 20, "军械室")
    room(12, 10, 14, 16, "秘密墓室")
    room(9, 17, 14, 20, "藏宝室")
    line(3, 7, 3, 17, "北走廊墙")
    line(5, 7, 5, 10, "北走廊墙")
    line(5, 15, 5, 17, "北走廊墙")
    line(5, 11, 10, 11, "中央通道西墙")
    line(5, 14, 10, 14, "中央通道东墙")
    line(10, 7, 10, 11, "西支路墙")
    line(12, 7, 12, 10, "西支路墙")
    line(10, 14, 10, 17, "东支路墙")
    line(12, 16, 12, 17, "东支路墙")

    doors = [
        (4, 7, "档案室侧门"),
        (11, 7, "仪式室警铃铁门"),
        (3, 12, "卧室南门"),
        (4, 17, "军械室木门"),
        (11, 11, "西支路拱门"),
        (11, 14, "东支路拱门"),
        (12, 13, "秘密墓室门"),
        (11, 17, "藏宝室铁门"),
        (8, 12, "中央升降门"),
    ]
    for row, col, label in doors:
        add_cell(row, col, "door", label, replace=True)

    for row, col, label in [
        (2, 4, "档案室"),
        (13, 4, "仪式室"),
        (2, 12, "卧室"),
        (2, 18, "军械室"),
        (4, 9, "北走廊"),
        (7, 12, "中央通道"),
        (13, 11, "秘密墓室"),
        (13, 18, "藏宝室"),
    ]:
        add_cell(row, col, "floor", label)

    def footprint(row: int, col: int) -> bool:
        return (
            (1 <= row <= 7 and 1 <= col <= 7)
            or (9 <= row <= 14 and 1 <= col <= 7)
            or (1 <= row <= 3 and 10 <= col <= 15)
            or (1 <= row <= 7 and 17 <= col <= 20)
            or (12 <= row <= 14 and 10 <= col <= 16)
            or (9 <= row <= 14 and 17 <= col <= 20)
            or (3 <= row <= 5 and 7 <= col <= 17)
            or (5 <= row <= 12 and 11 <= col <= 14)
            or (10 <= row <= 12 and 7 <= col <= 11)
            or (10 <= row <= 12 and 14 <= col <= 17)
        )
    for row in range(1, height + 1):
        for col in range(1, width + 1):
            if not footprint(row, col):
                add_cell(row, col, "wall", "地图外区域")

    for row, col, kind, label, blocks_sight in [
        (3, 3, "cover", "档案桌", False),
        (3, 4, "cover", "档案桌", False),
        (4, 13, "cover", "落地档案柜", True),
        (7, 13, "cover", "承重石柱", True),
        (5, 18, "cover", "武器架", True),
        (10, 4, "cover", "翻倒长椅", False),
        (12, 19, "cover", "酒桶堆", False),
        (13, 19, "water", "排水沟", False),
        (9, 12, "difficult", "碎石", False),
        (10, 13, "difficult", "碎石", False),
    ]:
        add_cell(row, col, kind, label, blocks_sight=blocks_sight)

    blocked_cells = {
        (int(cell["row"]), int(cell["col"]))
        for cell in cells
        if cell["kind"] == "wall"
    }
    room_markers = {
        (int(cell["row"]), int(cell["col"]))
        for cell in cells
        if cell["kind"] == "floor"
        and cell["label"] in {"档案室", "仪式室", "卧室", "军械室", "秘密墓室", "藏宝室"}
    }
    frontier = [next(iter(room_markers))]
    reachable = set(frontier)
    while frontier:
        row, col = frontier.pop()
        for candidate in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            if (
                1 <= candidate[0] <= height
                and 1 <= candidate[1] <= width
                and candidate not in blocked_cells
                and candidate not in reachable
            ):
                reachable.add(candidate)
                frontier.append(candidate)
    if not room_markers.issubset(reachable):
        raise RuntimeError("generated acceptance grid contains a disconnected room")
    for row, col, label in doors:
        open_neighbors = sum(
            neighbor not in blocked_cells
            for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1))
        )
        if open_neighbors < 2:
            raise RuntimeError(f"door {label} does not connect two walkable areas")
    post(
        f"{prefix}/scenes/{sid}/grid",
        {
            "width": width,
            "height": height,
            "cell_size_ft": 5,
            "mode": "exploration",
            "public_description": (
                "20×14格钟楼地下层：六个独立房间由横向走廊、中央通道和支路连接；"
                "每个房间入口均有明确门标记，并包含硬遮挡、碎石和排水沟。每格5尺。"
            ),
            "dm_description": "隐藏压力板位于铁门内侧；拟怪伪装为南侧宝箱。",
            "layers_json": {"theme": "clocktower-cellar", "cells": cells},
        },
    )

    object_specs = [
        {
            "object_type": "door",
            "label": "带警铃假销的仪式室铁门",
            "row": 11,
            "col": 7,
            "state": "closed",
            "visibility": "public",
            "interaction_json": {
                "action": "lockpick",
                "locked": True,
                "tool": "盗贼工具",
                "dc": 16,
                "description": "成功打开；失败时DM可让警铃响起。",
            },
        },
        {
            "object_type": "treasure",
            "label": "三重锁旅行箱",
            "row": 12,
            "col": 4,
            "state": "closed",
            "visibility": "public",
            "interaction_json": {
                "action": "lockpick",
                "locked": True,
                "tool": "盗贼工具",
                "dc": 14,
                "description": "内有银钥匙、治疗药水和假账本。",
            },
        },
        {
            "object_type": "trap",
            "label": "可见的符文警报机关",
            "row": 10,
            "col": 5,
            "state": "active",
            "visibility": "public",
            "interaction_json": {
                "action": "disarm",
                "tool": "盗贼工具",
                "dc": 15,
                "description": "解除后不会在开门时发出警报。",
            },
        },
        {
            "object_type": "trap",
            "label": "隐藏压力板（玩家不应看到）",
            "row": 9,
            "col": 12,
            "state": "active",
            "visibility": "hidden",
            "interaction_json": {"action": "disarm", "dc": 17},
            "metadata_json": {"secret": "触发后落下铁栅并唤醒怪物"},
        },
        {
            "object_type": "portal",
            "label": "钟楼升降机关",
            "row": 3,
            "col": 19,
            "state": "closed",
            "visibility": "public",
            "interaction_json": {
                "action": "unlock",
                "locked": True,
                "tool": "盗贼工具",
                "dc": 18,
                "description": "也可用黄铜总钥匙直接打开。",
            },
        },
        {
            "object_type": "furniture",
            "label": "夹层账本",
            "row": 3,
            "col": 3,
            "state": "active",
            "visibility": "public",
            "interaction_json": {
                "action": "search",
                "description": "调查可发现夹层与黄铜总钥匙。",
            },
        },
    ]
    objects = [
        post(f"{prefix}/scenes/{sid}/objects", {**spec, "width_cells": 1, "height_cells": 1})
        for spec in object_specs
    ]

    token_specs = [
        ("character", character, 4, 4),
        ("npc", npcs[0], 3, 5),
        ("npc", npcs[1], 11, 4),
        ("npc", npcs[2], 2, 13),
        ("monster", monsters[0], 4, 18),
        ("monster", monsters[1], 12, 18),
        ("monster", monsters[2], 8, 13),
        ("monster", monsters[3], 12, 5),
        ("monster", monsters[4], 13, 13),
    ]
    for entity_type, entity, row, col in token_specs:
        post(
            f"{prefix}/scenes/{sid}/tokens",
            {
                "entity_type": entity_type,
                "entity_id": entity["id"],
                "label": entity["name"],
                "row": row,
                "col": col,
                "visible": True,
                "metadata_json": {"acceptance_template": True},
            },
        )
        post(
            f"{prefix}/scenes/{sid}/participants",
            {
                "entity_type": entity_type,
                "entity_id": entity["id"],
                "role": "present",
                "visible": True,
                "notes": "综合验收模板固定成员",
            },
        )

    room = post(f"{prefix}/player-room/open", {"hours": 12})
    post(
        f"{prefix}/player-room/live-state",
        {"scene_id": sid, "combat_id": None},
    )

    result = {
        "campaign": {"id": cid, "name": campaign["name"]},
        "location": {"id": location["id"], "name": location["name"]},
        "scene": {"id": sid, "name": scene["name"]},
        "character": {"id": character["id"], "name": character["name"]},
        "npcs": [{"id": item["id"], "name": item["name"]} for item in npcs],
        "monsters": [{"id": item["id"], "name": item["name"]} for item in monsters],
        "objects": [{"id": item["id"], "label": item["label"]} for item in objects],
        "room_code": room["join_code"],
        "player_urls": room["urls"],
        "instructions": [
            "先用玩家入口加入房间并绑定“艾琳·综合验收员”。",
            "先不要发起战斗：测试网格、NPC/怪物/物体位置、调查/察觉/游说/潜行/巧手。",
            "测试铁门、旅行箱、公开符文机关；确认隐藏压力板不会泄漏。",
            "再由DM从当前Scene发起战斗，测试五种战斗能力与五类怪物。",
            "重点对比魔法飞弹自动命中、火焰箭/冷冻射线攻击检定、酸液飞溅单体豁免、火球术圆形范围与闪电束直线范围。",
            "尝试隔墙选择目标，确认墙、落地档案柜、石柱和倒塌圣像会阻断视线。",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"创建综合验收模板失败：{exc}", file=sys.stderr)
        raise
