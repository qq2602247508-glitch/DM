from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dnd_dm_assistant.application.player_rules_search import PlayerRulesSearch


def test_content_pack_registry_reports_safe_local_imports(campaign_client: TestClient) -> None:
    response = campaign_client.get("/api/v1/rules/content-packs")
    assert response.status_code == 200, response.text
    by_key = {item["key"]: item for item in response.json()["items"]}

    assert set(by_key) == {
        "xanathars-guide",
        "tashas-cauldron",
        "mordenkainen-multiverse",
        "fizbans-treasury",
        "bigbys-glory",
        "book-of-many-things",
    }
    assert by_key["mordenkainen-multiverse"]["entry_counts"]["monster"] >= 200
    assert by_key["bigbys-glory"]["status_counts"]["needs_normalization"] > 0
    assert by_key["fizbans-treasury"]["status_counts"]["imported"] > 0


def test_campaign_content_packs_gate_catalog_and_character_spell_options(
    campaign_client: TestClient,
) -> None:
    disabled = campaign_client.post("/api/v1/campaigns", json={"name": "核心规则团"})
    assert disabled.status_code == 201, disabled.text
    disabled_campaign = disabled.json()
    disabled_root = f"/api/v1/campaigns/{disabled_campaign['id']}/compendium"

    assert campaign_client.get(
        f"{disabled_root}?entry_type=spell&text=阿莎德隆奔行&page_size=10"
    ).json()["items"] == []
    assert "阿莎德隆奔行" not in {
        item["name"]
        for item in campaign_client.get(
            f"/api/v1/rules/character-options?campaign_id={disabled_campaign['id']}"
        ).json()["spells"]
    }

    enabled = campaign_client.post(
        "/api/v1/campaigns",
        json={
            "name": "扩展资料团",
            "allow_legacy": True,
            "enabled_content_packs": ["fizbans-treasury", "bigbys-glory"],
        },
    )
    assert enabled.status_code == 201, enabled.text
    campaign = enabled.json()
    assert campaign["enabled_content_packs"] == ["fizbans-treasury", "bigbys-glory"]
    root = f"/api/v1/campaigns/{campaign['id']}/compendium"

    spells = campaign_client.get(
        f"{root}?entry_type=spell&text=阿莎德隆奔行&content_pack=fizbans-treasury&page_size=10"
    )
    assert spells.status_code == 200, spells.text
    ashardalon = spells.json()["items"]
    assert len(ashardalon) == 1
    assert ashardalon[0]["filters_json"]["content_pack_status"] == "imported"
    assert ashardalon[0]["rules_json"]["rule_plan"]["source_kind"] == "spell"
    assert all(item["name"] != "巨龙法术" for item in ashardalon)

    monsters = campaign_client.get(
        f"{root}?entry_type=monster&text=墓石尸妖&content_pack=bigbys-glory&page_size=10"
    )
    assert monsters.status_code == 200, monsters.text
    tomb_wight = next(item for item in monsters.json()["items"] if item["name"] == "墓石尸妖")
    assert tomb_wight["filters_json"]["content_pack_status"] == "needs_normalization"
    assert tomb_wight["rules_json"]["armor_class"] == 19
    assert tomb_wight["rules_json"]["hp"] == 138

    spell_names = {
        item["name"]
        for item in campaign_client.get(
            f"/api/v1/rules/character-options?campaign_id={campaign['id']}"
        ).json()["spells"]
    }
    assert "阿莎德隆奔行" in spell_names

    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "巨人遗迹"},
    ).json()
    instantiated = campaign_client.post(
        f"{root}/{tomb_wight['id']}/instantiate",
        json={"target_type": "scene", "target_id": scene["id"]},
    )
    assert instantiated.status_code == 201, instantiated.text

    blocked_scene = campaign_client.post(
        f"/api/v1/campaigns/{disabled_campaign['id']}/scenes",
        json={"name": "未启用的遗迹"},
    ).json()
    blocked = campaign_client.post(
        f"{disabled_root}/{tomb_wight['id']}/instantiate",
        json={"target_type": "scene", "target_id": blocked_scene["id"]},
    )
    assert blocked.status_code == 404


def test_content_pack_selection_can_be_changed_and_rejects_unknown_keys(
    campaign_client: TestClient,
) -> None:
    invalid = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "坏资料包", "enabled_content_packs": ["not-a-book"]},
    )
    assert invalid.status_code == 422

    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "后开资料包"}).json()
    blocked = campaign_client.patch(
        f"/api/v1/campaigns/{campaign['id']}",
        headers={"If-Match": '"1"'},
        json={"enabled_content_packs": ["xanathars-guide"]},
    )
    assert blocked.status_code == 400
    assert "allow_legacy" in blocked.text
    updated = campaign_client.patch(
        f"/api/v1/campaigns/{campaign['id']}",
        headers={"If-Match": '"1"'},
        json={
            "allow_legacy": True,
            "enabled_content_packs": ["xanathars-guide"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["enabled_content_packs"] == ["xanathars-guide"]
    entries = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/compendium?entry_type=spell&text=魔石术&page_size=10"
    ).json()["items"]
    assert any(item["filters_json"]["content_pack_key"] == "xanathars-guide" for item in entries)


def test_extension_character_options_are_campaign_gated_and_truthfully_normalized(
    campaign_client: TestClient,
) -> None:
    disabled = campaign_client.post("/api/v1/campaigns", json={"name": "无扩展车卡"}).json()
    assert campaign_client.get(
        f"/api/v1/rules/character-options?campaign_id={disabled['id']}"
    ).json()["extension_character_options"] == []

    enabled = campaign_client.post(
        "/api/v1/campaigns",
        json={
            "name": "塔莎车卡",
            "allow_legacy": True,
            "enabled_content_packs": ["tashas-cauldron"],
        },
    ).json()
    options = campaign_client.get(
        f"/api/v1/rules/character-options?campaign_id={enabled['id']}"
    ).json()
    structured = next(
        item
        for item in options["extension_character_options"]
        if item["name"] == "奇械师（旧版）"
    )
    assert structured["normalization_status"] == "structured"
    assert structured["automation_status"] == "partial"
    assert structured["selectable_for_automatic_advancement"] is True

    unstructured = next(
        item
        for item in options["extension_character_options"]
        if item["normalization_status"] == "dm_choice"
    )
    assert unstructured["automation_status"] == "dm_only"
    assert unstructured["selectable_for_automatic_advancement"] is False


def test_player_rule_search_only_exposes_enabled_source_books() -> None:
    search = PlayerRulesSearch(Path("data/generated-content/dnd5e_chm/json"))
    assert not any(item["name"] == "阿莎德隆奔行" for item in search.search("阿莎德隆奔行"))

    enabled = search.search(
        "阿莎德隆奔行",
        enabled_content_packs=["fizbans-treasury"],
    )
    item = next(item for item in enabled if item["name"] == "阿莎德隆奔行")
    assert item["content_pack_key"] == "fizbans-treasury"
