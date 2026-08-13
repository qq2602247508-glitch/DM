from __future__ import annotations

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.domain.feature_capabilities import default_capability_catalog


def test_generic_capabilities_are_closed_and_registered_without_feature_name() -> None:
    catalog = default_capability_catalog()
    assert catalog.get("entity.senses").production_status == "production_closed"
    assert catalog.get("spell.slot.reactivation").production_status == "production_closed"
    senses = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={"entity_senses": [{"resolution_kind": "entity_senses"}]},
    )
    assert [item["consumer_id"] for item in senses] == ["entity.senses.v1"]
    reactivation = resolve_production_consumers(
        content_kind="advancement",
        runtime_schema_version="feature-runtime-1",
        blocks={"spell_slot_reactivations": [{"resolution_kind": "spell_slot_reactivation"}]},
    )
    assert [item["consumer_id"] for item in reactivation] == [
        "spell.slot.reactivation.v1"
    ]
    timed = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks={
            "effects": [{"parameters": {"type": "timed_modifier"}}],
            "target_selection": [{"kind": "one_creature"}],
            "duration": [{"unit": "hours", "value": 1}],
        },
    )
    assert [item["consumer_id"] for item in timed] == ["spell.timed_modifier.v1"]


def test_telepathic_sharing_is_not_implied_by_entity_senses_closure() -> None:
    descriptor = default_capability_catalog().get("entity.senses")
    assert descriptor.known_limitations == ()
    assert "telepathic" not in descriptor.consumer
