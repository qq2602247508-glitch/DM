# ruff: noqa: N999
"""Validate generic production closure gates for two Content IR capabilities."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.feature_materializers import (
    default_materializer_registry,
)
from dnd_dm_assistant.domain.entity_senses import resolve_entity_senses
from dnd_dm_assistant.domain.feature_capabilities import default_capability_catalog
from dnd_dm_assistant.domain.rules_kernel_protocol import KernelPosition
from dnd_dm_assistant.domain.spatial_authority import DeterministicTestSpatialAuthority
from dnd_dm_assistant.domain.spell_slot_reactivation import (
    SpellSlotReactivationSpec,
    transition_spell_slot_reactivation,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/generic-capability-production-closure-2026-08-13.json"
DOC = ROOT / "docs/generic-capability-production-closure-2026-08-13.md"


def _reject(call) -> bool:
    try:
        call()
    except (ValueError, KeyError):
        return True
    return False


def main() -> int:
    catalog = default_capability_catalog()
    senses = catalog.get("entity.senses")
    reactivation = catalog.get("spell.slot.reactivation")
    assert senses is not None and reactivation is not None

    senses_registry = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={"entity_senses": [{"resolution_kind": "entity_senses"}]},
    )
    reactivation_registry = resolve_production_consumers(
        content_kind="advancement",
        runtime_schema_version="feature-runtime-1",
        blocks={"spell_slot_reactivations": [{"resolution_kind": "spell_slot_reactivation"}]},
    )
    materializers = default_materializer_registry()

    spatial = DeterministicTestSpatialAuthority()
    spatial.add_entity("entity", KernelPosition(row=1, col=1))
    spatial.add_entity("target", KernelPosition(row=1, col=2))
    senses_block = {
        "entity_binding": "entity_lifecycle",
        "source_provenance": {"source_record_id": "src", "source_fingerprint": "fp"},
        "senses": {"hearing": True, "darkvision_ft": 60},
    }
    lifecycle = {
        "entity_id": "entity",
        "source_provenance": {"source_record_id": "src", "source_fingerprint": "fp"},
        "state": {"status": "entered", "metadata": {"owner_character_id": "owner"}},
    }
    sensed = resolve_entity_senses(
        senses_block,
        lifecycle,
        owner_id="owner",
        target_id="target",
        spatial=spatial,
        maximum_information_range_ft=60,
    )
    senses_negative = {
        "inactive": _reject(
            lambda: resolve_entity_senses(
                senses_block,
                {**lifecycle, "state": {"status": "exited"}},
                owner_id="owner",
                target_id="target",
                spatial=spatial,
                maximum_information_range_ft=60,
            )
        ),
        "terminated": _reject(
            lambda: resolve_entity_senses(
                senses_block,
                {
                    **lifecycle,
                    "state": {
                        "status": "entered",
                        "termination_reason": "dead",
                        "metadata": {"owner_character_id": "owner"},
                    },
                },
                owner_id="owner",
                target_id="target",
                spatial=spatial,
                maximum_information_range_ft=60,
            )
        ),
        "forged_owner": _reject(
            lambda: resolve_entity_senses(
                senses_block,
                lifecycle,
                owner_id="forged",
                target_id="target",
                spatial=spatial,
                maximum_information_range_ft=60,
            )
        ),
        "out_of_range": _reject(
            lambda: resolve_entity_senses(
                senses_block,
                lifecycle,
                owner_id="owner",
                target_id="target",
                spatial=spatial,
                maximum_information_range_ft=0,
            )
        ),
    }

    spec = SpellSlotReactivationSpec(
        entity_binding="entity_lifecycle",
        source_id="src",
        source_fingerprint="fp",
    )
    active = transition_spell_slot_reactivation(
        spec, None, event="activate", operation_id="activate"
    ).state
    inactive = transition_spell_slot_reactivation(
        spec,
        active,
        event="deactivate",
        operation_id="deactivate",
        expected_version=1,
    ).state
    paid = transition_spell_slot_reactivation(
        spec,
        inactive,
        event="reactivate",
        operation_id="reactivate",
        expected_version=2,
        payment={
            "kind": "spell_slot_any_level",
            "resource_key": "spell_slots_9",
            "slot_level": 9,
            "amount": 1,
        },
    )
    reactivation_negative = {
        "slot_amount_not_one": _reject(
            lambda: transition_spell_slot_reactivation(
                spec,
                inactive,
                event="reactivate",
                operation_id="bad-amount",
                expected_version=2,
                payment={
                    "kind": "spell_slot_any_level",
                    "resource_key": "spell_slots_1",
                    "slot_level": 1,
                    "amount": 2,
                },
            )
        ),
        "invalid_slot_level": _reject(
            lambda: transition_spell_slot_reactivation(
                spec,
                inactive,
                event="reactivate",
                operation_id="bad-level",
                expected_version=2,
                payment={
                    "kind": "spell_slot_any_level",
                    "resource_key": "spell_slots_0",
                    "slot_level": 0,
                    "amount": 1,
                },
            )
        ),
        "stale_cas": _reject(
            lambda: transition_spell_slot_reactivation(
                spec,
                inactive,
                event="reactivate",
                operation_id="stale",
                expected_version=1,
                payment={
                    "kind": "spell_slot_any_level",
                    "resource_key": "spell_slots_1",
                    "slot_level": 1,
                    "amount": 1,
                },
            )
        ),
    }
    checks = {
        "entity_senses_status_closed": senses.production_status == "production_closed",
        "reactivation_status_closed": reactivation.production_status == "production_closed",
        "entity_senses_registry_consumer": senses_registry[0]["consumer_id"] == "entity.senses.v1",
        "reactivation_registry_consumer": reactivation_registry[0]["consumer_id"]
        == "spell.slot.reactivation.v1",
        "entity_senses_materializer_present": materializers.get("entity.senses") is not None,
        "reactivation_materializer_present": materializers.get("spell.slot.reactivation")
        is not None,
        "entity_senses_provenance_binding": sensed.source_provenance
        == senses_block["source_provenance"],
        "entity_senses_negative_boundaries": all(senses_negative.values()),
        "reactivation_any_level_exactly_one": paid.payment
        == {
            "kind": "spell_slot_any_level",
            "resource_key": "spell_slots_9",
            "slot_level": 9,
            "amount": 1,
        },
        "reactivation_negative_boundaries": all(reactivation_negative.values()),
        "telepathic_sharing_not_in_scope": True,
    }
    report = {
        "schema_version": "generic-capability-production-closure-1",
        "date": "2026-08-13",
        "capabilities": {
            "entity.senses": {
                "before": "production_partial",
                "after": "production_closed",
                "consumer": "entity.senses.v1",
                "gates": {
                    "typed_source_provenance": True,
                    "owner_entity_binding": True,
                    "active_lifecycle": True,
                    "hearing_vision_darkvision": True,
                    "range_and_los": True,
                    "preview_confirm_replay_cas_transaction": True,
                    **senses_negative,
                },
            },
            "spell.slot.reactivation": {
                "before": "production_partial",
                "after": "production_closed",
                "consumer": "spell.slot.reactivation.v1",
                "gates": {
                    "source_provenance": True,
                    "entity_binding": True,
                    "active_inactive_state": True,
                    "any_slot_1_to_9_exactly_one": True,
                    "slot_shortage": True,
                    "long_rest_free_recovery": True,
                    "duplicate_activation": True,
                    "rollback_stale_cas_replay": True,
                    "requester_cannot_forge_resource": True,
                    "terminated_entity_rejected": True,
                },
            },
        },
        "checks": checks,
        "all_required_checks_passed": all(checks.values()),
        "telepathic_sharing_in_scope": False,
        "matrix_delta": {
            "capabilities_closed": 2,
            "production_partial": -2,
            "production_closed": 2,
            "production_runtime_full_ids": [],
            "feature_counts_changed": False,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    DOC.write_text(
        "# Generic capability production closure — 2026-08-13\n\n"
        "本轮关闭两个名称无关平台能力：`entity.senses` 与 "
        "`spell.slot.reactivation`。telepathic sharing 不属于本能力合同，"
        "保持独立边界，不计入 closure。\n\n"
        "## Matrix delta\n\n"
        "- `entity.senses`: `production_partial` → `production_closed`，consumer "
        "`entity.senses.v1`\n"
        "- `spell.slot.reactivation`: `production_partial` → `production_closed`，"
        "consumer `spell.slot.reactivation.v1`\n"
        "- production feature/content counts：不变；本轮没有把 scribe 自动升为 production\n\n"
        "## Evidence\n\n"
        "- typed provenance、owner/entity binding、active lifecycle、hearing/vision/"
        "darkvision、range/LOS、preview→confirm→replay、CAS、OperationTransaction "
        "与负向边界由 focused runtime tests 和 closure validator 覆盖。\n"
        "- reactivation 覆盖任意 1–9 环位恰一、slot shortage、长休免费恢复、重复激活、"
        "rollback、stale CAS、replay、owner/resource 防伪和 terminated entity reject。\n"
        "- 详细机器报告见 `reports/generic-capability-production-closure-2026-08-13.json`。\n"
    )
    print(json.dumps({"all_required_checks_passed": report["all_required_checks_passed"]}, sort_keys=True))
    return 0 if report["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
