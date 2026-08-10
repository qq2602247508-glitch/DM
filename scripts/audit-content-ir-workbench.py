# ruff: noqa: N999
"""Audit official source records without mutating production state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dnd_dm_assistant.application.content_ir_workbench import (
    audit_records,
    load_records,
    write_report,
)

ROOT = Path(__file__).resolve().parents[1]
JSON_ROOT = ROOT / "data/generated-content/dnd5e_chm/json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book")
    parser.add_argument(
        "--all-official",
        action="store_true",
        help="audit all registered official source books separately",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = load_records(JSON_ROOT)
    books = sorted(
        {
            str(record.get("source_book"))
            for record in records
            if record.get("officiality") == "official" and record.get("source_book")
        }
    )
    if args.all_official:
        reports = {
            book: audit_records(records, source_book=book).to_dict()
            for book in books
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {"schema_version": "content-ir-workbench-batch-1", "books": reports},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps(reports, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not args.book:
        parser.error("--book or --all-official is required")
    report = audit_records(records, source_book=args.book)
    write_report(report, args.output)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
