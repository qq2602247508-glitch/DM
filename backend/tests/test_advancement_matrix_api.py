from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.advancement_choices import CORE_CLASSES_2024


@pytest.fixture(scope="module")
def matrix_client(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[TestClient]:
    database = tmp_path_factory.mktemp("advancement-matrix") / "matrix.db"
    database_url = f"sqlite:///{database}"
    previous_database_url = os.environ.get("DND_DM_DATABASE_URL")
    os.environ["DND_DM_DATABASE_URL"] = database_url
    try:
        command.upgrade(Config("backend/alembic.ini"), "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DND_DM_DATABASE_URL", None)
        else:
            os.environ["DND_DM_DATABASE_URL"] = previous_database_url
    settings = Settings(
        environment="test",
        database_url=database_url,
        rag_corpus_json_root=Path("data/generated-content/dnd5e_chm/json"),
    )
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture(scope="module")
def matrix_campaign(matrix_client: TestClient) -> dict[str, Any]:
    response = matrix_client.post(
        "/api/v1/campaigns",
        json={"name": "升级矩阵验收"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(scope="module")
def character_options(matrix_client: TestClient) -> dict[str, Any]:
    response = matrix_client.get("/api/v1/rules/character-options")
    assert response.status_code == 200, response.text
    return response.json()


def _abilities() -> dict[str, int]:
    return {
        "strength": 14,
        "dexterity": 14,
        "constitution": 14,
        "intelligence": 14,
        "wisdom": 14,
        "charisma": 14,
    }


def _create_character(
    client: TestClient,
    campaign_id: str,
    *,
    class_name: str,
    level: int,
    experience: int,
    suffix: str,
    spells: list[dict[str, Any]] | None = None,
    subclass_name: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"{class_name}-{suffix}",
        "class_name": class_name,
        "level": level,
        "experience": experience,
        "hp": 12,
        "max_hp": 12,
        "ability_scores": _abilities(),
        "class_levels": {class_name: level},
    }
    if spells is not None:
        body["spells"] = spells
    if subclass_name is not None:
        body["subclass_choices"] = {class_name: subclass_name}
    response = client.post(
        f"/api/v1/campaigns/{campaign_id}/characters",
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _preview_path(campaign_id: str, character_id: str) -> str:
    return (
        f"/api/v1/campaigns/{campaign_id}/characters/{character_id}"
        "/advancement/preview"
    )


def _class_option(options: dict[str, Any], class_name: str) -> dict[str, Any]:
    return next(item for item in options["classes"] if item["name"] == class_name)


def test_all_core_classes_have_a_legal_level_two_preview(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
) -> None:
    """One API matrix covers every core class without 12 database fixtures."""

    observed: set[str] = set()
    for class_name in CORE_CLASSES_2024:
        character = _create_character(
            matrix_client,
            matrix_campaign["id"],
            class_name=class_name,
            level=1,
            experience=300,
            suffix="合法二级",
        )
        response = matrix_client.post(
            _preview_path(matrix_campaign["id"], character["id"]),
            json={
                "character_version": character["version"],
                "class_name": class_name,
            },
        )
        assert response.status_code == 200, (
            f"{class_name} level 2 preview failed: {response.text}"
        )
        preview = response.json()
        assert preview["class_name"] == class_name
        assert preview["class_level"] == 2
        assert preview["to_level"] == 2
        assert isinstance(preview["choice_requirements"], list)
        assert isinstance(preview["resource_updates"], dict)
        observed.add(class_name)
    assert observed == set(CORE_CLASSES_2024)


@pytest.mark.parametrize("class_name", ["战士", "法师", "牧师"])
def test_level_three_requires_and_accepts_a_catalog_subclass(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
    class_name: str,
) -> None:
    class_option = _class_option(character_options, class_name)
    subclass_name = class_option["subclasses"][0]["name"]
    character = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name=class_name,
        level=2,
        experience=900,
        suffix="子职",
    )
    path = _preview_path(matrix_campaign["id"], character["id"])
    base = {
        "character_version": character["version"],
        "class_name": class_name,
    }

    missing = matrix_client.post(path, json=base)
    assert missing.status_code == 400
    assert "subclass" in missing.text

    valid = matrix_client.post(
        path,
        json={**base, "subclass_name": subclass_name},
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["subclass_name"] == subclass_name
    requirement = next(
        item
        for item in valid.json()["choice_requirements"]
        if item["key"] == "subclass"
    )
    assert requirement["minimum"] == requirement["maximum"] == 1


@pytest.mark.parametrize("class_name", ["野蛮人", "战士", "游荡者"])
def test_level_four_requires_exactly_one_asi_or_feat_path(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
    class_name: str,
) -> None:
    subclass_name = _class_option(character_options, class_name)["subclasses"][0]["name"]
    character = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name=class_name,
        level=3,
        experience=2_700,
        suffix="属性提升",
        subclass_name=subclass_name,
    )
    path = _preview_path(matrix_campaign["id"], character["id"])
    base = {
        "character_version": character["version"],
        "class_name": class_name,
    }

    assert matrix_client.post(path, json=base).status_code == 400
    both = matrix_client.post(
        path,
        json={
            **base,
            "ability_increases": {"strength": 2},
            "feat_choice": "测试专长",
        },
    )
    assert both.status_code == 400

    valid = matrix_client.post(
        path,
        json={**base, "ability_increases": {"strength": 2}},
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["after"]["ability_scores"]["strength"] == 16


def test_wizard_spell_matrix_rejects_wrong_class_ring_count_and_preparation(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
) -> None:
    spells = character_options["spells"]
    wizard_cantrips = [
        item for item in spells if item["level"] == 0 and "法师" in item["classes"]
    ][:3]
    wizard_level_one = [
        item for item in spells if item["level"] == 1 and "法师" in item["classes"]
    ][:8]
    wrong_class = next(
        item
        for item in spells
        if item["level"] == 1 and "法师" not in item["classes"]
    )
    too_high = next(
        item for item in spells if item["level"] == 2 and "法师" in item["classes"]
    )
    assert len(wizard_cantrips) == 3
    assert len(wizard_level_one) == 8

    initial_spells = [
        *[
            {
                **spell,
                "spell_level": 0,
                "prepared": True,
                "class_name": "法师",
            }
            for spell in wizard_cantrips
        ],
        *[
            {
                **spell,
                "spell_level": 1,
                "prepared": index < 4,
                "class_name": "法师",
            }
            for index, spell in enumerate(wizard_level_one[:6])
        ],
    ]
    character = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="法师",
        level=1,
        experience=300,
        suffix="法术限制",
        spells=initial_spells,
    )
    path = _preview_path(matrix_campaign["id"], character["id"])
    base = {
        "character_version": character["version"],
        "class_name": "法师",
    }

    for illegal_spell in (wrong_class, too_high):
        response = matrix_client.post(
            path,
            json={
                **base,
                "spell_additions": [{**illegal_spell, "prepared": False}],
            },
        )
        assert response.status_code == 400, response.text

    only_one_new = matrix_client.post(
        path,
        json={
            **base,
            "spell_additions": [
                {**wizard_level_one[6], "prepared": True},
            ],
        },
    )
    assert only_one_new.status_code == 400
    assert "2个新法师法术" in only_one_new.text

    over_prepared = matrix_client.post(
        path,
        json={
            **base,
            "spell_additions": [
                {**wizard_level_one[6], "prepared": True},
                {**wizard_level_one[7], "prepared": True},
            ],
        },
    )
    assert over_prepared.status_code == 400
    assert "必须准备5个" in over_prepared.text


def test_confirm_is_idempotent_and_persists_once(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
) -> None:
    character = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="战士",
        level=1,
        experience=300,
        suffix="幂等",
    )
    body = {
        "character_version": character["version"],
        "class_name": "战士",
    }
    preview = matrix_client.post(
        _preview_path(matrix_campaign["id"], character["id"]),
        json=body,
    ).json()
    confirm_body = {
        **body,
        "preview_token": preview["preview_token"],
        "idempotency_key": "matrix-fighter-level-two",
    }
    path = (
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{character['id']}"
        "/advancement/confirm"
    )
    first = matrix_client.post(path, json=confirm_body)
    replay = matrix_client.post(path, json=confirm_body)
    assert first.status_code == replay.status_code == 200
    assert replay.json()["advancement_record_id"] == first.json()[
        "advancement_record_id"
    ]

    updated = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{character['id']}"
    ).json()
    history = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{character['id']}"
        "/advancement"
    ).json()
    assert updated["level"] == 2
    assert len(history["items"]) == 1
