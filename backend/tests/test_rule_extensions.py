from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def test_rule_extension_catalog_is_explicit_and_source_aware(campaign_client: TestClient) -> None:
    response = campaign_client.get("/api/v1/rules/extensions")
    assert response.status_code == 200
    items = response.json()["items"]
    by_key = {item["key"]: item for item in items}
    assert by_key["initiative_fixed"]["requires_legacy"] is True
    assert by_key["multiclassing"]["source_record_name"] == "兼职规则"
    assert by_key["cover"]["automation_status"] == "partial"


def test_campaign_rejects_legacy_extension_without_explicit_toggle(
    campaign_client: TestClient,
) -> None:
    response = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "No Legacy", "enabled_rule_extensions": ["initiative_fixed"]},
    )
    assert response.status_code == 422
    assert "allow_legacy" in str(response.json())


def test_campaign_materializes_selected_rule_atoms_and_plans(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns",
        json={
            "name": "Variant Rules",
            "allow_legacy": True,
            "enabled_rule_extensions": ["initiative_fixed", "multiclassing"],
        },
    )
    assert campaign.status_code == 201
    body: dict[str, Any] = campaign.json()
    assert body["enabled_rule_extensions"] == ["initiative_fixed", "multiclassing"]

    atoms = campaign_client.get(
        f"/api/v1/campaigns/{body['id']}/compendium?entry_type=rule&page_size=100"
    )
    assert atoms.status_code == 200
    items = atoms.json()["items"]
    seeded = {item["name"]: item for item in items if item["source_kind"] == "official"}
    assert {"固定先攻", "兼职"} <= seeded.keys()
    assert seeded["固定先攻"]["rules_json"]["rule_plan"]["source_kind"] == "rule"
    assert seeded["固定先攻"]["filters_json"]["automation_status"] == "dm_only"


def test_campaign_rejects_conflicting_extensions(campaign_client: TestClient) -> None:
    response = campaign_client.post(
        "/api/v1/campaigns",
        json={
            "name": "Conflicting Rules",
            "allow_legacy": True,
            "enabled_rule_extensions": ["initiative_fixed", "initiative_side"],
        },
    )
    assert response.status_code == 422
    assert "conflicting" in str(response.json())


def test_encumbrance_extension_selects_the_inventory_variant_executor(
    campaign_client: TestClient,
) -> None:
    campaign_response = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "变体负重团", "enabled_rule_extensions": ["encumbrance_variant"]},
    )
    assert campaign_response.status_code == 201
    campaign = campaign_response.json()
    assert campaign["encumbrance_mode"] == "variant"

    base = f"/api/v1/campaigns/{campaign['id']}"
    character_response = campaign_client.post(
        f"{base}/characters",
        json={
            "name": "搬运工",
            "ability_scores": {"strength": 10},
            "hp": 10,
            "max_hp": 10,
        },
    )
    assert character_response.status_code == 201
    item_response = campaign_client.post(
        f"{base}/items",
        json={
            "name": "沉重的补给箱",
            "quantity": 1,
            "unit_weight_lb": 60,
            "owner_character_id": character_response.json()["id"],
        },
    )
    assert item_response.status_code == 201

    inventory = campaign_client.get(
        f"{base}/characters/{character_response.json()['id']}/inventory"
    )
    assert inventory.status_code == 200
    summary = inventory.json()
    assert summary["encumbrance_mode"] == "variant"
    assert summary["state"] == "encumbered"
