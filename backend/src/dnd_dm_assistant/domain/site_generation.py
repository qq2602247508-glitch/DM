from __future__ import annotations

import hashlib
import math
import random
from collections import deque
from dataclasses import dataclass
from statistics import mean, pstdev
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
ROOM_SIZE_PRESETS = {
    "small": (4, 6),
    "medium": (6, 10),
    "large": (8, 14),
    "huge": (12, 20),
}
MAP_SIZE_PRESETS = {
    "small": (36, 26),
    "medium": (48, 34),
    "large": (64, 46),
    "huge": (82, 60),
}
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
    "sahuagin": (
        ("鲨华鱼人", 100),
        ("鲨华祭司", 450),
        ("寻猎鲨", 450),
        ("鲨华女祭司", 450),
        ("鲨华鱼人男爵", 1800),
        ("底栖魔鱼", 5900),
    ),
    "cult": (("邪教徒", 25), ("邪教狂信徒", 450), ("祭司", 450), ("法师", 2300)),
    "fire": (("岩浆怪", 100), ("火蛇", 200), ("炼狱犬", 700), ("火元素", 1800)),
    "frost": (("冰魔蝠", 50), ("冬狼", 700), ("雪人", 700), ("霜巨人", 3900)),
    "default": (("巨鼠", 25), ("强盗", 25), ("守卫", 25), ("狼", 50)),
}
THEME_PROFILES: dict[str, dict[str, Any]] = {
    "sahuagin": {
        "label": "鲨华鱼人 / 深海",
        "palette": "ocean",
        "wall_label": "潮湿岩壁",
        "cover_label": "珊瑚柱",
        "room_names": (
            "潮门入口",
            "积水哨室",
            "断船厅",
            "贝壳祭坛",
            "盐渍牢房",
            "育卵池",
            "珊瑚藏宝室",
            "潮汐仪式厅",
            "鲨华男爵巢穴",
        ),
        "loot": (
            ("潮汐珍珠", "treasure"),
            ("鲨华祭司的防水卷轴匣", "adventuring_gear"),
            ("深海珊瑚护符", "wondrous"),
        ),
    },
    "aberration": {"label": "异怪污染", "palette": "violet"},
    "undead": {"label": "亡灵墓穴", "palette": "ashen"},
    "goblin": {"label": "地精巢穴", "palette": "moss"},
    "cult": {
        "label": "邪教仪式",
        "palette": "violet",
        "room_names": (
            "伪装入口",
            "信徒宿舍",
            "献祭准备室",
            "亵渎祭坛",
            "囚禁室",
            "经卷库",
            "圣物密藏",
            "召唤仪式厅",
            "教首密室",
        ),
        "loot": (("被亵渎的圣徽", "treasure"), ("仪式经卷匣", "adventuring_gear")),
    },
    "fire": {
        "label": "火山与熔岩",
        "palette": "ember",
        "room_names": (
            "焦岩入口",
            "熔渣哨站",
            "岩浆断桥",
            "火焰祭坛",
            "冷却石牢",
            "硫磺洞",
            "黑曜石宝库",
            "熔炉仪式厅",
            "炎兽巢穴",
        ),
        "loot": (("黑曜石火晶", "treasure"), ("耐热炼金器具", "adventuring_gear")),
    },
    "frost": {
        "label": "冰窟与霜寒",
        "palette": "ice",
        "room_names": (
            "覆霜入口",
            "冰墙哨室",
            "裂隙冰桥",
            "霜纹祭坛",
            "冻牢",
            "蓝冰洞",
            "寒晶宝库",
            "极光仪式厅",
            "霜兽巢穴",
        ),
        "loot": (("永冻寒晶", "treasure"), ("保温远行装备", "adventuring_gear")),
    },
    "default": {"label": "通用地下城", "palette": "amber"},
}


def _seed(data: dict[str, Any]) -> int:
    supplied = data.get("seed")
    if supplied is not None:
        return int(supplied)
    digest = hashlib.sha256(f"{data['name']}|{data['brief']}".encode()).hexdigest()
    return int(digest[:8], 16)


def _theme(text: str) -> str:
    lowered = text.lower()
    if any(
        word in lowered
        for word in (
            "渔人",
            "鱼人",
            "鲨华",
            "深海",
            "海底",
            "潮汐",
            "sahuagin",
            "fish folk",
        )
    ):
        return "sahuagin"
    if any(word in lowered for word in ("夺心魔", "异怪", "心灵", "mind flayer")):
        return "aberration"
    if any(word in lowered for word in ("亡灵", "墓穴", "骷髅", "undead")):
        return "undead"
    if any(word in lowered for word in ("地精", "goblin")):
        return "goblin"
    if any(word in lowered for word in ("邪教", "献祭", "异端", "cult")):
        return "cult"
    if any(word in lowered for word in ("火山", "岩浆", "熔炉", "烈焰", "inferno")):
        return "fire"
    if any(word in lowered for word in ("冰窟", "冰川", "霜寒", "冻原", "frost")):
        return "frost"
    return "default"


@dataclass(frozen=True)
class Rect:
    top: int
    left: int
    bottom: int
    right: int

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[int, int]:
        return ((self.top + self.bottom) // 2, (self.left + self.right) // 2)


def _blank_cells(
    width: int, height: int
) -> tuple[list[dict[str, Any]], dict[tuple[int, int], dict[str, Any]]]:
    cells: list[dict[str, Any]] = [
        {"row": row, "col": col, "kind": "wall", "label": "地图外区域", "blocks_sight": True}
        for row in range(height)
        for col in range(width)
    ]
    return cells, {(int(cell["row"]), int(cell["col"])): cell for cell in cells}


def _room_record(index: int, name: str, rect: Rect, room_type: str = "room") -> dict[str, Any]:
    return {
        "room_index": index,
        "name": name,
        "room_type": room_type,
        "description": f"{name}，面积约 {rect.area * 25} 平方尺，包含可调查细节与战术空间。",
        "bounds": {
            "row": rect.top,
            "col": rect.left,
            "width": rect.width,
            "height": rect.height,
        },
        "interactive_objects": [{"name": f"{name}内的可调查物", "interaction": "调查"}],
    }


def _building_names(brief: str, level_index: int) -> tuple[str, ...]:
    lowered = brief.lower()
    if "酒馆" in lowered or "旅店" in lowered:
        if level_index == 1:
            return (
                "公共大厅",
                "吧台",
                "厨房",
                "门厅",
                "包间",
                "储藏室",
                "楼梯间",
                "办公室",
                "客房",
            )
        if level_index == 2:
            return (
                "客房",
                "豪华客房",
                "公共起居室",
                "盥洗室",
                "布草间",
                "楼梯间",
                "包间",
                "办公室",
            )
        return ("酒窖", "储藏室", "酿酒间", "秘密包间", "地窖走廊", "楼梯间", "守夜人房")
    if "教堂" in lowered or "神殿" in lowered:
        return ("主礼拜堂", "祭衣间", "祈祷室", "藏经室", "牧师房", "钟楼间", "地下墓室", "储物间")
    if level_index == 1:
        return ("主会客厅", "门厅", "餐厅", "厨房", "书房", "储藏室", "仆役间", "楼梯厅", "密室")
    return ("起居大厅", "主卧室", "客卧", "书房", "更衣室", "浴室", "楼梯厅", "储藏室", "密室")


def _split_building(
    rng: random.Random, footprint: Rect, target_count: int, minimum_span: int
) -> tuple[list[Rect], list[dict[str, Any]]]:
    leaves = [footprint]
    partitions: list[dict[str, Any]] = []
    while len(leaves) < target_count:
        candidates = [
            rect
            for rect in leaves
            if rect.width >= minimum_span * 2 + 1 or rect.height >= minimum_span * 2 + 1
        ]
        if not candidates:
            break
        rect = max(candidates, key=lambda item: item.area * rng.uniform(0.8, 1.2))
        orientations: list[str] = []
        if rect.width >= minimum_span * 2 + 1:
            orientations.append("vertical")
        if rect.height >= minimum_span * 2 + 1:
            orientations.append("horizontal")
        if rect.width / max(1, rect.height) > 1.35 and "vertical" in orientations:
            orientation = "vertical"
        elif rect.height / max(1, rect.width) > 1.35 and "horizontal" in orientations:
            orientation = "horizontal"
        else:
            orientation = rng.choice(orientations)
        if orientation == "vertical":
            low, high = rect.left + minimum_span, rect.right - minimum_span
            split = rng.randint(low, high)
            children = (
                Rect(rect.top, rect.left, rect.bottom, split - 1),
                Rect(rect.top, split + 1, rect.bottom, rect.right),
            )
            partition = {
                "orientation": orientation,
                "fixed": split,
                "start": rect.top,
                "end": rect.bottom,
            }
        else:
            low, high = rect.top + minimum_span, rect.bottom - minimum_span
            split = rng.randint(low, high)
            children = (
                Rect(rect.top, rect.left, split - 1, rect.right),
                Rect(split + 1, rect.left, rect.bottom, rect.right),
            )
            partition = {
                "orientation": orientation,
                "fixed": split,
                "start": rect.left,
                "end": rect.right,
            }
        leaves.remove(rect)
        leaves.extend(children)
        partitions.append(partition)
    return leaves, partitions


def _add_building_furnishings(
    lookup: dict[tuple[int, int], dict[str, Any]],
    rect: Rect,
    name: str,
    rng: random.Random,
) -> list[dict[str, str]]:
    if "公共大厅" in name or "起居" in name:
        labels = ["桌椅", "桌椅", "桌椅", "壁炉"]
    elif "吧台" in name:
        labels = ["吧台", "吧台", "酒桶", "酒架"]
    elif "厨房" in name or "酿酒" in name:
        labels = ["炉灶", "备餐台", "水槽", "酒桶"]
    elif "客房" in name or "卧" in name or "守夜人房" in name:
        labels = ["床铺", "衣柜", "小桌"]
    elif "储藏" in name or "布草" in name or "酒窖" in name:
        labels = ["木箱", "酒桶", "货架"]
    elif "书房" in name or "办公室" in name:
        labels = ["书架", "书桌", "文件柜"]
    elif "礼拜" in name or "祈祷" in name:
        labels = ["祭坛", "长椅", "烛台"]
    elif "包间" in name:
        labels = ["圆桌", "座椅", "酒柜"]
    else:
        labels = ["桌椅", "储物柜"]
    candidates = [
        (row, col)
        for row in range(rect.top, rect.bottom + 1)
        for col in range(rect.left, rect.right + 1)
        if lookup[(row, col)]["kind"] == "floor"
        and (row, col) != rect.center
        and (row in (rect.top, rect.bottom) or col in (rect.left, rect.right))
    ]
    rng.shuffle(candidates)
    interactive: list[dict[str, str]] = []
    for label, point in zip(labels, candidates, strict=False):
        lookup[point].update(
            kind="cover",
            label=label,
            blocks_sight=label in {"吧台", "酒架", "货架", "书架", "衣柜", "文件柜"},
        )
        interactive.append({"name": label, "interaction": "调查或互动"})
    return interactive


def _partition_doors(
    rng: random.Random,
    partitions: list[dict[str, Any]],
    leaves: list[Rect],
    lookup: dict[tuple[int, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    connectors: list[dict[str, Any]] = []
    for partition in partitions:
        if partition["orientation"] == "vertical":
            col = partition["fixed"]
            candidates = [
                (row, col)
                for row in range(partition["start"] + 1, partition["end"])
                if lookup[(row, col - 1)]["kind"] == "floor"
                and lookup[(row, col + 1)]["kind"] == "floor"
            ]
        else:
            row = partition["fixed"]
            candidates = [
                (row, col)
                for col in range(partition["start"] + 1, partition["end"])
                if lookup[(row - 1, col)]["kind"] == "floor"
                and lookup[(row + 1, col)]["kind"] == "floor"
            ]
        if not candidates:
            continue
        door = rng.choice(candidates)
        lookup[door].update(kind="door", label="门", blocks_sight=False)
        neighbor_points = (
            ((door[0], door[1] - 1), (door[0], door[1] + 1))
            if partition["orientation"] == "vertical"
            else ((door[0] - 1, door[1]), (door[0] + 1, door[1]))
        )
        adjoining = [
            next(
                (
                    index + 1
                    for index, rect in enumerate(leaves)
                    if rect.top <= point[0] <= rect.bottom and rect.left <= point[1] <= rect.right
                ),
                1,
            )
            for point in neighbor_points
        ]
        connectors.append(
            {
                "from_room_index": adjoining[0],
                "to_room_index": adjoining[1],
                "connector_type": "door",
                "label": "房门",
                "state": "closed",
                "position": {"row": door[0], "col": door[1]},
            }
        )
    return connectors


def _building_layout(
    rng: random.Random,
    room_count: int,
    brief: str,
    level_index: int,
    overall_scale: str,
    minimum_room_size: str,
) -> dict[str, Any]:
    base_width, base_height = MAP_SIZE_PRESETS[overall_scale]
    width = min(99, base_width + rng.randrange(-3, 4, 2))
    height = min(99, base_height + rng.randrange(-3, 4, 2))
    minimum_span = ROOM_SIZE_PRESETS[minimum_room_size][0]
    cells, lookup = _blank_cells(width, height)
    top, left, bottom, right = 2, 2, height - 3, width - 3
    side_zone: Rect | None = None
    split_col = -1
    if room_count >= 5:
        split_col = left + round((right - left) * rng.uniform(0.52, 0.62))
        wing_edge = top + round((bottom - top) * rng.uniform(0.48, 0.62))
        main_zone = Rect(top, left, bottom, split_col - 1)
        side_zone = (
            Rect(top, split_col + 1, wing_edge, right)
            if rng.random() < 0.5
            else Rect(wing_edge, split_col + 1, bottom, right)
        )
        main_count = min(room_count - 2, max(3, round(room_count * 0.62)))
        main_leaves, main_partitions = _split_building(
            rng, main_zone, main_count, minimum_span
        )
        side_leaves, side_partitions = _split_building(
            rng, side_zone, room_count - main_count, minimum_span
        )
        leaves = [*main_leaves, *side_leaves]
        partitions = [*main_partitions, *side_partitions]
        outline = "l_shape"
    else:
        main_zone = Rect(top, left, bottom, right)
        leaves, partitions = _split_building(rng, main_zone, room_count, minimum_span)
        outline = "compact"
    ordered = sorted(leaves, key=lambda rect: (-rect.area, rect.top, rect.left))
    names = _building_names(brief, level_index)
    named = {rect: names[index % len(names)] for index, rect in enumerate(ordered)}
    for rect in leaves:
        for row in range(rect.top, rect.bottom + 1):
            for col in range(rect.left, rect.right + 1):
                lookup[(row, col)].update(kind="floor", label="地板", blocks_sight=False)
    floor_points = {point for point, cell in lookup.items() if cell["kind"] == "floor"}
    for row, col in floor_points:
        for point in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            if point in lookup and lookup[point]["label"] == "地图外区域":
                lookup[point].update(kind="wall", label="外墙", blocks_sight=True)
    for partition in partitions:
        if partition["orientation"] == "vertical":
            for row in range(partition["start"], partition["end"] + 1):
                lookup[(row, partition["fixed"])].update(
                    kind="wall", label="内墙", blocks_sight=True
                )
        else:
            for col in range(partition["start"], partition["end"] + 1):
                lookup[(partition["fixed"], col)].update(
                    kind="wall", label="内墙", blocks_sight=True
                )
    connectors = _partition_doors(rng, partitions, leaves, lookup)
    if side_zone is not None:
        bridge_candidates = [
            (row, split_col)
            for row in range(
                max(main_zone.top, side_zone.top), min(main_zone.bottom, side_zone.bottom) + 1
            )
            if lookup[(row, split_col - 1)]["kind"] == "floor"
            and lookup[(row, split_col + 1)]["kind"] == "floor"
        ]
        if not bridge_candidates:
            raise ValueError("could not connect building wings")
        bridge = rng.choice(bridge_candidates)
        lookup[bridge].update(kind="door", label="翼廊门", blocks_sight=False)
        adjoining = [
            next(
                index + 1
                for index, rect in enumerate(leaves)
                if rect.top <= bridge[0] <= rect.bottom
                and rect.left <= bridge[1] + offset <= rect.right
            )
            for offset in (-1, 1)
        ]
        connectors.append(
            {
                "from_room_index": adjoining[0],
                "to_room_index": adjoining[1],
                "connector_type": "door",
                "label": "连接主翼与侧翼",
                "state": "closed",
                "position": {"row": bridge[0], "col": bridge[1]},
            }
        )
    room_index = {rect: index + 1 for index, rect in enumerate(leaves)}
    rooms = [_room_record(room_index[rect], named[rect], rect, "building_room") for rect in leaves]
    for rect in leaves:
        lookup[rect.center].update(kind="room", label=named[rect], blocks_sight=False)
    room_by_index = {int(room["room_index"]): room for room in rooms}
    furniture_labels: set[str] = set()
    for rect in leaves:
        interactive = _add_building_furnishings(lookup, rect, named[rect], rng)
        room_by_index[room_index[rect]]["interactive_objects"] = interactive
        furniture_labels.update(item["name"] for item in interactive)
    return {
        "width": width,
        "height": height,
        "cell_size_ft": 5,
        "grid_type": "square",
        "algorithm": "building_wings_bsp",
        "outline": outline,
        "furniture_labels": sorted(furniture_labels),
        "cells": cells,
        "rooms": rooms,
        "connectors": connectors,
    }


def _overlaps_with_margin(candidate: Rect, rooms: list[Rect], margin: int = 2) -> bool:
    return any(
        candidate.left - margin <= room.right
        and candidate.right + margin >= room.left
        and candidate.top - margin <= room.bottom
        and candidate.bottom + margin >= room.top
        for room in rooms
    )


def _dungeon_layout(
    rng: random.Random,
    room_count: int,
    brief: str,
    level_index: int,
    overall_scale: str,
    minimum_room_size: str,
    maximum_room_size: str,
    party_size: int,
) -> dict[str, Any]:
    width, height = MAP_SIZE_PRESETS[overall_scale]
    theme = _theme(brief)
    profile = THEME_PROFILES.get(theme, THEME_PROFILES["default"])
    minimum_span = ROOM_SIZE_PRESETS[minimum_room_size][0]
    maximum_span = ROOM_SIZE_PRESETS[maximum_room_size][1]
    # A selected party needs at least one genuine tactical room.  Small side
    # chambers remain possible, but the main chamber must support movement,
    # cover and common area templates instead of degenerating to 4×5 boxes.
    tactical_span = min(maximum_span, max(8, 6 + math.ceil(max(0, party_size - 4) / 2)))
    cells, lookup = _blank_cells(width, height)
    rects: list[Rect] = []
    for _ in range(500):
        if len(rects) >= room_count:
            break
        room_width = rng.randint(minimum_span, maximum_span)
        room_height = rng.randint(minimum_span, maximum_span)
        if not rects:
            room_width = max(room_width, tactical_span)
            room_height = max(room_height, tactical_span)
        candidate = Rect(
            rng.randint(2, height - room_height - 3),
            rng.randint(2, width - room_width - 3),
            0,
            0,
        )
        candidate = Rect(
            candidate.top,
            candidate.left,
            candidate.top + room_height - 1,
            candidate.left + room_width - 1,
        )
        if not _overlaps_with_margin(candidate, rects):
            rects.append(candidate)
    if len(rects) < max(3, room_count - 1):
        raise ValueError("could not place enough dungeon rooms")
    rects = rects[:room_count]
    for rect in rects:
        for row in range(rect.top, rect.bottom + 1):
            for col in range(rect.left, rect.right + 1):
                lookup[(row, col)].update(kind="floor", label="洞窟地面", blocks_sight=False)
    connected = {0}
    edges: list[tuple[int, int]] = []
    while len(connected) < len(rects):
        edge = min(
            (
                (left, right)
                for left in connected
                for right in range(len(rects))
                if right not in connected
            ),
            key=lambda pair: math.dist(rects[pair[0]].center, rects[pair[1]].center),
        )
        edges.append(edge)
        connected.add(edge[1])
    extra_candidates = [
        (left, right)
        for left in range(len(rects))
        for right in range(left + 1, len(rects))
        if (left, right) not in edges and (right, left) not in edges
    ]
    rng.shuffle(extra_candidates)
    edges.extend(extra_candidates[: max(1, len(rects) // 4)])
    connectors: list[dict[str, Any]] = []
    degrees = [0] * len(rects)
    for edge_index, (left_index, right_index) in enumerate(edges):
        degrees[left_index] += 1
        degrees[right_index] += 1
        start = rects[left_index].center
        end = rects[right_index].center
        if rng.random() < 0.5:
            path = [
                *(
                    (start[0], col)
                    for col in range(min(start[1], end[1]), max(start[1], end[1]) + 1)
                ),
                *((row, end[1]) for row in range(min(start[0], end[0]), max(start[0], end[0]) + 1)),
            ]
        else:
            path = [
                *(
                    (row, start[1])
                    for row in range(min(start[0], end[0]), max(start[0], end[0]) + 1)
                ),
                *((end[0], col) for col in range(min(start[1], end[1]), max(start[1], end[1]) + 1)),
            ]
        for point in path:
            lookup[point].update(kind="floor", label="通道", blocks_sight=False)
        door = next(
            (
                point
                for point in path
                if point
                not in {
                    (row, col)
                    for row in range(rects[left_index].top, rects[left_index].bottom + 1)
                    for col in range(rects[left_index].left, rects[left_index].right + 1)
                }
            ),
            path[len(path) // 2],
        )
        connector_type = (
            "secret_door" if edge_index == len(edges) - 1 and len(edges) >= len(rects) else "door"
        )
        lookup[door].update(
            kind="door",
            label="暗门" if connector_type == "secret_door" else "门",
            blocks_sight=connector_type == "secret_door",
        )
        connectors.append(
            {
                "from_room_index": left_index + 1,
                "to_room_index": right_index + 1,
                "connector_type": connector_type,
                "label": "隐藏通道" if connector_type == "secret_door" else "石门",
                "state": "hidden" if connector_type == "secret_door" else "closed",
                "position": {"row": door[0], "col": door[1]},
            }
        )
    walkable = {point for point, cell in lookup.items() if cell["kind"] in ("floor", "door")}
    for row, col in walkable:
        for neighbor in (
            (row + 1, col),
            (row - 1, col),
            (row, col + 1),
            (row, col - 1),
        ):
            if (
                neighbor in lookup
                and lookup[neighbor]["kind"] == "wall"
                and lookup[neighbor]["label"] == "地图外区域"
            ):
                lookup[neighbor].update(
                    kind="wall",
                    label=str(profile.get("wall_label") or "岩壁"),
                    blocks_sight=True,
                )
    names = tuple(profile.get("room_names") or ROOM_NAMES["dungeon"])
    ordered = sorted(range(len(rects)), key=lambda index: (-rects[index].area, index))
    assigned: dict[int, str] = {}
    for rank, index in enumerate(ordered):
        if rank == 0:
            assigned[index] = (
                str(names[0])
                if theme == "sahuagin" and level_index < 3
                else str(names[-1])
                if theme == "sahuagin"
                else "主洞厅"
                if level_index < 3
                else "首领巢穴"
            )
        elif degrees[index] == 1 and rank == len(ordered) - 1:
            assigned[index] = "隐秘藏宝室"
        else:
            assigned[index] = names[(rank + level_index - 1) % len(names)]
    rooms = [
        _room_record(index + 1, assigned[index], rect, "dungeon_room")
        for index, rect in enumerate(rects)
    ]
    for index, rect in enumerate(rects):
        lookup[rect.center].update(kind="room", label=assigned[index], blocks_sight=False)
    for index in ordered[: min(3, len(ordered))]:
        rect = rects[index]
        point = (rect.center[0], min(rect.right, rect.center[1] + 1))
        if lookup[point]["kind"] == "floor":
            lookup[point].update(
                kind="cover",
                label=str(profile.get("cover_label") or "岩柱"),
                blocks_sight=True,
            )
    # Later corridor carving and room labels may cross an earlier connector.
    # Re-assert connector cells after all decorative passes so persisted
    # connector metadata always lands on a real door cell.
    for connector in connectors:
        position = connector["position"]
        lookup[(int(position["row"]), int(position["col"]))].update(
            kind="door",
            label="暗门" if connector["connector_type"] == "secret_door" else "门",
            blocks_sight=connector["connector_type"] == "secret_door",
        )
    return {
        "width": width,
        "height": height,
        "cell_size_ft": 5,
        "grid_type": "square",
        "algorithm": "dungeon_rooms_and_corridors",
        "cells": cells,
        "rooms": rooms,
        "connectors": connectors,
        "graph": {"edges": edges, "degrees": degrees},
    }


def score_layout(layout: dict[str, Any], site_type: str) -> dict[str, Any]:
    rooms = layout.get("rooms", [])
    areas = [int(room["bounds"]["width"]) * int(room["bounds"]["height"]) for room in rooms]
    connectors = layout.get("connectors", [])
    connected = layout_is_connected(layout)
    diversity = pstdev(areas) / mean(areas) if len(areas) > 1 and mean(areas) else 0
    size_ratio = max(areas) / min(areas) if areas else 0
    valid_doors = sum(
        1
        for connector in connectors
        if connector.get("from_room_index") != connector.get("to_room_index")
    )
    walkable = sum(
        1 for cell in layout.get("cells", []) if cell.get("kind") not in ("void", "wall")
    )
    utilization = walkable / max(1, int(layout["width"]) * int(layout["height"]))
    score = 25 if connected else 0
    score += min(20, round(diversity * 60))
    score += min(10, round(max(0, size_ratio - 1) * 8))
    score += min(15, round(15 * valid_doors / max(1, len(rooms) - 1)))
    score += 10 if len(rooms) >= 3 else 0
    if site_type == "building":
        score += 10 if size_ratio >= 1.8 else 0
        score += 10 if 0.35 <= utilization <= 0.85 else 4
        score += 5 if layout.get("outline") == "l_shape" else 0
        score += min(5, len(layout.get("furniture_labels", [])) // 3)
    else:
        graph = layout.get("graph", {})
        degrees = graph.get("degrees", [])
        cycle_count = max(0, len(graph.get("edges", [])) - len(rooms) + 1)
        score += 5 if cycle_count >= 1 else 0
        score += 5 if any(degree == 1 for degree in degrees) else 0
        score += 10 if 0.12 <= utilization <= 0.55 else 4
        largest = max(areas, default=0)
        score += 5 if largest >= 64 else 0
    return {
        "score": min(100, score),
        "connected": connected,
        "room_size_cv": round(diversity, 3),
        "largest_smallest_ratio": round(size_ratio, 2),
        "valid_connectors": valid_doors,
        "walkable_utilization": round(utilization, 3),
        "algorithm": layout.get("algorithm"),
        "outline": layout.get("outline"),
        "furniture_diversity": len(layout.get("furniture_labels", [])),
    }


def _best_layout(
    site_type: str,
    seed: int,
    room_count: int,
    brief: str,
    level_index: int,
    overall_scale: str,
    minimum_room_size: str,
    maximum_room_size: str,
    party_size: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for attempt in range(16):
        rng = random.Random(seed + attempt * 104_729)
        try:
            layout = (
                _building_layout(
                    rng,
                    room_count,
                    brief,
                    level_index,
                    overall_scale,
                    minimum_room_size,
                )
                if site_type == "building"
                else _dungeon_layout(
                    rng,
                    room_count,
                    brief,
                    level_index,
                    overall_scale,
                    minimum_room_size,
                    maximum_room_size,
                    party_size,
                )
            )
        except ValueError:
            continue
        quality = score_layout(layout, site_type)
        candidates.append((layout, quality))
        if quality["score"] >= 88:
            break
    if not candidates:
        raise ValueError("could not generate a valid site layout")
    return max(candidates, key=lambda item: item[1]["score"])


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
            result.append(
                {
                    "name": name,
                    "quantity": quantity,
                    "xp_each": xp,
                    "source": "official",
                    "theme": theme,
                    "encounter_role": (
                        "首领" if xp >= max(450, budget // 3) else "精英" if xp >= 450 else "杂兵"
                    ),
                }
            )
            remaining -= quantity * xp
    return result


def _party_loot_plan(
    class_names: list[str],
    party_level: int,
    budget_gp: int,
    theme: str,
) -> list[dict[str, Any]]:
    """Build a rules-shaped loot mix without pretending homebrew is official."""
    lowered = " ".join(class_names).lower()
    suggestions: list[tuple[str, str, int]] = [
        ("治疗药水", "consumable", max(25, min(100, budget_gp // 5))),
        ("金币与可交易宝物", "treasure", max(1, budget_gp // 2)),
    ]
    if any(name in lowered for name in ("wizard", "法师", "sorcerer", "术士", "warlock", "邪术师")):
        suggestions.append(("与队伍环级相符的法术卷轴", "spell_scroll", max(50, budget_gp // 4)))
    if any(
        name in lowered
        for name in ("fighter", "战士", "paladin", "圣武士", "barbarian", "野蛮人")
    ):
        suggestions.append(("精制武器或护甲材料", "equipment", max(50, budget_gp // 4)))
    if any(name in lowered for name in ("rogue", "游荡者", "ranger", "游侠")):
        suggestions.append(("精制弹药与探索工具", "equipment", max(35, budget_gp // 5)))
    if any(name in lowered for name in ("cleric", "牧师", "druid", "德鲁伊", "bard", "吟游诗人")):
        suggestions.append(("法器材料与恢复性消耗品", "consumable", max(40, budget_gp // 5)))
    profile = THEME_PROFILES.get(theme, {})
    for themed_name, themed_category in profile.get("loot", ()):
        suggestions.append(
            (str(themed_name), str(themed_category), max(25, budget_gp // 6))
        )
    return [
        {
            "name": name,
            "category": category,
            "value_gp": min(value, max(1, budget_gp)),
            "quantity": 1,
            "source_kind": "generated_plan",
            "recommended_level": party_level,
        }
        for name, category, value in suggestions
    ]


def _npc_plan(brief: str, level_index: int) -> list[dict[str, Any]]:
    lowered = brief.lower()
    if _theme(brief) == "sahuagin":
        role = "被放逐的鲨华鱼人向导" if level_index == 1 else "被囚禁的沿海水手"
    elif any(word in lowered for word in ("酒馆", "旅店")):
        role = "酒馆经营者" if level_index == 1 else "住客或雇员"
    elif any(word in lowered for word in ("教堂", "神殿")):
        role = "教堂看守或幸存信徒"
    elif any(word in lowered for word in ("矿坑", "地下城", "洞穴")):
        role = "受困的探险者"
    else:
        role = "地点知情人"
    return [
        {
            "name": role,
            "role": role,
            "attitude": "neutral",
            "source_kind": "original",
            "room_index": 1,
        }
    ]


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
    profiles = [
        profile for profile in data.get("party_profiles", []) if isinstance(profile, dict)
    ]
    configured_level = int(data.get("party_level", 1))
    configured_size = int(data.get("party_size", 4))
    party_size = len(profiles) if profiles else configured_size
    profile_levels = [int(profile.get("level", configured_level)) for profile in profiles]
    party_level = (
        max(1, min(20, round(sum(profile_levels) / len(profile_levels))))
        if profile_levels
        else configured_level
    )
    class_names = [str(profile.get("class_name") or "") for profile in profiles]
    starting = DIFFICULTIES.index(str(data.get("starting_difficulty", "low")))
    growth = int(data.get("difficulty_growth", 1))
    reward_rate = float(data.get("reward_rate", 1))
    monster_density = int(data.get("monster_density", 60))
    rooms_min = int(data.get("rooms_min", 3))
    rooms_max = int(data.get("rooms_max", 7))
    overall_scale = str(data.get("overall_scale", "medium"))
    minimum_room_size = str(data.get("minimum_room_size", "medium"))
    maximum_room_size = str(data.get("maximum_room_size", "large"))
    generate_monsters = bool(data.get("generate_monsters", True))
    generate_npcs = bool(data.get("generate_npcs", True))
    generate_loot = bool(data.get("generate_loot", True))
    if overall_scale not in MAP_SIZE_PRESETS:
        raise ValueError("overall_scale is invalid")
    if minimum_room_size not in ROOM_SIZE_PRESETS or maximum_room_size not in ROOM_SIZE_PRESETS:
        raise ValueError("room size preset is invalid")
    size_order = tuple(ROOM_SIZE_PRESETS)
    if size_order.index(minimum_room_size) > size_order.index(maximum_room_size):
        raise ValueError("minimum_room_size cannot exceed maximum_room_size")
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
        layout, quality = _best_layout(
            site_type,
            seed + level_index * 1_000_003,
            room_count,
            str(data["brief"]),
            level_index,
            overall_scale,
            minimum_room_size,
            maximum_room_size,
            party_size,
        )
        monster_plan = (
            _monster_plan(theme, round(budget * monster_density / 100))
            if generate_monsters
            else []
        )
        reward_plan = (
            _party_loot_plan(class_names, party_level, reward, theme)
            if generate_loot
            else []
        )
        levels.append(
            {
                "level_index": level_index,
                "name": ("第" + str(level_index) + "层")
                if site_type == "building"
                else f"地下城第 {level_index} 层",
                "description": f"{data['brief']}（{difficulty} 难度）",
                "visual_theme": {
                    "theme": theme,
                    "label": str(
                        THEME_PROFILES.get(theme, THEME_PROFILES["default"]).get(
                            "label", theme
                        )
                    ),
                    "palette": str(
                        THEME_PROFILES.get(theme, THEME_PROFILES["default"]).get(
                            "palette", "amber"
                        )
                    ),
                },
                "difficulty": difficulty,
                "encounter_budget_xp": budget,
                "reward_budget_gp": reward,
                "layout": {
                    key: value
                    for key, value in layout.items()
                    if key not in ("rooms", "connectors", "graph")
                },
                "rooms": layout["rooms"],
                "connectors": layout["connectors"],
                "quality": quality,
                "monster_plan": [
                    {**monster, "room_index": (index % len(layout["rooms"])) + 1}
                    for index, monster in enumerate(monster_plan)
                ],
                "npc_plan": _npc_plan(str(data["brief"]), level_index) if generate_npcs else [],
                "reward_plan": [
                    {
                        **item,
                        "room_index": (
                            (index + len(layout["rooms"]) - 1) % len(layout["rooms"])
                        )
                        + 1,
                    }
                    for index, item in enumerate(reward_plan)
                ],
            }
        )
    for current, following in zip(levels, levels[1:], strict=False):
        from_bounds = current["rooms"][-1]["bounds"]
        to_bounds = following["rooms"][0]["bounds"]
        def stair_position(
            level: dict[str, Any], bounds: dict[str, Any]
        ) -> dict[str, int]:
            occupied = {
                (int(connector["position"]["row"]), int(connector["position"]["col"]))
                for connector in level["connectors"]
            }
            center = (
                int(bounds["row"]) + int(bounds["height"]) // 2,
                int(bounds["col"]) + int(bounds["width"]) // 2,
            )
            cells = {
                (int(cell["row"]), int(cell["col"])): cell
                for cell in level["layout"]["cells"]
            }
            candidates = [
                (row, col)
                for row in range(int(bounds["row"]), int(bounds["row"]) + int(bounds["height"]))
                for col in range(int(bounds["col"]), int(bounds["col"]) + int(bounds["width"]))
                if (row, col) not in occupied
                and cells.get((row, col), {}).get("kind") in {"floor", "room"}
            ]
            if not candidates:
                raise ValueError("could not place a non-overlapping staircase")
            row, col = min(
                candidates,
                key=lambda point: (
                    abs(point[0] - center[0]) + abs(point[1] - center[1]),
                    point,
                ),
            )
            return {"row": row, "col": col}

        from_position = stair_position(current, from_bounds)
        to_position = stair_position(following, to_bounds)
        for cell in current["layout"]["cells"]:
            if cell["row"] == from_position["row"] and cell["col"] == from_position["col"]:
                cell.update(kind="stairs", label="向下楼梯", blocks_sight=False)
                break
        for cell in following["layout"]["cells"]:
            if cell["row"] == to_position["row"] and cell["col"] == to_position["col"]:
                cell.update(kind="stairs", label="向上楼梯", blocks_sight=False)
                break
        current["connectors"].append(
            {
                "from_room_index": current["rooms"][-1]["room_index"],
                "to_level_index": following["level_index"],
                "to_room_index": following["rooms"][0]["room_index"],
                "connector_type": "stairs_down",
                "label": "通往下一层",
                "state": "open",
                "position": from_position,
            }
        )
        following["connectors"].append(
            {
                "from_room_index": following["rooms"][0]["room_index"],
                "to_level_index": current["level_index"],
                "to_room_index": current["rooms"][-1]["room_index"],
                "connector_type": "stairs_up",
                "label": "返回上一层",
                "state": "open",
                "position": to_position,
            }
        )
    return {
        "schema_version": "1.0",
        "site": {
            "site_type": site_type,
            "name": str(data["name"]).strip(),
            "brief": str(data["brief"]).strip(),
            "theme": theme,
            "theme_profile": {
                key: value
                for key, value in THEME_PROFILES.get(
                    theme, THEME_PROFILES["default"]
                ).items()
                if key not in {"room_names", "loot"}
            },
            "seed": seed,
            "maximum_levels": maximum_levels,
            "party_level": party_level,
            "party_size": party_size,
            "character_ids": list(data.get("character_ids", [])),
            "generation_parameters": {
                "rooms_min": rooms_min,
                "rooms_max": rooms_max,
                "starting_difficulty": DIFFICULTIES[starting],
                "difficulty_growth": growth,
                "reward_rate": reward_rate,
                "monster_density": monster_density,
                "overall_scale": overall_scale,
                "minimum_room_size": minimum_room_size,
                "maximum_room_size": maximum_room_size,
                "generate_monsters": generate_monsters,
                "generate_npcs": generate_npcs,
                "generate_loot": generate_loot,
                "party_profiles": profiles,
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
