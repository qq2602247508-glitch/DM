#!/usr/bin/env python3
"""Audit and safely upgrade the five maps in an existing Duskbell campaign."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from duskbell_map_layouts import (
    DuskbellMapLayout,
    assert_duskbell_layouts,
    audit_duskbell_layout,
)

SCENE_NAMES = (
    "Scene 1 · 提灯旅店的委托",
    "Scene 2 · 林间旧路与断桥",
    "Scene 3 · 暮铃磨坊外院",
    "Scene 4 · 地下齿轮工坊",
    "Scene 5 · 晨溪村庆功与升级",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument(
        "--backup-directory",
        type=Path,
        help="Defaults to a backups directory beside the database.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply after a successful dry audit.")
    return parser.parse_args()


def _scene_rows(
    connection: sqlite3.Connection, campaign_id: str
) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in SCENE_NAMES)
    rows = connection.execute(
        f"""
        SELECT s.id AS scene_id, s.name, g.id AS grid_id, g.width, g.height,
               g.public_description, g.dm_description, g.layers_json
        FROM scenes AS s
        JOIN scene_grids AS g ON g.scene_id = s.id
        WHERE s.campaign_id = ? AND s.name IN ({placeholders})
        """,
        (campaign_id, *SCENE_NAMES),
    ).fetchall()
    by_name = {str(row["name"]): row for row in rows}
    missing = [name for name in SCENE_NAMES if name not in by_name]
    if missing:
        raise ValueError(f"campaign does not contain all Duskbell maps: {missing}")
    return [by_name[name] for name in SCENE_NAMES]


def _current_layout(row: sqlite3.Row, target: DuskbellMapLayout) -> DuskbellMapLayout:
    layers = json.loads(str(row["layers_json"]))
    raw_cells = layers.get("cells", []) if isinstance(layers, dict) else []
    cells = tuple(dict(cell) for cell in raw_cells if isinstance(cell, dict))
    return DuskbellMapLayout(
        target.scene_key,
        int(row["width"]),
        int(row["height"]),
        str(layers.get("theme") or "") if isinstance(layers, dict) else "",
        str(row["public_description"] or ""),
        str(row["dm_description"] or ""),
        cells,
    )


def _counts(cells: tuple[dict[str, Any], ...]) -> dict[str, int]:
    result: dict[str, int] = {}
    for cell in cells:
        kind = str(cell.get("kind") or "unknown")
        result[kind] = result.get(kind, 0) + 1
    return dict(sorted(result.items()))


def _backup(connection: sqlite3.Connection, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(destination) as backup_connection:
        connection.backup(backup_connection)


def _materialized_object(cell: dict[str, Any]) -> tuple[str, dict[str, object]] | None:
    kind = str(cell.get("kind") or "")
    mapping: dict[str, tuple[str, dict[str, object]]] = {
        "wall": ("wall", {}),
        "door": ("door", {}),
        "cover": ("cover", {}),
        "object": ("furniture", {}),
        "water": ("terrain", {"difficult": True, "terrain_kind": "water"}),
        "difficult": ("terrain", {"difficult": True, "terrain_kind": "difficult"}),
    }
    return mapping.get(kind)


def _replace_grid(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    layout: DuskbellMapLayout,
) -> tuple[int, int]:
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
    scene_id = str(row["scene_id"])
    connection.execute(
        """
        UPDATE scene_grids
        SET width = ?, height = ?, public_description = ?, dm_description = ?,
            layers_json = ?, version = version + 1, updated_at = ?
        WHERE id = ?
        """,
        (
            layout.width,
            layout.height,
            layout.public_description,
            layout.dm_description,
            json.dumps(layout.layers_json(), ensure_ascii=False),
            now,
            str(row["grid_id"]),
        ),
    )
    deleted = connection.execute(
        """
        DELETE FROM scene_objects
        WHERE scene_id = ?
          AND json_extract(metadata_json, '$.generated_from') = 'layers_json'
        """,
        (scene_id,),
    ).rowcount
    inserted = 0
    for cell in layout.cells:
        materialized = _materialized_object(cell)
        if materialized is None:
            continue
        object_type, metadata = materialized
        connection.execute(
            """
            INSERT INTO scene_objects (
                id, created_at, updated_at, version, scene_id, object_type, label,
                "row", col, width_cells, height_cells, state, visibility,
                interaction_json, metadata_json
            ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, 1, 1, ?, 'public', '{}', ?)
            """,
            (
                str(uuid4()),
                now,
                now,
                scene_id,
                object_type,
                str(cell.get("label") or object_type)[:200],
                int(cell["row"]),
                int(cell["col"]),
                "closed" if object_type == "door" else "active",
                json.dumps({"generated_from": "layers_json", **metadata}, ensure_ascii=False),
            ),
        )
        inserted += 1
    return deleted, inserted


def _clean_template_tokens(connection: sqlite3.Connection) -> int:
    deleted = connection.execute(
        """
        DELETE FROM scene_tokens AS generated
        WHERE json_extract(generated.metadata_json, '$.generated_from') = 'scene_participant'
          AND EXISTS (
              SELECT 1 FROM scene_tokens AS intentional
              WHERE intentional.scene_id = generated.scene_id
                AND intentional.entity_type = generated.entity_type
                AND intentional.entity_id = generated.entity_id
                AND json_extract(intentional.metadata_json, '$.module') = 'duskbell-mill'
          )
        """
    ).rowcount
    # The original module intentionally hid the rat behind the cart, but its
    # token occupied the same blocking cell.  Keep the intent and move it to
    # the labelled square immediately behind the cart.
    connection.execute(
        """
        UPDATE scene_tokens
        SET "row" = 6, col = 8, version = version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE label = '饥饿巨鼠' AND "row" = 5 AND col = 8
          AND json_extract(metadata_json, '$.module') = 'duskbell-mill'
        """
    )
    # The generated merchant token used the old fallback (1,1), which is an
    # exterior wall in the tavern.  Move only this merchant-generated token.
    connection.execute(
        """
        UPDATE scene_tokens
        SET "row" = 2, col = 16, version = version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE "row" = 1 AND col = 1
          AND json_extract(metadata_json, '$.merchant_id') IS NOT NULL
        """
    )
    return deleted


def main() -> None:
    args = parse_args()
    database = args.database.expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    layouts = assert_duskbell_layouts()
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        rows = _scene_rows(connection, args.campaign_id)
        print("《暮铃磨坊》5 图语义审计")
        for row, target in zip(rows, layouts, strict=True):
            current = _current_layout(row, target)
            failures = audit_duskbell_layout(current)
            status = "通过" if not failures else "需升级"
            print(f"- {row['name']}：{status}")
            print(f"  当前：{_counts(current.cells)}")
            print(f"  目标：{_counts(target.cells)}")
            for failure in failures:
                print(f"  · {failure}")
        if not args.apply:
            print("dry-run 完成；添加 --apply 才会写入数据库。")
            return

        backup_directory = (
            args.backup_directory.expanduser().resolve()
            if args.backup_directory
            else database.parent / "backups"
        )
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup_path = backup_directory / f"pre-duskbell-map-semantics-{stamp}.sqlite3"
        _backup(connection, backup_path)
        print(f"备份：{backup_path}")

        with connection:
            totals = []
            for row, layout in zip(rows, layouts, strict=True):
                totals.append(_replace_grid(connection, row, layout))
            duplicate_tokens = _clean_template_tokens(connection)
        print(
            f"升级完成：替换 {sum(item[0] for item in totals)} 个旧生成对象，"
            f"写入 {sum(item[1] for item in totals)} 个结构对象，"
            f"清理 {duplicate_tokens} 个模板重复 Token。"
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"foreign key check failed: {violations}")
        refreshed_rows = _scene_rows(connection, args.campaign_id)
        for row, target in zip(refreshed_rows, layouts, strict=True):
            failures = audit_duskbell_layout(_current_layout(row, target))
            if failures:
                raise RuntimeError(f"post-write audit failed for {row['name']}: {failures}")
        print("写入后 5/5 地图语义审计通过；外键检查通过。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
