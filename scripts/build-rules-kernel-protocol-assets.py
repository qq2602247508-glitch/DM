# ruff: noqa: N999
"""Build standalone JSON Schema and example assets for the rules kernel."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.domain.rules_kernel_protocol import (
    RulesKernelAdjudicationDecision,
    RulesKernelAdjudicationRequest,
    RulesKernelCommand,
    RulesKernelConfirmation,
    RulesKernelPreview,
    RulesKernelResult,
    RulesKernelSceneDelta,
    SceneQuery,
    protocol_json_schema,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/protocols"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    schemas = {
        "rules-kernel-command-v1.schema.json": RulesKernelCommand,
        "rules-kernel-preview-v1.schema.json": RulesKernelPreview,
        "rules-kernel-confirmation-v1.schema.json": RulesKernelConfirmation,
        "rules-kernel-result-v1.schema.json": RulesKernelResult,
        "scene-query-v1.schema.json": SceneQuery,
        "scene-delta-v1.schema.json": RulesKernelSceneDelta,
    }
    for filename, model in schemas.items():
        schema = protocol_json_schema(model)
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        _write(OUT / filename, schema)
    _write(
        OUT / "dm-adjudication-v1.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "RulesKernelDMAdjudicationV1",
            "oneOf": [
                protocol_json_schema(RulesKernelAdjudicationRequest),
                protocol_json_schema(RulesKernelAdjudicationDecision),
            ],
        },
    )
    examples = {
        "spell-attack.json": {
            "schema_version": "rules-kernel-1",
            "command_id": "cmd-spell-attack-001",
            "idempotency_key": "idem-spell-attack-001",
            "campaign_id": "campaign-001",
            "scene_id": "scene-001",
            "combat_id": "combat-001",
            "actor_id": "combatant-caster",
            "content_id": "typed-content:spell-attack",
            "content_kind": "spell",
            "action_kind": "content",
            "target_intent": {"target_ids": ["combatant-target"], "target_kind": "one_creature"},
            "roll_inputs": {"attack_roll_total": 17, "resolution_total": 8},
            "expected_versions": {"actor_version": 1, "target_versions": {"combatant-target": 1}},
            "metadata": {"clause_types": ["attack_roll", "damage"], "effects": [{"kind": "damage", "amount": 8, "damage_type": "force"}]},
        },
        "area-save.json": {
            "schema_version": "rules-kernel-1",
            "command_id": "cmd-area-save-001",
            "idempotency_key": "idem-area-save-001",
            "campaign_id": "campaign-001",
            "scene_id": "scene-001",
            "combat_id": "combat-001",
            "actor_id": "combatant-caster",
            "content_id": "typed-content:area-save",
            "content_kind": "spell",
            "action_kind": "content",
            "spatial_intent": {"origin": {"row": 2, "col": 2}, "shape": "sphere", "size_ft": 15},
            "target_intent": {"target_kind": "area"},
            "roll_inputs": {"resolution_total": 12, "save_succeeded": False},
            "metadata": {"clause_types": ["area", "saving_throw", "damage"], "effects": [{"kind": "damage", "amount": 12, "damage_type": "fire"}]},
        },
        "healing.json": {
            "schema_version": "rules-kernel-1",
            "command_id": "cmd-healing-001",
            "idempotency_key": "idem-healing-001",
            "campaign_id": "campaign-001",
            "combat_id": "combat-001",
            "actor_id": "combatant-cleric",
            "content_id": "typed-content:healing",
            "content_kind": "feature",
            "action_kind": "content",
            "target_intent": {"target_ids": ["combatant-ally"], "target_kind": "one_creature"},
            "roll_inputs": {"resolution_total": 9},
            "metadata": {"clause_types": ["healing"], "effects": [{"kind": "healing", "amount": 9}]},
        },
        "summon.json": {
            "schema_version": "rules-kernel-1",
            "command_id": "cmd-summon-001",
            "idempotency_key": "idem-summon-001",
            "campaign_id": "campaign-001",
            "scene_id": "scene-001",
            "combat_id": "combat-001",
            "actor_id": "combatant-caster",
            "content_id": "typed-content:summon",
            "content_kind": "spell",
            "action_kind": "summon_known_profile",
            "spatial_intent": {"destination": {"row": 3, "col": 3}, "entity_profile_id": "compendium-profile-001"},
            "expected_versions": {"actor_version": 1},
            "metadata": {"clause_types": ["summon_known_profile"]},
        },
        "teleport.json": {
            "schema_version": "rules-kernel-1",
            "command_id": "cmd-teleport-001",
            "idempotency_key": "idem-teleport-001",
            "campaign_id": "campaign-001",
            "scene_id": "scene-001",
            "combat_id": "combat-001",
            "actor_id": "combatant-rogue",
            "content_id": "typed-content:teleport",
            "content_kind": "feature",
            "action_kind": "teleport",
            "spatial_intent": {"destination": {"row": 5, "col": 5}, "maximum_distance_ft": 30, "movement_kind": "teleport"},
            "expected_versions": {"actor_version": 1},
            "metadata": {"clause_types": ["teleport"]},
        },
        "dm-adjudication.json": {
            "schema_version": "dm-adjudication-1",
            "adjudication_id": "adjudication-001",
            "source_command_id": "cmd-freeform-001",
            "content_id": "typed-content:freeform",
            "category": "target_semantics",
            "source_text_evidence": "The typed source leaves the affected creature relationship open.",
            "open_questions": ["Which visible creature is the secondary target?"],
            "allowed_decision_schema": ["approved_targets", "notes"],
        },
    }
    for filename, example in examples.items():
        _write(OUT / "examples" / filename, example)
    _write(
        OUT / "negative-examples.json",
        [
            {"schema_version": "rules-kernel-999", "command_id": "bad", "idempotency_key": "bad-key-000", "campaign_id": "c", "actor_id": "a", "content_kind": "spell", "content_id": "x", "extra_callback": "import os"},
            {"schema_version": "rules-kernel-1", "command_id": "bad-target", "idempotency_key": "bad-target-000", "campaign_id": "c", "actor_id": "a", "content_kind": "spell", "content_id": "x", "target_intent": {"target_kind": "one_creature", "target_ids": ["a", "a"]}},
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
