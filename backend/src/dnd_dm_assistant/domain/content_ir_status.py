"""Shared Content IR state layers.

The project has several deliberately different execution boundaries.  This
module gives reports and isolated pack registries one vocabulary so that an
isolated preview cannot be counted as a formal production registration.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

CONTENT_STATUS_LAYERS = (
    "source_identified",
    "draft",
    "candidate",
    "reviewed",
    "authored_typed_ir",
    "compile_full",
    "runtime_preview_full",
    "isolated_runtime_validated",
    "registered_production_full",
    "dm_assisted",
    "game_usable",
)

GAME_USABLE_LAYERS = frozenset({"registered_production_full", "dm_assisted"})


def build_status_layers(
    *,
    source_identified: bool = False,
    draft: bool = False,
    candidate: bool = False,
    reviewed: bool = False,
    authored_typed_ir: bool = False,
    compile_full: bool = False,
    runtime_preview_full: bool = False,
    isolated_runtime_validated: bool = False,
    registered_production_full: bool = False,
    dm_assisted: bool = False,
) -> dict[str, Any]:
    """Build the canonical layer projection for one content entry."""

    values = {
        "source_identified": bool(source_identified),
        "draft": bool(draft),
        "candidate": bool(candidate),
        "reviewed": bool(reviewed),
        "authored_typed_ir": bool(authored_typed_ir),
        "compile_full": bool(compile_full),
        "runtime_preview_full": bool(runtime_preview_full),
        "isolated_runtime_validated": bool(isolated_runtime_validated),
        "registered_production_full": bool(registered_production_full),
        "dm_assisted": bool(dm_assisted),
    }
    values["game_usable"] = bool(
        values["registered_production_full"] or values["dm_assisted"]
    )
    reached = [layer for layer in CONTENT_STATUS_LAYERS if values.get(layer, False)]
    return {
        **values,
        "highest_status": "game_usable" if values["game_usable"] else (
            reached[-1] if reached else "unclassified"
        ),
    }


def status_layers_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Read a row's canonical layers, rejecting unknown layer names."""

    raw = row.get("status_layers")
    if not isinstance(raw, Mapping):
        return build_status_layers()
    unknown = sorted(set(raw) - set(CONTENT_STATUS_LAYERS) - {"highest_status"})
    if unknown:
        raise ValueError("unknown Content IR status layers: " + ",".join(unknown))
    values = {
        layer: bool(raw.get(layer, False))
        for layer in CONTENT_STATUS_LAYERS
        if layer != "game_usable"
    }
    return build_status_layers(**values)


def summarize_status_layers(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Count each canonical layer exactly once across a row collection."""

    counts = {layer: 0 for layer in CONTENT_STATUS_LAYERS}
    for row in rows:
        layers = status_layers_from_row(row)
        for layer in CONTENT_STATUS_LAYERS:
            counts[layer] += int(bool(layers.get(layer)))
    return counts
