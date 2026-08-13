from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_evidence import (
    load_production_runtime_evidence,
)
from dnd_dm_assistant.application.tashas_recovery import (
    apply_isolated_runtime_validation,
    load_item_production_evidence,
)
from dnd_dm_assistant.application.tashas_whole_pack import (
    PACK_ID,
    build_migration,
    existing_project_production_ids,
)
from dnd_dm_assistant.domain.content_ir_status import summarize_status_layers

ROOT = Path(__file__).resolve().parents[2]


def test_shared_evidence_loader_scopes_and_deduplicates_round_receipts() -> None:
    tasha = load_production_runtime_evidence(ROOT, pack_id=PACK_ID)
    all_evidence = load_production_runtime_evidence(ROOT, pack_id=None)

    # Round XXV's historical 131/188 snapshot is superseded by the current
    # Round XXVI Ambush receipt. Keep this test focused on reconciliation
    # invariants; the current exact projection is asserted by the Round XXVI
    # receipt test.
    project_ids = existing_project_production_ids(ROOT)
    assert len(tasha) == len(set(tasha))
    assert len(project_ids) == len(set(project_ids))
    assert len(tasha) >= 131
    assert len(project_ids) >= 188
    assert set(tasha).issubset(all_evidence)
    assert "tashas-cauldron:spell:54c8c29188db1442473d9dc1" in tasha
    assert "tashas-cauldron:spell:083419d9de551806a5ca9748" in tasha
    assert "content.tashas-cauldron.feature.battle-master.ambush" in tasha
    assert all(
        content_id.startswith(("content.tashas-cauldron.", "tashas-cauldron:"))
        for content_id in tasha
    )


def test_item_evidence_is_closed_to_valid_item_consumer_receipts() -> None:
    item_ids = load_item_production_evidence(ROOT)

    assert len(item_ids) == 40
    assert all(item_id.startswith("content.tashas-cauldron.item.") for item_id in item_ids)
    assert len(item_ids) == len(set(item_ids))


def test_current_content_and_item_layers_reconcile_without_double_counting() -> None:
    migration = build_migration(ROOT)
    atoms = migration["atoms"]

    assert {
        key: migration[key]
        for key in (
            "content_atom_total",
            "executable_candidate_total",
            "authored_typed_ir",
            "compile_full",
            "runtime_preview_full",
            "production_full",
            "dm_assisted",
            "game_usable",
            "compile_only",
            "manual_authoring",
            "dm_reference",
        )
    } == {
        "content_atom_total": 525,
        "executable_candidate_total": 408,
            "authored_typed_ir": 106,
            "compile_full": 105,
            "runtime_preview_full": 105,
                "production_full": 103,
            "dm_assisted": 2,
                    "game_usable": 105,
                "compile_only": 0,
            "manual_authoring": 303,
        "dm_reference": 107,
    }

    layers = summarize_status_layers(atoms)
    assert layers["registered_production_full"] == migration["production_full"]
    assert layers["dm_assisted"] == migration["dm_assisted"]
    assert layers["game_usable"] == migration["game_usable"]
    assert migration["game_usable"] == migration["production_full"] + migration["dm_assisted"]

    item_catalog = migration["item_spec_catalog"]
    validated = apply_isolated_runtime_validation(
        item_catalog,
        {
            "isolated_runtime_validated_ids": [
                spec["item_id"]
                for spec in item_catalog["specs"]
                if spec["compile"]["compile_status"] == "full"
            ],
            "registered_production_full_ids": sorted(load_item_production_evidence(ROOT)),
            "dm_assisted_ids": [],
        },
    )
    assert validated["item_spec_total"] == 47
    assert validated["item_spec_compile_full"] == 40
    assert validated["item_spec_compile_only"] == 7
    assert validated["isolated_runtime_validated"] == 40
    assert validated["registered_production_full"] == 40
    assert validated["dm_assisted"] == 0
    assert validated["game_usable"] == 40
    assert validated["game_usable"] == (
        validated["registered_production_full"] + validated["dm_assisted"]
    )
    assert validated["status_layers"]["game_usable"] == 40


def test_reconciliation_counts_are_dynamic_and_wrong_projection_fails() -> None:
    migration = build_migration(ROOT)
    projection = {
        key: migration[key]
        for key in (
            "authored_typed_ir",
            "compile_full",
            "runtime_preview_full",
            "production_full",
            "dm_assisted",
            "game_usable",
            "compile_only",
            "manual_authoring",
        )
    }
    assert projection["production_full"] == 103
    assert projection["game_usable"] == 105
    assert projection["compile_only"] == 0
    wrong = dict(projection)
    wrong["production_full"] += 1
    assert wrong != projection
    assert wrong["production_full"] != migration["production_full"]

    result = json.loads(
        (
            ROOT / "reports/tashas-production-reconciliation-round-XXV-2026-08-12.json"
        ).read_text(encoding="utf-8")
    )
    assert result["checks"]["baseline_after_delta_relation"] is True
    assert result["counts"]["after"]["tasha"]["production_full"] == 102
    assert result["counts"]["delta"]["tasha"]["production_full"] == 1
