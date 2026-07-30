#!/usr/bin/env python3
"""Create a complete one-DM/one-player beginner adventure campaign.

The generated campaign is a playable module, not an acceptance sandbox.  Use
``--rehearsal`` for a disposable copy and omit it for the pristine delivery.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from duskbell_map_layouts import DuskbellMapLayout, assert_duskbell_layouts

BASE = os.getenv("DND_DM_ACCEPTANCE_BASE", "http://127.0.0.1:8000/api/v1")


def request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> Any:
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    request_headers = {"Content-Type": "application/json"} if payload else {}
    request_headers.update(headers or {})
    req = urllib.request.Request(
        BASE + path,
        data=payload,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc


def post(path: str, body: dict[str, Any]) -> Any:
    return request("POST", path, body)


def get(path: str) -> Any:
    return request("GET", path)


def combat_action(
    name: str,
    description: str,
    damage: str,
    range_text: str,
    damage_type: str,
    *,
    attack_bonus: int | None = None,
    save_ability: str | None = None,
    save_dc: int | None = None,
    cost: str = "动作",
    resource_key: str | None = None,
    resource_cost: int = 0,
    half_damage_on_save: bool = False,
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
        "half_damage_on_save": half_damage_on_save,
        "cost": cost,
        "resource_key": resource_key,
        "resource_cost": resource_cost,
        "resolution_kind": "damage",
    }


def outline(
    chapter: str,
    chapter_order: int,
    scene_order: int,
    objective: str,
    opening: str,
    development: str,
    twist: str,
    climax: str,
    transition: str,
) -> str:
    return json.dumps(
        {
            "story_outline": {
                "chapterTitle": chapter,
                "chapterOrder": chapter_order,
                "sceneOrder": scene_order,
                "objective": objective,
                "opening": opening,
                "development": development,
                "twist": twist,
                "climax": climax,
                "transition": transition,
            }
        },
        ensure_ascii=False,
    )


def create_grid(
    prefix: str,
    scene_id: str,
    *,
    layout: DuskbellMapLayout,
) -> Any:
    return post(
        f"{prefix}/scenes/{scene_id}/grid",
        {
            "width": layout.width,
            "height": layout.height,
            "cell_size_ft": 5,
            "mode": "exploration",
            "public_description": layout.public_description,
            "dm_description": layout.dm_description,
            "layers_json": layout.layers_json(),
        },
    )


def add_participant(
    prefix: str,
    scene_id: str,
    entity_type: str,
    entity: dict[str, Any],
    row: int,
    col: int,
    *,
    visible: bool = True,
    role: str = "present",
) -> None:
    # Place the intentional module token first.  The participant endpoint only
    # creates a fallback token when none exists, so this order prevents a
    # duplicate actor from appearing near the top-left corner of every map.
    post(
        f"{prefix}/scenes/{scene_id}/tokens",
        {
            "entity_type": entity_type,
            "entity_id": entity["id"],
            "label": entity["name"],
            "row": row,
            "col": col,
            "visible": visible,
            "metadata_json": {"module": "duskbell-mill", "role": role},
        },
    )
    post(
        f"{prefix}/scenes/{scene_id}/participants",
        {
            "entity_type": entity_type,
            "entity_id": entity["id"],
            "role": role,
            "visible": visible,
            "notes": "《暮铃磨坊》模组预设成员",
        },
    )


def create_object(
    prefix: str,
    scene_id: str,
    *,
    object_type: str,
    label: str,
    row: int,
    col: int,
    state: str = "active",
    visibility: str = "public",
    interaction: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    return post(
        f"{prefix}/scenes/{scene_id}/objects",
        {
            "object_type": object_type,
            "label": label,
            "row": row,
            "col": col,
            "width_cells": 1,
            "height_cells": 1,
            "state": state,
            "visibility": visibility,
            "interaction_json": interaction or {},
            "metadata_json": metadata or {},
        },
    )


def fresh_character(prefix: str, character_id: str) -> dict[str, Any]:
    return get(f"{prefix}/characters/{character_id}")


def create_assets(prefix: str, character: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    cid = character["id"]
    wallet = post(
        f"{prefix}/characters/assets/wallets",
        {
            "character_id": cid,
            "character_version": fresh_character(prefix, cid)["version"],
            "name": "莉亚的钱袋",
            "copper": 1_500,
        },
    )
    equipment_specs = [
        ("皮甲", "armor", 11, {"slot": "armor", "equipped": True, "official": True}),
        ("刺剑", "weapon", None, {"slot": "main_hand", "damage": "1d8 穿刺", "official": True}),
        ("轻弩", "weapon", None, {"slot": "main_hand", "damage": "1d8 穿刺", "range": "80/320尺", "official": True}),
        ("鲁特琴", "focus", None, {"slot": "focus", "official": True}),
        ("盗贼工具", "tool", None, {"proficient": True, "official": True}),
        ("治疗药水", "consumable", None, {"healing": "2d4+2", "official": True}),
        ("探险套组", "gear", None, {"contents": "背包、绳索、火把、口粮、水袋", "official": True}),
    ]
    equipment = []
    for name, category, armor_class, metadata in equipment_specs:
        current = fresh_character(prefix, cid)
        equipment.append(
            post(
                f"{prefix}/characters/assets/equipment",
                {
                    "character_id": cid,
                    "character_version": current["version"],
                    "name": name,
                    "category": category,
                    "quantity": 2 if name == "治疗药水" else 1,
                    "armor_class": armor_class,
                    "metadata_json": metadata,
                },
            )
        )
    spells = []
    for name, level, metadata in [
        ("恶言相加", 0, {"kind": "save_damage", "save": "Wisdom", "damage": "1d6 psychic"}),
        ("法师之手", 0, {"kind": "narrative", "range": "30尺"}),
        ("治愈真言", 1, {"kind": "healing", "cost": "bonus_action", "healing": "2d4+3"}),
        ("不谐低语", 1, {"kind": "save_damage", "save": "Wisdom", "damage": "3d6 psychic"}),
        ("妖火", 1, {"kind": "area_condition", "save": "Dexterity", "area": "20尺立方"}),
        ("雷鸣波", 1, {"kind": "area_damage", "save": "Constitution", "area": "15尺立方", "damage": "2d8 thunder"}),
    ]:
        current = fresh_character(prefix, cid)
        spells.append(
            post(
                f"{prefix}/characters/assets/spells",
                {
                    "character_id": cid,
                    "character_version": current["version"],
                    "name": name,
                    "spell_level": level,
                    "prepared": True,
                    "source_reference": "PHB 2024",
                    "metadata_json": metadata,
                },
            )
        )
    return {"wallet": [wallet], "equipment": equipment, "spells": spells}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name")
    parser.add_argument("--room-hours", type=int, default=24)
    parser.add_argument("--no-room", action="store_true")
    parser.add_argument("--rehearsal", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.room_hours <= 24:
        raise ValueError("--room-hours 必须在 1 到 24 之间")

    suffix = datetime.now(UTC).astimezone().strftime("%m%d-%H%M")
    default_name = "《暮铃磨坊：第一声钟响》· 新手单人模组"
    if args.rehearsal:
        default_name += f" · 排练 {suffix}"
    campaign = post(
        "/campaigns",
        {
            "name": args.name or default_name,
            "description": (
                "原创 D&D 5e 2024 新手冒险：1位DM、1位玩家、约2.5–4小时。"
                "覆盖联机绑定、角色卡、场景网格、战争迷雾、社交、调查、工具、"
                "机关、商店、两场可调难度战斗、范围法术、结算、战利品和1→2级升级。"
            ),
            "world_setting": "D&D 5e 2024 · 剑湾东部的晨溪村",
            "ruleset": "dnd5e",
            "primary_rules_year": 2024,
            "allow_legacy": False,
        },
    )
    campaign_id = campaign["id"]
    prefix = f"/campaigns/{campaign_id}"

    village = post(
        f"{prefix}/locations",
        {
            "name": "晨溪村",
            "depth": 1,
            "description": "沿浅溪而建的小村，提灯旅店、铁匠棚和通往暮铃磨坊的旧路围绕村中心展开。",
            "secrets": "失踪的钟声不是亡灵，而是被困狗头人修补匠在用磨坊机关求救。",
            "discovered": True,
        },
    )
    tavern = post(
        f"{prefix}/locations",
        {
            "name": "提灯旅店",
            "parent_location_id": village["id"],
            "depth": 2,
            "description": "暖色木结构旅店，有吧台、壁炉、公告板和小型杂货柜。",
            "interactive_objects": ["委托公告板", "补给货架", "壁炉边的村民桌"],
            "discovered": True,
        },
    )
    road = post(
        f"{prefix}/locations",
        {
            "name": "林间旧路与断桥",
            "parent_location_id": village["id"],
            "depth": 2,
            "description": "被春雨冲坏的林路，溪流、断桥、倒木和兽径提供多条通过路线。",
            "secrets": "桥下藏有磨坊工头留下的防水工具包。",
            "discovered": True,
        },
    )
    mill = post(
        f"{prefix}/locations",
        {
            "name": "暮铃磨坊",
            "parent_location_id": village["id"],
            "depth": 2,
            "description": "废弃水磨坊由外院、主磨房和地下齿轮工坊组成，木墙与石基形成不规则战术空间。",
            "secrets": "村长曾要求工头掩盖危险的蓄能齿轮；真正反派是失控机关而非求救者。",
            "discovered": True,
        },
    )

    character = post(
        f"{prefix}/characters",
        {
            "name": "莉亚·晨歌",
            "race": "人类",
            "background": "艺人",
            "class_name": "吟游诗人",
            "class_levels": {"吟游诗人": 1},
            "level": 1,
            "experience": 0,
            "armor_class": 14,
            "speed": 30,
            "hp": 10,
            "max_hp": 10,
            "ability_scores": {
                "strength": 8,
                "dexterity": 16,
                "constitution": 14,
                "intelligence": 10,
                "wisdom": 12,
                "charisma": 17,
            },
            "skills": {
                "察觉": {"proficient": True},
                "游说": {"proficient": True},
                "欺瞒": {"proficient": True},
                "洞悉": {"proficient": True},
                "调查": {"proficient": True},
                "表演": {"proficient": True},
                "巧手": {"proficient": True},
            },
            "proficiencies": ["轻甲", "简易武器", "刺剑", "轻弩", "盗贼工具", "鲁特琴"],
            "features": [
                {"name": "吟游激励", "description": "附赠动作给予一名可见盟友1枚d6激励骰；长休恢复。"},
                {"name": "施法", "description": "魅力是施法关键属性；法术豁免DC 13，法术攻击+5。"},
                {"name": "技能多面手（预告）", "description": "升到2级后获得；未熟练能力检定加入一半熟练加值。"},
            ],
            "actions": [
                combat_action("刺剑", "近战武器攻击；请掷d20+5，最终总值需达到目标AC。", "1d8+3 穿刺", "5尺", "piercing", attack_bonus=5),
                combat_action("轻弩", "远程武器攻击；80尺内正常，超过80尺至320尺按远距离劣势处理，近身射击也可能不利。", "1d8+3 穿刺", "320尺（正常80尺）", "piercing", attack_bonus=5),
                combat_action("恶言相加", "目标进行感知豁免；失败受伤并在下一次攻击检定中承受劣势。", "1d6 心灵", "60尺", "psychic", save_ability="wisdom", save_dc=13),
                combat_action("不谐低语", "目标感知豁免；成功减半，失败后需远离施法者。", "3d6 心灵", "60尺", "psychic", save_ability="wisdom", save_dc=13, resource_key="spell_slots_1", resource_cost=1, half_damage_on_save=True),
                combat_action("雷鸣波", "以自身为起点15尺立方范围；体质豁免，失败被推开10尺。", "2d8 雷鸣", "自身；15尺立方", "thunder", save_ability="constitution", save_dc=13, resource_key="spell_slots_1", resource_cost=1, half_damage_on_save=True),
                combat_action("治愈真言", "60尺内治疗可见生物；使用附赠动作和1环法术位。", "2d4+3 治疗", "60尺", "healing", cost="附赠动作", resource_key="spell_slots_1", resource_cost=1),
            ],
            "spells": [
                {"name": "法师之手", "spell_level": 0, "prepared": True, "range": "30尺", "description": "操纵轻小物体，适合拉杆、取物和试探机关。", "resolution_kind": "narrative"},
                {"name": "妖火", "spell_level": 1, "prepared": True, "range": "60尺；20尺立方", "save_ability": "dexterity", "save_dc": 13, "description": "失败目标发光，针对它的攻击可能获得优势。", "resource_key": "spell_slots_1", "resource_cost": 1, "resolution_kind": "narrative"},
            ],
            "spellcasting": {"ability": "魅力", "save_dc": 13, "attack_bonus": 5, "mode": "slots"},
            "resources": {
                "spell_slots_1": {"label": "1环法术位", "current": 2, "max": 2, "recovery": "long_rest"},
                "bardic_inspiration": {"label": "吟游激励d6", "current": 3, "max": 3, "recovery": "long_rest"},
            },
            "inventory": [
                {"name": "治疗药水", "quantity": 2, "unit_weight_lb": 0.5, "price_gp": 50},
                {"name": "50尺麻绳", "quantity": 1, "unit_weight_lb": 10, "price_gp": 1},
                {"name": "粉笔", "quantity": 5, "unit_weight_lb": 0, "price_gp": 0.01},
            ],
            "equipment": ["皮甲", "刺剑", "轻弩", "鲁特琴", "盗贼工具"],
            "notes": "推荐新手预生成角色；既能社交调查，也能体验武器、治疗、攻击法术、豁免法术和范围效果。",
        },
    )
    assets = create_assets(prefix, character)

    ally = post(
        f"{prefix}/npcs",
        {
            "name": "村卫学徒玛拉",
            "description": "紧张但可靠的年轻卫兵。她只负责保护、扶起和提供简单提示，不替玩家做决定。",
            "attitude": "friendly",
            "goal": "证明自己能保护村民",
            "fear": "同伴因自己的鲁莽受伤",
            "armor_class": 15,
            "hp": 11,
            "max_hp": 11,
            "speed": 30,
            "ability_scores": {"strength": 13, "dexterity": 12, "constitution": 14, "intelligence": 10, "wisdom": 12, "charisma": 11},
            "known_information": "知道旧路有断桥，也听见磨坊方向每晚响一次钟。",
            "actions": [combat_action("长矛", "优先保护莉亚，不抢最后一击。", "1d6+1 穿刺", "5尺或20尺", "piercing", attack_bonus=3)],
            "equipment": ["链甲衫", "长矛", "治疗包"],
            "location_id": tavern["id"],
        },
    )
    innkeeper = post(
        f"{prefix}/npcs",
        {
            "name": "店主奥尔莎",
            "description": "说话直接的旅店老板兼临时委托人。",
            "attitude": "friendly",
            "goal": "找回失踪的磨坊工头并恢复村里的面粉供应",
            "fear": "真相会牵连村长",
            "armor_class": 10,
            "hp": 8,
            "max_hp": 8,
            "ability_scores": {"wisdom": 14, "charisma": 13},
            "known_information": "昨夜钟响后，一名矮小身影从磨坊方向跑进树林。",
            "secrets": "她在工头留下的账本上看见村长签名，但暂时不敢公开。",
            "location_id": tavern["id"],
        },
    )
    tinker = post(
        f"{prefix}/npcs",
        {
            "name": "啮齿·铜帽",
            "description": "被误认为入侵者的狗头人修补匠，满身齿轮油，真正目的是阻止蓄能轮爆炸。",
            "attitude": "suspicious",
            "goal": "修好主轴并救出被困族人",
            "fear": "人类先动手而不听解释",
            "armor_class": 12,
            "hp": 7,
            "max_hp": 7,
            "speed": 30,
            "ability_scores": {"strength": 7, "dexterity": 15, "constitution": 9, "intelligence": 14, "wisdom": 10, "charisma": 11},
            "known_information": "知道关闭失控机关需要黄铜钥匙或成功操作两处拉杆。",
            "secrets": "拿走面粉只是为了喂养躲在地下的幼崽。",
            "actions": [combat_action("投石索", "只有被逼入绝境才会攻击。", "1d4+2 钝击", "30尺", "bludgeoning", attack_bonus=4)],
            "location_id": mill["id"],
        },
    )

    rat = post(
        f"{prefix}/monsters",
        {
            "name": "饥饿巨鼠",
            "source_record_id": "giant-rat-2024",
            "source_name": "Giant Rat",
            "armor_class": 12,
            "hp": 7,
            "max_hp": 7,
            "speed": 30,
            "ability_scores": {"strength": 7, "dexterity": 15, "constitution": 11, "intelligence": 2, "wisdom": 10, "charisma": 4},
            "challenge_rating": "1/8",
            "actions": [combat_action("啃咬", "近战攻击；优先攻击最近目标。", "1d4+2 穿刺", "5尺", "piercing", attack_bonus=4)],
            "notes": "官方巨鼠模板；教学战敌人。",
        },
    )
    rat_two = post(
        f"{prefix}/monsters",
        {
            "name": "磨坊巨鼠",
            "source_record_id": "giant-rat-2024",
            "source_name": "Giant Rat",
            "armor_class": 12,
            "hp": 7,
            "max_hp": 7,
            "speed": 30,
            "ability_scores": {"strength": 7, "dexterity": 15, "constitution": 11, "intelligence": 2, "wisdom": 10, "charisma": 4},
            "challenge_rating": "1/8",
            "actions": [combat_action("啃咬", "会绕过障碍接近最近目标。", "1d4+2 穿刺", "5尺", "piercing", attack_bonus=4)],
            "notes": "官方巨鼠模板；最终场景的次要威胁。",
        },
    )
    homunculus = post(
        f"{prefix}/monsters",
        {
            "name": "失控齿轮侍从",
            "source_name": "Animated Armor (scaled template)",
            "armor_class": 13,
            "hp": 16,
            "max_hp": 16,
            "speed": 25,
            "ability_scores": {"strength": 12, "dexterity": 12, "constitution": 12, "intelligence": 3, "wisdom": 8, "charisma": 1},
            "challenge_rating": "1/4",
            "actions": [
                combat_action("齿轮撞击", "近战攻击；命中后发出刺耳钟声。", "1d6+1 钝击", "5尺", "bludgeoning", attack_bonus=3),
                combat_action("蒸汽喷射", "15尺锥形；敏捷豁免DC11，成功减半。", "1d6 火焰", "15尺锥形", "fire", save_ability="dexterity", save_dc=11, half_damage_on_save=True),
            ],
            "notes": "原创怪物，绑定低CR构装体模板；可通过关闭机关使其停机。",
        },
    )

    scene_specs = [
        (
            "Scene 1 · 提灯旅店的委托",
            tavern,
            "玩家在温暖旅店内认识玛拉，查看委托、询问奥尔莎并购买补给。",
            outline("第一章 · 钟声之前", 1, 1, "接受委托并学会查看角色卡、交谈和购买。", "傍晚的雨点敲着窗。墙上委托写着：暮铃磨坊连续三夜无人归来。", "奥尔莎愿付报酬；洞悉可发现她隐瞒了一页账本。", "玛拉主动要求同行，却承认自己从未真正战斗过。", "玩家决定调查方式并领取委托。", "进入林间旧路与断桥。"),
        ),
        (
            "Scene 2 · 林间旧路与断桥",
            road,
            "共享探索网格：断桥、溪流、倒木、兽径、隐藏工具包和可失败前进的环境挑战。",
            outline("第一章 · 钟声之前", 1, 2, "通过断桥并发现磨坊相关线索。", "雨后的溪水漫过桥墩，半截桥板在水面摇晃。", "察觉、求生、运动、巧手或法师之手都可创造通路。", "桥下不是尸体，而是装着黄铜齿轮钥匙的防水包。", "玩家取得线索；失败只会损失时间、资源或HP，不阻断前进。", "看见暮铃磨坊的第一声钟响。"),
        ),
        (
            "Scene 3 · 暮铃磨坊外院",
            mill,
            "外院有木栅、粮车、矮墙和水渠；可潜行、交涉、绕行或进行巨鼠教学战。",
            outline("第二章 · 齿轮之下", 2, 3, "进入磨坊并学习遮挡、视线与战斗回合。", "暮色里，停转的水轮忽然向后跳了一格。粮车后传来抓挠声。", "玩家可潜行观察、用食物引开巨鼠或直接战斗。", "啮齿·铜帽短暂现身并喊：别敲钟！随后逃向地下。", "击退或绕过巨鼠，找到地下入口。", "开启通往地下齿轮工坊的铁门。"),
        ),
        (
            "Scene 4 · 地下齿轮工坊",
            mill,
            "多房间地下网格：维修间、主轴厅、储藏室和控制台由门廊连接，未揭露房间保留战争迷雾。",
            outline("第二章 · 齿轮之下", 2, 4, "查明真相并关闭蓄能轮。", "地下每一次齿轮咬合，都让墙上的铜铃无风自鸣。", "调查日志、撬锁、操作双拉杆或与啮齿交涉都能削弱最终威胁。", "真正危险是村长命人违规加装的蓄能轮；啮齿一直在尝试阻止爆炸。", "在倒计时内谈判、解除机关或击败失控齿轮侍从。", "带着证据和幸存者回到晨溪村。"),
        ),
        (
            "Scene 5 · 晨溪村庆功与升级",
            tavern,
            "尾声：结算任务、战利品、金币、经验、升级和后续钩子。",
            outline("尾声 · 新的旅程", 3, 5, "完成结算并把角色升到2级。", "提灯旅店的门被推开时，整间大厅先安静了一瞬，随后爆发欢呼。", "公开真相、包庇村长或保护啮齿会形成不同关系后果。", "账本最后一页还画着另一座更古老的钟塔。", "DM确认300XP、金币和战利品写入角色。", "预览并确认吟游诗人2级，结束本次冒险。"),
        ),
    ]
    scenes: list[dict[str, Any]] = []
    for name, location, description, notes in scene_specs:
        scenes.append(post(f"{prefix}/scenes", {"name": name, "location_id": location["id"], "description": description, "status": "active", "notes": notes}))

    s1, s2, s3, s4, s5 = scenes
    layouts = assert_duskbell_layouts()
    for scene, layout in zip(scenes, layouts, strict=True):
        create_grid(prefix, scene["id"], layout=layout)

    add_participant(prefix, s1["id"], "character", character, 9, 9)
    add_participant(prefix, s1["id"], "npc", ally, 9, 10)
    add_participant(prefix, s1["id"], "npc", innkeeper, 3, 5)
    add_participant(prefix, s2["id"], "character", character, 7, 4)
    add_participant(prefix, s2["id"], "npc", ally, 8, 4)
    add_participant(prefix, s3["id"], "character", character, 12, 10)
    add_participant(prefix, s3["id"], "npc", ally, 12, 11)
    add_participant(prefix, s3["id"], "npc", tinker, 5, 17, visible=False, role="hidden")
    add_participant(prefix, s3["id"], "monster", rat, 6, 8, visible=False, role="hidden")
    add_participant(prefix, s4["id"], "character", character, 14, 11)
    add_participant(prefix, s4["id"], "npc", ally, 14, 12)
    add_participant(prefix, s4["id"], "npc", tinker, 5, 5, visible=False, role="hidden")
    add_participant(prefix, s4["id"], "monster", rat_two, 3, 18, visible=False, role="hidden")
    add_participant(prefix, s4["id"], "monster", homunculus, 8, 12, visible=False, role="hidden")
    add_participant(prefix, s5["id"], "character", character, 9, 9)
    add_participant(prefix, s5["id"], "npc", ally, 9, 10)
    add_participant(prefix, s5["id"], "npc", innkeeper, 3, 5)
    add_participant(prefix, s5["id"], "npc", tinker, 8, 12)

    bridge_cache = create_object(prefix, s2["id"], object_type="treasure", label="桥下防水工具包", row=8, col=10, state="closed", visibility="hidden", interaction={"action": "search", "dc": 12, "description": "察觉或调查成功后揭露；内有黄铜齿轮钥匙和一瓶治疗药水。"})
    create_object(prefix, s2["id"], object_type="trap", label="松动桥板", row=6, col=8, visibility="public", interaction={"action": "disarm", "tool": "盗贼工具", "dc": 11, "description": "失败则落水并受到1点钝击伤害，但仍可从浅滩继续。"})
    cellar_door = create_object(prefix, s3["id"], object_type="door", label="地下工坊铁门", row=6, col=17, state="closed", visibility="public", interaction={"action": "lockpick", "locked": True, "tool": "盗贼工具", "dc": 12, "description": "黄铜齿轮钥匙可直接打开；撬锁失败会惊动地下生物。"})
    create_object(prefix, s4["id"], object_type="furniture", label="西侧制动拉杆", row=5, col=6, visibility="public", interaction={"action": "operate", "dc": 11, "description": "成功关闭一半蓄能轮；两个拉杆都关闭会停用构装体。"})
    create_object(prefix, s4["id"], object_type="furniture", label="东侧制动拉杆", row=13, col=18, visibility="hidden", interaction={"action": "operate", "dc": 11, "description": "需要先揭露控制室。"})
    create_object(prefix, s4["id"], object_type="furniture", label="违规改造账本", row=12, col=5, visibility="hidden", interaction={"action": "search", "dc": 10, "description": "证明村长下令拆除安全制动器。"})
    create_object(prefix, s4["id"], object_type="trap", label="蓄能轮倒计时", row=8, col=11, visibility="public", interaction={"action": "disarm", "dc": 13, "description": "三次成功前允许一次失败；失败推进危险但不立即结束冒险。"})

    main_quest = post(f"{prefix}/quests", {"name": "主线：让暮铃停下", "description": "调查磨坊钟声、找到失踪工头的线索并阻止地下蓄能轮爆炸。", "quest_type": "main", "giver": "店主奥尔莎", "reward": "25金币、晨溪村英雄徽章、200XP", "xp_reward": 200, "status": "open", "notes": "谈判、解除机关或战斗三种解决方式都算完成。"})
    bridge_quest = post(f"{prefix}/quests", {"name": "支线：桥下的工具包", "description": "安全通过断桥并找回工头遗失的防水工具包。", "quest_type": "side", "giver": "村卫学徒玛拉", "reward": "治疗药水、50XP", "xp_reward": 50, "status": "open"})
    truth_quest = post(f"{prefix}/quests", {"name": "支线：谁改坏了磨坊", "description": "找到违规改造账本，决定公开真相、与村长谈判或保护相关村民。", "quest_type": "side", "giver": "无", "reward": "晨溪村声望、50XP", "xp_reward": 50, "status": "open"})
    clue_specs = [
        ("泥地里的三趾脚印", "泥里有一串小型三趾足迹，方向是磨坊而不是离开磨坊。", "属于狗头人修补匠；它在往返搬运工具。", main_quest, False),
        ("奥尔莎缺失的账页", "账本中少了一页，撕口很新。", "缺页记录了村长批准危险改造。", truth_quest, False),
        ("黄铜齿轮钥匙", "钥匙齿形像半枚齿轮，可开启地下铁门或制动箱。", "也是和平解决终局的关键捷径。", bridge_quest, False),
        ("不是求救的钟声", "钟声每次都在主轴倒转后出现。", "这是过载警报，不是亡灵或邪教仪式。", main_quest, False),
        ("狗头人的粉笔图", "墙上画着两个拉杆和一个被红叉划掉的大齿轮。", "同时操作两拉杆可不经战斗停机构装体。", main_quest, False),
        ("违规改造账本", "工头写道：安全制动器被命令拆除。", "村长为提高产量签字批准改造。", truth_quest, False),
    ]
    clues = [post(f"{prefix}/clues", {"name": name, "description": player_text, "player_text": player_text, "dm_truth": dm_truth, "quest_id": quest["id"], "discovered": discovered}) for name, player_text, dm_truth, quest, discovered in clue_specs]

    handouts = []
    for order, (title, body, published) in enumerate(
        [
            ("新手玩家快速操作卡", "你的回合通常有：移动、1个动作、可能的1个附赠动作。先看战斗面板，再在地图选择合法目标。系统会明确告诉你掷什么骰、加多少以及需要达到的AC/DC。非战斗时可从技能、工具或法术中选择，再点列表目标或直接点地图目标。一次失败不会终止冒险。", True),
            ("暮铃磨坊委托书", "连续三夜，废弃磨坊在日落后自行鸣钟。磨坊工头失踪，村中面粉见底。查明原因并让钟声停止，报酬25金币。", True),
            ("DM手册 · 全模组运行指南", "【节奏】旅店30–40分钟；旧路30分钟；外院40分钟；地下60–90分钟；尾声20分钟。\n【失败前进】检定失败只增加代价：损失时间、资源、位置或少量HP，不隐藏唯一线索。\n【单人平衡】玛拉只保护、治疗和提供一次提示。玩家HP≤4时减少一个敌人或让敌人转向机关。\n【死亡】0HP后先按死亡豁免处理，不再扣成负数；三成功稳定、三失败死亡、自然20恢复1HP。\n【场景】按右侧大纲逐个进入。地下房间和敌人由DM用眼睛按钮揭露。\n【结算】主线200XP，两支线各50XP，合计300XP，足够1→2级。战斗规避或谈判同样给XP。", False),
            ("DM手册 · NPC动机与扮演", "奥尔莎：直接、担忧生计、隐瞒村长签字。玛拉：勇敢但紧张，不替玩家决定。啮齿：语速快、用技术词、被攻击才还手；他不是反派。失控齿轮侍从：没有人格，会在每回合寻找最接近主轴的人。", False),
            ("残缺维修日志（发现后公开）", "……主轴再快一成就能赶上订单。制动器暂时拆除。若铜铃连续响三次，必须同时压下东西两侧拉杆……署名处被油污遮住。", False),
        ]
    ):
        handouts.append(post(f"{prefix}/handouts", {"title": title, "body": body, "published": published, "sort_order": order}))

    for title, description, location in [
        ("模组准备完成", "预生成角色、五个Scene、NPC、怪物、线索、商店与公开手册已就绪。", tavern),
        ("推荐开场", "请玩家从玩家入口加入房间并绑定莉亚·晨歌；DM进入Scene 1后开始朗读。", tavern),
    ]:
        post(f"{prefix}/events", {"title": title, "event_type": "module", "description": description, "location_id": location["id"], "visibility": "dm", "metadata_json": {"module": "duskbell-mill"}})

    merchant_preview = post(
        f"{prefix}/merchants/generate/preview",
        {
            "name": "提灯旅店补给柜",
            "brief": "晨溪村的新手冒险补给，只出售官方基础装备、杂物和低级消耗品；不要原创魔法物品。",
            "location_id": tavern["id"],
            "scene_id": s1["id"],
            "categories": ["adventuring_gear", "consumable"],
            "item_tier": "mundane",
            "character_ids": [character["id"]],
            "stock_size": 12,
            "price_modifier_bps": 10_000,
            "allow_original": False,
            "seed": 20260730,
        },
    )
    merchant = post(f"{prefix}/merchants/generate/confirm", {"preview": merchant_preview})

    room: dict[str, Any] | None = None
    if not args.no_room:
        room = post(f"{prefix}/player-room/open", {"hours": args.room_hours})
        post(f"{prefix}/player-room/live-state", {"scene_id": s1["id"], "combat_id": None})

    result = {
        "module": {"slug": "duskbell-mill", "title": "暮铃磨坊：第一声钟响", "mode": "rehearsal" if args.rehearsal else "delivery", "duration": "2.5–4小时", "players": 1, "dm": 1},
        "campaign": {"id": campaign_id, "name": campaign["name"]},
        "character": {"id": character["id"], "name": character["name"]},
        "support_npc": {"id": ally["id"], "name": ally["name"]},
        "npcs": [{"id": item["id"], "name": item["name"]} for item in (innkeeper, ally, tinker)],
        "monsters": [{"id": item["id"], "name": item["name"]} for item in (rat, rat_two, homunculus)],
        "locations": [{"id": item["id"], "name": item["name"]} for item in (village, tavern, road, mill)],
        "scenes": [{"id": item["id"], "name": item["name"]} for item in scenes],
        "quests": [{"id": item["id"], "name": item["name"], "xp": item["xp_reward"]} for item in (main_quest, bridge_quest, truth_quest)],
        "clues": [{"id": item["id"], "name": item["name"]} for item in clues],
        "handouts": [{"id": item["id"], "title": item["title"], "published": item["published"]} for item in handouts],
        "objects": {"bridge_cache": bridge_cache["id"], "cellar_door": cellar_door["id"]},
        "assets": {key: [item["id"] for item in value] for key, value in assets.items()},
        "merchant": {
            "id": merchant["merchant_id"],
            "name": merchant["merchant"]["name"],
            "stock_count": len(merchant.get("stock", [])),
        },
        "room_code": room["join_code"] if room else None,
        "player_urls": room["urls"] if room else [],
        "dm_run_order": [
            "玩家加入房间并绑定莉亚·晨歌；一起查看公开的新手快速操作卡。",
            "进入Scene 1：社交、洞悉、商店与领取任务。",
            "进入Scene 2：移动、战争迷雾、调查/工具/法师之手与失败前进。",
            "进入Scene 3：潜行或交涉；揭露巨鼠后可开始教学战。",
            "进入Scene 4：逐房揭露，撬锁、双拉杆、真相分支与最终谈判/战斗。",
            "进入Scene 5：确认战利品、金币与总计300XP，再预览并确认升到2级。",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"创建《暮铃磨坊》失败：{exc}", file=sys.stderr)
        raise
