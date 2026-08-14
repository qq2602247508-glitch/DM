"""Shared persisted production-runtime evidence loading.

Production receipts are written by several historical validation rounds.  The
consumer-specific callers must agree on how IDs are scoped, deduplicated, and
filtered without making an isolated receipt look like a formal registry write.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def authoritative_compile_only_ids(repo_root: Path) -> set[str]:
    """Return the immutable 2026-08-11 unique compile-only census.

    The census is derived from the authoritative blocker audit and the
    authoritative batch-II unlock receipt.  It is intentionally an ID set:
    report counts and receipt ``compile_only_delta`` fields are not inputs.
    """

    blocker_path = repo_root / "reports" / "content-ir-production-blocker-audit-II-2026-08-11.json"
    unlock_path = repo_root / "reports" / "content-ir-production-runtime-batch-II-2026-08-11.json"
    try:
        blocker = json.loads(blocker_path.read_text(encoding="utf-8"))
        unlocked = json.loads(unlock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return set()
    entries = blocker.get("entries")
    evidence = unlocked.get("evidence")
    if not isinstance(entries, list) or not isinstance(evidence, list):
        return set()
    compile_only = {
        str(entry["content_id"]).strip()
        for entry in entries
        if isinstance(entry, Mapping)
        and entry.get("production_status") == "compile_only"
        and str(entry.get("content_id") or "").strip()
    }
    unlocked_ids = {
        str(row["content_id"]).strip()
        for row in evidence
        if isinstance(row, Mapping) and str(row.get("content_id") or "").strip()
    }
    return compile_only - unlocked_ids


def project_compile_only_ids(
    census_ids: Iterable[str],
    validated_production_ids: Iterable[str],
) -> set[str]:
    """Remove each validated promotion from the census at most once."""

    return {str(content_id).strip() for content_id in census_ids if str(content_id).strip()} - {
        str(content_id).strip()
        for content_id in validated_production_ids
        if str(content_id).strip()
    }


def current_project_compile_only_ids(repo_root: Path) -> set[str]:
    census = authoritative_compile_only_ids(repo_root)
    evidence = load_production_runtime_evidence(
        repo_root,
        pack_id=None,
        round_id="round-XLVIII",
    )
    return project_compile_only_ids(census, evidence)


def current_project_compile_only_count(repo_root: Path) -> int:
    """Return the current set-based compile-only projection."""

    return len(current_project_compile_only_ids(repo_root))


def _is_pack_content_id(content_id: str, pack_id: str | None) -> bool:
    if pack_id is None:
        return True
    return content_id.startswith((f"content.{pack_id}.", f"{pack_id}:"))


def load_production_runtime_evidence(
    repo_root: Path,
    *,
    pack_id: str | None,
    content_kind: str | None = None,
    required_checks: Iterable[str] = (),
    require_name_branch_free: bool = False,
    round_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load a deterministic, deduplicated set of persisted production IDs.

    The result is keyed by content ID.  A receipt is accepted only when it has
    a production ID list, belongs to the requested pack, matches the optional
    content kind, and passes the requested consumer checks.  ``formal_apply``
    is deliberately not inferred here: these receipts are runtime evidence,
    while formal registry application remains a separate boundary.
    """

    required = tuple(str(check) for check in required_checks)
    root = repo_root / "data" / "content-ir" / "compiled"
    evidence: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("production-runtime-results*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(value, Mapping):
            continue
        if round_id is not None and value.get("round_id") != round_id:
            continue
        if content_kind is not None and value.get("content_kind") != content_kind:
            continue
        raw_ids = value.get("production_runtime_full_ids")
        if not isinstance(raw_ids, list):
            continue
        checks = value.get("checks")
        checks = checks if isinstance(checks, Mapping) else {}
        rows = value.get("evidence_by_id")
        if not isinstance(rows, Mapping) or not checks:
            continue
        if required and not all(bool(checks.get(check)) for check in required):
            continue
        if require_name_branch_free and checks.get("name_branch_count") != 0:
            continue
        for raw_id in raw_ids:
            content_id = str(raw_id).strip()
            if not content_id or not _is_pack_content_id(content_id, pack_id):
                continue
            row = rows.get(content_id)
            if not isinstance(row, Mapping) or row.get("production_runtime_full") is False:
                continue
            if checks.get("all_required_checks_passed") is False:
                continue
            row = dict(row)
            evidence[content_id] = {
                **row,
                "content_id": content_id,
                "content_kind": row.get("content_kind", value.get("content_kind")),
                "schema_version": value.get("schema_version"),
                "round_id": value.get("round_id"),
                "checks": dict(checks),
                "evidence_path": str(path.relative_to(repo_root)),
                "production_runtime_full": True,
            }
    return dict(sorted(evidence.items()))
