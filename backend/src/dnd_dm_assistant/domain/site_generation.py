from __future__ import annotations

import hashlib
import random
from collections import deque
from typing import Any

ENCOUNTER_BUDGETS = {
    1: (50, 75, 100),
    2: (100, 150, 200),
    3: (150, 225, 400),
    4: (250, 375, 500),
    5: (500, 750, 1100),
    6: (600, 1000, 1400),
    7: (750, 1300, 1700),
    8: (1000, 1700, 2100),
    9: (1300, 2000, 2600),
    10: (1600, 2300, 3100),
    11: (1900, 2900, 4100),
    12: (2200, 3700, 4700),
    13: (2600, 4200, 5400),
    14: (2900, 4900, 6200),
    15: (3300, 5400, 7800),
    16: (3800, 6100, 9800),
    17: (4500, 7200, 11700),
    18: (5000, 8700, 14200),
    19: (5500, 10700, 17200),
    20: (6400, 13200, 22000),
}
DIFFICULTIES = ("low", "moderate", "high")
ROOM_NAMES = {
    "building": ("门厅", "会客厅", "厨房", "卧室", "书房", "储藏室", "礼拜堂", "密室", "走廊"),
    "dungeon": (
        "入口厅",
        "哨戒室",
        "断桥厅",
        "祭坛室",
        "牢房",
        "菌菇洞",
        "藏宝室",
        "仪式厅",
        "首领巢穴",
    ),
}
MONSTERS = {
    "aberration": (("噬脑怪", 450), ("喋喋不休的异怪", 450), ("格雷尔", 700), ("夺心魔", 2900)),
    "undead": (("骷髅", 50), ("僵尸", 50), ("食尸鬼", 200), ("尸妖", 700)),
    "goblin": (("地精", 50), ("大地精", 100), ("熊地精", 200), ("地精首领", 200)),
    "default": (("巨鼠", 25), ("强盗", 25), ("守卫", 25), ("狼", 50)),
}


def _seed(data: dict[str, Any]) -> int:
    supplied = data.get("seed")
    if supplied is not None:
        return int(supplied)
    digest = hashlib.sha256(f"{data['name']}|{data['brief']}".encode()).hexdigest()
    return int(digest[:8], 16)


def _theme(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("夺心魔", "异怪", "心灵", "mind flayer")):
        return "aberration"
    if any(word in lowered for word in ("亡灵", "墓穴", "骷髅", "undead")):
        return "undead"
    if any(word in lowered for word in ("地精", "goblin")):
        return "goblin"
    return "default"


def _connected_slots(rng: random.Random, count: int) -> list[tuple[int, int]]:
    selected = {(1, 1)}
    while len(selected) < count:
        candidates: set[tuple[int, int]] = set()
        for row, col in selected:
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                point = (row + dr, col + dc)
                if 0 <= point[0] < 3 and 0 <= point[1] < 3 and point not in selected:
                    candidates.add(point)
        selected.add(rng.choice(sorted(candidates)))
    return sorted(selected)


def _layout(rng: random.Random, room_count: int, names: tuple[str, ...]) -> dict[str, Any]:
    width, height = 26, 20
    slots = _connected_slots(rng, room_count)
    cells = [
        {"row": row, "col": col, "kind": "void", "label": "地图外区域", "blocks_sight": True}
        for row in range(height)
        for col in range(width)
    ]
    lookup = {(cell["row"], cell["col"]): cell for cell in cells}
    rooms: list[dict[str, Any]] = []
    origins = {(sr, sc): (1 + sr * 6, 1 + sc * 8) for sr, sc in slots}
    for index, slot in enumerate(slots, 1):
        top, left = origins[slot]
        name = names[(index - 1) % len(names)]
        for row in range(top, top + 5):
            for col in range(left, left + 7):
                boundary = row in (top, top + 4) or col in (left, left + 6)
                lookup[(row, col)].update(
                    kind="wall" if boundary else "floor",
                    label="墙壁" if boundary else name,
                    blocks_sight=boundary,
                )
        rooms.append(
            {
                "room_index": index,
                "name": name,
                "room_type": "room",
                "description": f"{name}，包含可调查的环境细节与战术空间。",
                "bounds": {"row": top, "col": left, "width": 7, "height": 5},
                "interactive_objects": [{"name": "可调查物", "interaction": "调查"}],
            }
        )
    index_by_slot = {slot: index + 1 for index, slot in enumerate(slots)}
    connectors: list[dict[str, Any]] = []
    for slot in slots:
        row, col = slot
        for neighbor in ((row + 1, col), (row, col + 1)):
            if neighbor not in index_by_slot:
                continue
            top, left = origins[slot]
            ntop, nleft = origins[neighbor]
            if neighbor[0] != row:
                points = ((top + 4, left + 3), (top + 5, left + 3), (ntop, nleft + 3))
            else:
                points = ((top + 2, left + 6), (top + 2, left + 7), (ntop + 2, nleft))
            for point in points:
                lookup[point].update(kind="door", label="门", blocks_sight=False)
            connectors.append(
                {
                    "from_room_index": index_by_slot[slot],
                    "to_room_index": index_by_slot[neighbor],
                    "connector_type": "door",
                    "label": "房门",
                    "state": "closed",
                    "position": {"row": points[1][0], "col": points[1][1]},
                }
            )
    for room in rng.sample(rooms, k=min(2, len(rooms))):
        bounds = room["bounds"]
        row, col = bounds["row"] + 2, bounds["col"] + 3
        lookup[(row, col)].update(kind="cover", label="掩体", blocks_sight=True)
    return {
        "width": width,
        "height": height,
        "cell_size_ft": 5,
        "grid_type": "square",
        "cells": cells,
        "rooms": rooms,
        "connectors": connectors,
    }


def _monster_plan(theme: str, budget: int) -> list[dict[str, Any]]:
    choices = [item for item in MONSTERS[theme] if item[1] <= max(25, round(budget * 1.25))]
    if not choices:
        return []
    result: list[dict[str, Any]] = []
    remaining = budget
    for name, xp in reversed(choices):
        if remaining <= 0:
            break
        quantity = min(4, remaining // xp)
        if not result and quantity == 0 and xp <= round(budget * 1.25):
            quantity = 1
        if quantity:
            result.append({"name": name, "quantity": quantity, "xp_each": xp, "source": "official"})
            remaining -= quantity * xp
    return result


def generate_site(data: dict[str, Any]) -> dict[str, Any]:
    site_type = str(data["site_type"])
    if site_type not in ROOM_NAMES:
        raise ValueError("site_type must be building or dungeon")
    maximum_levels = int(data.get("maximum_levels", 1))
    if not 1 <= maximum_levels <= 20:
        raise ValueError("maximum_levels must be between 1 and 20")
    seed = _seed(data)
    theme = _theme(f"{data['name']} {data['brief']}")
    region_path = [
        part.strip()
        for part in str(data["region_path"]).replace(">", "/").split("/")
        if part.strip()
    ]
    if not region_path:
        raise ValueError("region_path is required")
    party_level = int(data.get("party_level", 1))
    party_size = int(data.get("party_size", 4))
    starting = DIFFICULTIES.index(str(data.get("starting_difficulty", "low")))
    growth = int(data.get("difficulty_growth", 1))
    reward_rate = float(data.get("reward_rate", 1))
    monster_density = int(data.get("monster_density", 60))
    rooms_min = int(data.get("rooms_min", 3))
    rooms_max = int(data.get("rooms_max", 7))
    if not 2 <= rooms_min <= rooms_max <= 9:
        raise ValueError("rooms must satisfy 2 <= min <= max <= 9")
    rng = random.Random(seed)
    levels: list[dict[str, Any]] = []
    for level_index in range(1, maximum_levels + 1):
        difficulty_index = min(
            2, starting + ((level_index - 1) * growth // max(1, maximum_levels - 1))
        )
        difficulty = DIFFICULTIES[difficulty_index]
        budget = ENCOUNTER_BUDGETS[party_level][difficulty_index] * party_size
        reward = round(
            party_size
            * party_level
            * (10 + party_level * 2)
            * reward_rate
            * (1 + 0.35 * (level_index - 1))
        )
        room_count = rng.randint(rooms_min, rooms_max)
        layout = _layout(rng, room_count, ROOM_NAMES[site_type])
        levels.append(
            {
                "level_index": level_index,
                "name": ("第" + str(level_index) + "层")
                if site_type == "building"
                else f"地下城第 {level_index} 层",
                "description": f"{data['brief']}（{difficulty} 难度）",
                "difficulty": difficulty,
                "encounter_budget_xp": budget,
                "reward_budget_gp": reward,
                "layout": {
                    key: value
                    for key, value in layout.items()
                    if key not in ("rooms", "connectors")
                },
                "rooms": layout["rooms"],
                "connectors": layout["connectors"],
                "monster_plan": _monster_plan(
                    theme, round(budget * monster_density / 100)
                ),
                "reward_plan": [{"name": "金币与等价战利品", "value_gp": reward}],
            }
        )
    for current, following in zip(levels, levels[1:], strict=False):
        current["connectors"].append(
            {
                "from_room_index": current["rooms"][-1]["room_index"],
                "to_level_index": following["level_index"],
                "to_room_index": following["rooms"][0]["room_index"],
                "connector_type": "stairs_down",
                "label": "通往下一层",
                "state": "open",
                "position": {"row": 3, "col": 3},
            }
        )
    return {
        "schema_version": "1.0",
        "site": {
            "site_type": site_type,
            "name": str(data["name"]).strip(),
            "brief": str(data["brief"]).strip(),
            "theme": theme,
            "seed": seed,
            "maximum_levels": maximum_levels,
            "party_level": party_level,
            "party_size": party_size,
            "generation_parameters": {
                "rooms_min": rooms_min,
                "rooms_max": rooms_max,
                "starting_difficulty": DIFFICULTIES[starting],
                "difficulty_growth": growth,
                "reward_rate": reward_rate,
                "monster_density": monster_density,
            },
        },
        "region": {"path": region_path, "name": region_path[-1]},
        "levels": levels,
        "warnings": ["奖励为规划预算；具体魔法物品仍需 DM 按当前规则版本确认。"],
    }


def layout_is_connected(layout: dict[str, Any]) -> bool:
    cells = {
        (int(cell["row"]), int(cell["col"]))
        for cell in layout.get("cells", [])
        if cell.get("kind") not in ("void", "wall")
    }
    if not cells:
        return False
    seen = {next(iter(cells))}
    queue = deque(seen)
    while queue:
        row, col = queue.popleft()
        for neighbor in ((row + 1, col), (row - 1, col), (row, col + 1), (row, col - 1)):
            if neighbor in cells and neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen == cells
