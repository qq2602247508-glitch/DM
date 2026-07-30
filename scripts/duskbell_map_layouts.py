"""Deterministic, scene-specific maps for the Duskbell Mill beginner module."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

Cell = dict[str, Any]
Point = tuple[int, int]


@dataclass(frozen=True)
class DuskbellMapLayout:
    scene_key: str
    width: int
    height: int
    theme: str
    public_description: str
    dm_description: str
    cells: tuple[Cell, ...]

    def layers_json(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "structure": self.scene_key,
            "generator": "duskbell-scene-layouts-2.0",
            "cells": [dict(cell) for cell in self.cells],
        }


class _Cells:
    def __init__(self, width: int, height: int, ground: str) -> None:
        self.width = width
        self.height = height
        self.items: dict[Point, Cell] = {}
        self.rect(1, 1, height, width, "floor", ground)

    def put(
        self,
        row: int,
        col: int,
        kind: str,
        label: str,
        *,
        blocks_sight: bool = False,
    ) -> None:
        if not (1 <= row <= self.height and 1 <= col <= self.width):
            raise ValueError(f"cell outside map: {row},{col}")
        cell: Cell = {"row": row, "col": col, "kind": kind, "label": label}
        if blocks_sight:
            cell["blocks_sight"] = True
        self.items[(row, col)] = cell

    def line(
        self,
        row_1: int,
        col_1: int,
        row_2: int,
        col_2: int,
        kind: str,
        label: str,
        *,
        blocks_sight: bool = False,
    ) -> None:
        if row_1 != row_2 and col_1 != col_2:
            raise ValueError("only orthogonal map lines are supported")
        row_step = 0 if row_1 == row_2 else (1 if row_2 > row_1 else -1)
        col_step = 0 if col_1 == col_2 else (1 if col_2 > col_1 else -1)
        row, col = row_1, col_1
        while True:
            self.put(row, col, kind, label, blocks_sight=blocks_sight)
            if (row, col) == (row_2, col_2):
                return
            row += row_step
            col += col_step

    def rect(
        self,
        row_1: int,
        col_1: int,
        row_2: int,
        col_2: int,
        kind: str,
        label: str,
        *,
        blocks_sight: bool = False,
    ) -> None:
        for row in range(row_1, row_2 + 1):
            for col in range(col_1, col_2 + 1):
                self.put(row, col, kind, label, blocks_sight=blocks_sight)

    def building_boundary(self, label: str, doors: Iterable[tuple[int, int, str]]) -> None:
        self.line(1, 1, 1, self.width, "wall", f"{label}北墙", blocks_sight=True)
        self.line(
            self.height,
            1,
            self.height,
            self.width,
            "wall",
            f"{label}南墙",
            blocks_sight=True,
        )
        self.line(1, 1, self.height, 1, "wall", f"{label}西墙", blocks_sight=True)
        self.line(
            1,
            self.width,
            self.height,
            self.width,
            "wall",
            f"{label}东墙",
            blocks_sight=True,
        )
        for row, col, door_label in doors:
            self.put(row, col, "door", door_label)

    def result(self) -> tuple[Cell, ...]:
        return tuple(self.items[key] for key in sorted(self.items))


def _tavern(*, celebration: bool) -> DuskbellMapLayout:
    width, height = 18, 12
    cells = _Cells(width, height, "旅店木地板")
    cells.building_boundary("提灯旅店", [(12, 9, "旅店正门")])
    cells.line(1, 13, 5, 13, "wall", "厨房隔墙", blocks_sight=True)
    cells.line(5, 13, 5, 18, "wall", "厨房南墙", blocks_sight=True)
    cells.put(4, 13, "door", "厨房门")
    cells.put(3, 15, "room", "厨房")
    cells.put(7, 9, "room", "旅店大厅")
    for col in range(3, 9):
        cells.put(4, col, "cover", "吧台")
    cells.put(3, 16, "cover", "补给货架", blocks_sight=True)
    cells.put(6, 2, "fire", "石砌壁炉")
    cells.put(7, 15, "marker", "新的委托" if celebration else "委托公告板")
    if celebration:
        for col in range(5, 13):
            cells.put(8, col, "cover", "庆功长桌")
        cells.put(6, 5, "marker", "乐手席")
        cells.put(10, 14, "marker", "后续委托席")
        scene_key = "celebration_tavern"
        theme = "lantern-tavern-celebration"
        public = "庆功后的提灯旅店仍是同一座建筑：大厅、吧台、厨房、正门和庆功长桌清晰可辨。"
        dm = "保留第一幕旅店空间记忆，用长桌、乐手席和新委托改变场景功能。"
    else:
        for start_col in (4, 10):
            for col in range(start_col, start_col + 3):
                cells.put(8, col, "cover", "旅店长桌")
        cells.put(10, 15, "marker", "安静谈话角")
        scene_key = "tavern"
        theme = "lantern-tavern"
        public = "提灯旅店一层：大厅、吧台、厨房、壁炉、公告板、补给货架与正门构成完整室内建筑。"
        dm = "奥尔莎的账本藏在吧台下；厨房门和大厅家具形成社交、搜寻与遮挡区域。"
    return DuskbellMapLayout(scene_key, width, height, theme, public, dm, cells.result())


def _forest_crossing() -> DuskbellMapLayout:
    width, height = 20, 14
    cells = _Cells(width, height, "湿润林地")

    # A continuous north-south stream divides the two banks.  The changing
    # starting column makes it read as a natural watercourse rather than a room.
    stream_starts = (9, 9, 9, 10, 10, 10, 9, 9, 9, 8, 8, 8, 9, 9)
    for row, start in enumerate(stream_starts, start=1):
        for col in range(start, start + 4):
            cells.put(row, col, "water", "湍急溪流")
        cells.put(row, start - 1, "difficult", "泥泞西岸")
        cells.put(row, start + 4, "difficult", "碎石东岸")

    # The old road reaches the broken bridge but does not magically span it.
    cells.line(7, 1, 7, 8, "floor", "林间旧路")
    cells.line(7, 13, 7, 20, "floor", "林间旧路")
    cells.put(7, 9, "difficult", "断桥西侧残板")
    cells.put(7, 12, "difficult", "断桥东侧残板")
    cells.put(7, 10, "water", "桥面断口")
    cells.put(7, 11, "water", "桥面断口")

    # Three complete fallback routes ensure failure-forward traversal.
    for col in range(1, width + 1):
        if col <= 8 or col >= 13:
            cells.put(3, col, "difficult", "倒木绕行道")
    for col in range(9, 13):
        cells.put(3, col, "difficult", "横卧倒木")
    for col in range(1, width + 1):
        if col <= 7 or col >= 12:
            cells.put(11, col, "difficult", "浅滩小径")
    for col in range(8, 12):
        cells.put(11, col, "difficult", "可涉水浅滩")
    cells.line(13, 1, 13, width, "difficult", "高地兽径")

    # Irregular tree masses frame the road without a four-wall building box.
    trees = {
        (1, 1), (1, 2), (1, 5), (1, 6), (1, 16), (1, 18), (1, 19), (1, 20),
        (2, 2), (2, 5), (2, 17), (2, 20), (4, 1), (4, 4), (4, 18), (5, 2),
        (5, 6), (5, 19), (6, 1), (6, 17), (8, 2), (8, 18), (9, 1), (9, 5),
        (9, 19), (10, 3), (10, 17), (12, 1), (12, 5), (12, 18), (14, 2),
        (14, 4), (14, 6), (14, 16), (14, 19), (14, 20),
    }
    for row, col in trees:
        cells.put(row, col, "cover", "密林与灌木", blocks_sight=True)
    cells.put(4, 5, "cover", "倒伏树根", blocks_sight=True)
    cells.put(10, 16, "cover", "河岸巨石", blocks_sight=True)
    cells.put(6, 8, "marker", "断桥西桥头")
    cells.put(8, 13, "marker", "断桥东桥头")

    return DuskbellMapLayout(
        "forest_crossing",
        width,
        height,
        "rainy-forest-crossing",
        "林间旧路被连续溪流切开；断桥、北侧倒木、南侧浅滩与高地兽径是四种不同通路。",
        "桥面中段确实断裂；三条替代路线可完整连通两岸，失败只增加代价而不锁死推进。",
        cells.result(),
    )


def _mill_yard() -> DuskbellMapLayout:
    width, height = 20, 14
    cells = _Cells(width, height, "暮色草地")
    cells.rect(3, 3, 12, 13, "floor", "泥土地院落")

    # An irregular fence encloses the yard, while the mill itself is a real
    # building occupying the north-east corner.
    cells.line(1, 2, 1, 11, "wall", "外院木栅", blocks_sight=False)
    cells.line(1, 2, 11, 2, "wall", "外院木栅", blocks_sight=False)
    cells.line(13, 2, 13, 9, "wall", "外院木栅", blocks_sight=False)
    cells.line(13, 11, 13, 15, "wall", "外院木栅", blocks_sight=False)
    cells.put(13, 10, "door", "外院木门")

    cells.line(2, 14, 2, 20, "wall", "磨坊北墙", blocks_sight=True)
    cells.line(2, 14, 8, 14, "wall", "磨坊西墙", blocks_sight=True)
    cells.line(8, 14, 8, 20, "wall", "磨坊南墙", blocks_sight=True)
    cells.line(2, 20, 8, 20, "wall", "磨坊东墙", blocks_sight=True)
    cells.put(5, 14, "door", "磨坊侧门")
    cells.put(4, 17, "room", "磨坊一层")
    cells.put(6, 17, "stairs", "地下工坊入口")

    cells.line(9, 13, 14, 13, "water", "磨坊引水渠")
    cells.line(9, 12, 14, 12, "difficult", "湿滑渠岸")
    cells.line(4, 5, 9, 5, "wall", "院落矮墙", blocks_sight=False)
    cells.put(7, 5, "door", "矮墙缺口")
    cells.put(6, 10, "room", "开阔外院")
    cells.put(5, 8, "cover", "粮车", blocks_sight=True)
    cells.put(5, 9, "cover", "粮车", blocks_sight=True)
    cells.put(6, 8, "marker", "粮车后方")
    cells.put(9, 7, "cover", "面粉桶")
    cells.put(10, 4, "cover", "柴堆", blocks_sight=True)
    cells.put(11, 16, "marker", "水轮检修台")

    return DuskbellMapLayout(
        "mill_yard",
        width,
        height,
        "dusk-mill-yard",
        "不规则木栅围出磨坊外院；东北角是磨坊建筑，院内有粮车、矮墙、水渠、侧门和地下入口。",
        "巨鼠藏在粮车后；院落中央保持开阔，木门、矮墙缺口和磨坊侧门形成清楚的推进路线。",
        cells.result(),
    )


def _undercroft() -> DuskbellMapLayout:
    width, height = 22, 16
    cells = _Cells(width, height, "地下石地板")
    cells.building_boundary("地下工坊", [(16, 11, "地下入口")])

    walls = (
        (1, 8, 7, 8, "维修间东墙"),
        (7, 1, 7, 8, "维修间南墙"),
        (1, 15, 6, 15, "储藏室西墙"),
        (6, 15, 6, 22, "储藏室南墙"),
        (10, 1, 10, 9, "档案室北墙"),
        (10, 9, 16, 9, "档案室东墙"),
        (10, 14, 16, 14, "控制室西墙"),
        (10, 14, 10, 22, "控制室北墙"),
    )
    for row_1, col_1, row_2, col_2, label in walls:
        cells.line(row_1, col_1, row_2, col_2, "wall", label, blocks_sight=True)
    for row, col, label in (
        (4, 8, "维修间门"),
        (6, 18, "储藏室门"),
        (10, 5, "档案室门"),
        (10, 18, "控制室门"),
        (16, 11, "地下入口"),
    ):
        cells.put(row, col, "door", label)

    for row, col, label in (
        (3, 4, "维修间"),
        (4, 18, "储藏室"),
        (8, 10, "主轴厅"),
        (13, 5, "档案室"),
        (12, 18, "控制室"),
    ):
        cells.put(row, col, "room", label)
    cells.put(5, 4, "cover", "维修台")
    cells.put(3, 19, "cover", "木箱堆", blocks_sight=True)
    cells.put(8, 11, "cover", "主轴齿轮", blocks_sight=True)
    cells.put(8, 12, "cover", "主轴齿轮", blocks_sight=True)
    cells.put(12, 5, "cover", "档案柜", blocks_sight=True)
    cells.put(13, 18, "lever", "东侧制动拉杆")
    cells.put(5, 6, "lever", "西侧制动拉杆")
    cells.put(12, 11, "difficult", "散落齿轮")
    cells.put(9, 11, "marker", "主轴南走廊")

    return DuskbellMapLayout(
        "gear_undercroft",
        width,
        height,
        "brass-gear-undercroft",
        "地下工坊由维修间、储藏室、主轴厅、档案室与控制室组成，房间通过门廊和中央走廊连通。",
        "入口可达主轴厅与四个功能房；两侧制动拉杆、账本和蓄能轮分别位于不同区域。",
        cells.result(),
    )


def duskbell_map_layouts() -> tuple[DuskbellMapLayout, ...]:
    """Return all five layouts in Scene order."""
    return (_tavern(celebration=False), _forest_crossing(), _mill_yard(), _undercroft(), _tavern(celebration=True))


def _reachable(layout: DuskbellMapLayout, start: Point, goal: Point, *, water_blocks: bool) -> bool:
    by_point = {(int(cell["row"]), int(cell["col"])): cell for cell in layout.cells}
    blocked_kinds = {"wall", "cover"}
    if water_blocks:
        blocked_kinds.add("water")
    queue = deque([start])
    seen = {start}
    while queue:
        row, col = queue.popleft()
        if (row, col) == goal:
            return True
        for point in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            next_row, next_col = point
            if point in seen or not (1 <= next_row <= layout.height and 1 <= next_col <= layout.width):
                continue
            if str(by_point.get(point, {"kind": "floor"})["kind"]) in blocked_kinds:
                continue
            seen.add(point)
            queue.append(point)
    return False


def audit_duskbell_layout(layout: DuskbellMapLayout) -> tuple[str, ...]:
    """Return semantic failures; an empty tuple means the map meets its contract."""
    failures: list[str] = []
    points = [(int(cell["row"]), int(cell["col"])) for cell in layout.cells]
    if len(points) != layout.width * layout.height or len(set(points)) != len(points):
        failures.append("地图必须恰好描述每个格子一次")
    if any(not (1 <= row <= layout.height and 1 <= col <= layout.width) for row, col in points):
        failures.append("存在越界格子")
    labels = [str(cell.get("label") or "") for cell in layout.cells]
    kinds = [str(cell.get("kind") or "") for cell in layout.cells]

    if layout.scene_key in {"tavern", "celebration_tavern"}:
        for required in ("旅店正门", "厨房门", "厨房", "吧台"):
            if not any(required in label for label in labels):
                failures.append(f"旅店缺少{required}")
        for row, col in ((1, 1), (1, layout.width), (layout.height, 1), (layout.height, layout.width)):
            cell = next(item for item in layout.cells if item["row"] == row and item["col"] == col)
            if cell["kind"] != "wall":
                failures.append("旅店没有完整建筑外墙")
                break
        if layout.scene_key == "celebration_tavern" and not any("庆功长桌" in label for label in labels):
            failures.append("尾声旅店缺少庆功布置")
    elif layout.scene_key == "forest_crossing":
        if any("北墙" in label or "南墙" in label or "东墙" in label or "西墙" in label for label in labels):
            failures.append("户外断桥不应使用建筑外墙")
        water_rows = {int(cell["row"]) for cell in layout.cells if cell["kind"] == "water"}
        if 1 not in water_rows or layout.height not in water_rows or len(water_rows) < 10:
            failures.append("溪流没有连续贯穿地图")
        for route in ("横卧倒木", "可涉水浅滩", "高地兽径"):
            if not any(route in label for label in labels):
                failures.append(f"缺少替代路线：{route}")
        if not _reachable(layout, (7, 4), (7, 17), water_blocks=True):
            failures.append("两岸之间没有避开深水的完整路线")
    elif layout.scene_key == "mill_yard":
        for required in ("外院木栅", "外院木门", "磨坊侧门", "磨坊引水渠", "开阔外院", "地下工坊入口"):
            if not any(required in label for label in labels):
                failures.append(f"磨坊外院缺少{required}")
        if kinds.count("water") < 5:
            failures.append("引水渠没有形成连续结构")
        if not _reachable(layout, (12, 10), (5, 14), water_blocks=True):
            failures.append("外院入口无法到达磨坊侧门")
    elif layout.scene_key == "gear_undercroft":
        for required in ("维修间", "储藏室", "主轴厅", "档案室", "控制室"):
            if not any(label == required for label in labels):
                failures.append(f"地下工坊缺少{required}")
        if kinds.count("door") < 5:
            failures.append("地下工坊门廊不足")
        for goal in ((4, 8), (6, 18), (10, 5), (10, 18)):
            if not _reachable(layout, (15, 11), goal, water_blocks=False):
                failures.append(f"地下入口无法连通门廊{goal}")
    return tuple(failures)


def assert_duskbell_layouts() -> tuple[DuskbellMapLayout, ...]:
    layouts = duskbell_map_layouts()
    failures = {
        layout.scene_key: audit_duskbell_layout(layout)
        for layout in layouts
        if audit_duskbell_layout(layout)
    }
    if failures:
        raise ValueError(f"Duskbell map semantic audit failed: {failures}")
    return layouts
