from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_workbench import (
    _registered_pack,
    _select_records,
    audit_records,
    compile_artifact_directory,
    compile_pack_records,
    dry_run_manifest,
    load_records,
    report_from_artifacts,
    scan_registered_official_packs,
    write_report,
)

ROOT = Path(__file__).resolve().parents[3]
JSON_ROOT = ROOT / "data/generated-content/dnd5e_chm/json"
SOURCE_ROOT = ROOT / "data/sources/dnd5e_chm"
DEFAULT_WORKBENCH_ROOT = Path("/tmp/content-ir-workbench")


def _dump(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _records_for_selector(
    selector: str, records: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    pack = _registered_pack(selector)
    if pack is not None:
        selected = _select_records(records, content_pack=pack)
        return selected, pack
    return _select_records(records, source_book=selector), None


def _records_for_input(
    input_path: Path, records: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    pack = _registered_pack(input_path.name)
    if pack is not None:
        return _select_records(records, content_pack=pack), pack
    try:
        relative = input_path.resolve().relative_to(SOURCE_ROOT.resolve()).as_posix().strip("/")
    except ValueError:
        relative = input_path.name
    selected = [
        dict(record)
        for record in records
        if str(record.get("source_relative_path") or "").strip("/").startswith(relative)
    ]
    return sorted(
        selected,
        key=lambda item: (
            str(item.get("source_relative_path") or ""),
            str(item.get("name") or ""),
        ),
    ), None


def _cmd_scan(args: argparse.Namespace) -> int:
    records = load_records(JSON_ROOT)
    selected, pack = _records_for_selector(args.book, records)
    report = audit_records(
        selected,
        source_book=pack["source_book"] if pack else args.book,
        pack_id=pack["pack_id"] if pack else None,
        pack_version=None,
        content_pack=pack,
    )
    if args.output:
        write_report(report, args.output)
    _dump(report.to_dict())
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    records = load_records(JSON_ROOT)
    if args.book:
        selected, pack = _records_for_selector(args.book, records)
        input_name = args.book
    else:
        selected, pack = _records_for_input(args.input, records)
        input_name = args.input.name
    if pack is None:
        pack = {
            "pack_id": input_name.lower().replace(" ", "-"),
            "label": input_name,
            "source_book": input_name,
            "source_book_aliases": [],
            "source_path_prefixes": [input_name],
            "source_origin": "local-source",
            "content_types": [],
        }
    report = audit_records(
        selected,
        source_book=pack["source_book"],
        pack_id=pack["pack_id"],
        content_pack=pack if _registered_pack(pack["pack_id"]) else None,
    )
    result = compile_pack_records(selected, report=report, pack=pack, output_dir=args.output)
    _dump(result)
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    result = compile_artifact_directory(args.input, output_dir=args.output, write_files=True)
    _dump(result)
    return 0


def _cmd_dry_run(args: argparse.Namespace) -> int:
    result = dry_run_manifest(args.manifest, args.isolated_target)
    _dump(result)
    return 0 if result.get("status") not in {"conflict", "rolled_back"} else 2


def _cmd_report(args: argparse.Namespace) -> int:
    _dump(report_from_artifacts(args.input))
    return 0


def _cmd_scan_all_official(args: argparse.Namespace) -> int:
    records = load_records(JSON_ROOT)
    root = args.workbench_root or DEFAULT_WORKBENCH_ROOT
    index = scan_registered_official_packs(records, workbench_root=root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _dump(index)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m feature_workbench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan")
    scan.add_argument("--book", required=True)
    scan.add_argument("--output", type=Path)
    scan.set_defaults(func=_cmd_scan)

    extract = subparsers.add_parser("extract")
    input_group = extract.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", type=Path)
    input_group.add_argument("--book")
    extract.add_argument("--output", type=Path, required=True)
    extract.set_defaults(func=_cmd_extract)

    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("--input", type=Path, required=True)
    compile_parser.add_argument("--output", type=Path)
    compile_parser.set_defaults(func=_cmd_compile)

    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--manifest", type=Path, required=True)
    dry_run.add_argument("--isolated-target", type=Path, required=True)
    dry_run.set_defaults(func=_cmd_dry_run)

    report = subparsers.add_parser("report")
    report.add_argument("--input", type=Path, required=True)
    report.set_defaults(func=_cmd_report)

    scan_all = subparsers.add_parser("scan-all-official")
    scan_all.add_argument("--output", type=Path, required=True)
    scan_all.add_argument("--workbench-root", type=Path)
    scan_all.set_defaults(func=_cmd_scan_all_official)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
