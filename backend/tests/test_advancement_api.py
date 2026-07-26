from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.config import Settings


def _class_record(name: str, stable_id: str, path: str) -> dict[str, Any]:
    rows = "\n".join(
        f"| {level} | +{2 + (level - 1) // 4} | "
        f"{'战士子职' if level == 3 else '属性值提升' if level == 4 else f'{level}级特性'} |"
        for level in range(1, 21)
    )
    return {
        "name": name,
        "stable_id": stable_id,
        "edition": "2024",
        "officiality": "official",
        "source_relative_path": path,
        "content_markdown": (
            f"# {name}\n生命值骰 Hit Point Die：每{name}等级D10\n"
            "| 等级 | 熟练加值(PB) | 职业特性 |\n"
            "| --- | --- | --- |\n"
            f"{rows}\n"
        ),
    }


@pytest.fixture
def advancement_client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'advancement.db'}"
    corpus = tmp_path / "corpus"
    classes = corpus / "classes"
    classes.mkdir(parents=True)
    fighter = _class_record(
        "战士",
        "fighter-2024",
        "玩家手册2024/角色职业/战士/战士.htm",
    )
    subclass = {
        **_class_record(
            "勇士",
            "champion-2024",
            "玩家手册2024/角色职业/战士/勇士.htm",
        ),
        "content_markdown": "# 勇士",
    }
    (classes / "fighter.json").write_text(
        json.dumps(fighter, ensure_ascii=False), encoding="utf-8"
    )
    (classes / "champion.json").write_text(
        json.dumps(subclass, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(
        environment="test",
        database_url=database_url,
        rag_corpus_json_root=corpus,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def _campaign(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/v1/campaigns", json={"name": "成长测试"})
    assert response.status_code == 201
    return response.json()


def test_character_options_load_complete_local_2024_progression(
    advancement_client: TestClient,
) -> None:
    response = advancement_client.get("/api/v1/rules/character-options")
    assert response.status_code == 200
    fighter = response.json()["classes"][0]
    assert fighter["name"] == "战士"
    assert len(fighter["levels"]) == 20
    assert fighter["subclasses"][0]["name"] == "勇士"


def test_advancement_preview_confirm_and_idempotency(
    advancement_client: TestClient,
) -> None:
    campaign = _campaign(advancement_client)
    created = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "成长战士",
            "class_name": "战士",
            "level": 1,
            "experience": 300,
            "hp": 12,
            "max_hp": 12,
            "ability_scores": {
                "strength": 16,
                "dexterity": 12,
                "constitution": 14,
                "intelligence": 10,
                "wisdom": 10,
                "charisma": 8,
            },
            "class_levels": {"战士": 1},
        },
    ).json()
    body = {
        "character_version": created["version"],
        "class_name": "战士",
        "hp_mode": "fixed",
    }
    preview_response = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
        "/advancement/preview",
        json=body,
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["to_level"] == 2
    assert preview["hp_gain"] == 8
    assert preview["after"]["class_levels"] == {"战士": 2}

    confirm_body = {
        **body,
        "preview_token": preview["preview_token"],
        "idempotency_key": "advance-fighter-0001",
    }
    confirm_response = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
        "/advancement/confirm",
        json=confirm_body,
    )
    assert confirm_response.status_code == 200, confirm_response.text
    result = confirm_response.json()
    updated = advancement_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
    ).json()
    assert updated["level"] == 2
    assert updated["max_hp"] == 20
    assert updated["class_levels"] == {"战士": 2}

    replay = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
        "/advancement/confirm",
        json=confirm_body,
    )
    assert replay.status_code == 200
    assert replay.json()["advancement_record_id"] == result["advancement_record_id"]


def test_level_three_requires_valid_subclass(
    advancement_client: TestClient,
) -> None:
    campaign = _campaign(advancement_client)
    created = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "二级战士",
            "class_name": "战士",
            "level": 2,
            "experience": 900,
            "hp": 20,
            "max_hp": 20,
            "ability_scores": {"constitution": 14, "strength": 16},
            "class_levels": {"战士": 2},
        },
    ).json()
    path = (
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
        "/advancement/preview"
    )
    missing = advancement_client.post(
        path,
        json={
            "character_version": created["version"],
            "class_name": "战士",
        },
    )
    assert missing.status_code == 400
    valid = advancement_client.post(
        path,
        json={
            "character_version": created["version"],
            "class_name": "战士",
            "subclass_name": "勇士",
        },
    )
    assert valid.status_code == 200
    assert valid.json()["subclass_name"] == "勇士"
