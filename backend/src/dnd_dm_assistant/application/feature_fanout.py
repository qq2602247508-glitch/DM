"""Production capability fan-out cohort used by reports and regression tests."""

from __future__ import annotations

from dnd_dm_assistant.domain.feature_ir import FeatureSpec

FANOUT_FEATURE_IDS = (
    "dnd2024.cohort.roving-speed",
    "dnd2024.cohort.wild-senses-range",
    "dnd2024.cohort.second-story-jump",
    "dnd2024.cohort.water-affinity",
    "dnd2024.cohort.sequence-awareness",
    "dnd2024.cohort.swift-glimmer",
)


def production_fanout_specs() -> tuple[FeatureSpec, ...]:
    specs: list[FeatureSpec] = []
    for index, feature_id in enumerate(FANOUT_FEATURE_IDS, start=1):
        specs.append(
            FeatureSpec.from_dict(
                {
                    "schema_version": "feature-ir-1",
                    "feature_id": feature_id,
                    "namespace": "dnd.2024.cohort",
                    "pack_id": "dnd2024-cohort",
                    "pack_version": "1.0.0",
                    "ruleset_version": "2024",
                    "source_record_id": feature_id,
                    "source_name": feature_id.rsplit(".", 1)[-1],
                    "source_trust": "authored_ir",
                    "localized_names": {},
                    "class_name": "多职业生产扇出簇",
                    "subclass_name": None,
                    "level": index,
                    "source_completeness": "complete",
                    "clauses": [
                        {
                            "clause_id": "shared-passive",
                            "trigger": "advancement_confirmed",
                            "activation": "automatic",
                            "action_economy": "none",
                            "targeting": {"kind": "self", "parameters": {}},
                            "effects": [
                                {
                                    "operator": "grant_passive_modifier",
                                    "parameters": {
                                        "stat": "speed_ft",
                                        "operation": "add",
                                        "value": index,
                                        "scope": "self",
                                        "applies_when": "always",
                                        "id": f"{feature_id}:speed",
                                    },
                                }
                            ],
                        }
                    ],
                    "dependencies": [],
                    "compatibility": {
                        "consumer_apis": ["feature_runtime_registry", "combat_start_modifiers"]
                    },
                }
            )
        )
    return tuple(specs)
