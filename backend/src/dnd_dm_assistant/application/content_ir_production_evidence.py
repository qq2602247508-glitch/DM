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


def current_project_compile_only_count(repo_root: Path) -> int:
    """Reconcile the canonical census with explicit evidence deltas."""

    baseline_path = repo_root / "reports" / "tashas-baseline-2026-08-11.json"
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        count = int(baseline["compile_only"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        count = 35
    root = repo_root / "data" / "content-ir" / "compiled"
    delta = 0
    for path in sorted(root.rglob("production-runtime-results*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, Mapping):
            delta += int(value.get("compile_only_delta") or 0)
    return count + delta


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
        if content_kind is not None and value.get("content_kind") != content_kind:
            continue
        raw_ids = value.get("production_runtime_full_ids")
        if not isinstance(raw_ids, list):
            continue
        checks = value.get("checks")
        checks = checks if isinstance(checks, Mapping) else {}
        if required and not all(bool(checks.get(check)) for check in required):
            continue
        if require_name_branch_free and checks.get("name_branch_count") != 0:
            continue
        for raw_id in raw_ids:
            content_id = str(raw_id).strip()
            if not content_id or not _is_pack_content_id(content_id, pack_id):
                continue
            row = (value.get("evidence_by_id") or {}).get(content_id)
            row = dict(row) if isinstance(row, Mapping) else {}
            evidence[content_id] = {
                **row,
                "content_id": content_id,
                "content_kind": row.get("content_kind", value.get("content_kind")),
                "schema_version": value.get("schema_version"),
                "checks": dict(checks),
                "evidence_path": str(path.relative_to(repo_root)),
                "production_runtime_full": True,
            }
    return dict(sorted(evidence.items()))
