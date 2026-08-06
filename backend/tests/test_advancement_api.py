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
from dnd_dm_assistant.domain.feature_runtime import feature_runtime_action_projections


def _class_record(name: str, stable_id: str, path: str) -> dict[str, Any]:
    rows = "\n".join(
        f"| {level} | +{2 + (level - 1) // 4} | "
        f"{f'{name}子职' if level == 3 else '属性值提升' if level == 4 else f'{level}级特性'} |"
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
        "content_markdown": (
            "# 勇士\n"
            "### 3级 战斗专精\n"
            "作为附赠动作，你可以使用此特性 2 次，每次短休恢复。\n"
            "### 6级 勇气\n"
            "你可以作为动作使用此特性。"
        ),
    }
    (classes / "fighter.json").write_text(
        json.dumps(fighter, ensure_ascii=False), encoding="utf-8"
    )
    (classes / "champion.json").write_text(
        json.dumps(subclass, ensure_ascii=False), encoding="utf-8"
    )
    wizard = _class_record(
        "法师",
        "wizard-2024",
        "玩家手册2024/角色职业/法师/法师.htm",
    )
    wizard_rows = "\n".join(
        f"| {level} | +{2 + (level - 1) // 4} | "
        f"{'法师子职' if level == 3 else '属性值提升' if level == 4 else f'{level}级特性'}"
        f" | {3 + int(level >= 4)} | {3 + level} |"
        for level in range(1, 21)
    )
    wizard["content_markdown"] = (
        "# 法师\n生命值骰 Hit Point Die：每法师等级D6\n"
        "| 等级 | 熟练加值(PB) | 职业特性 | 戏法 | 准备法术 |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"{wizard_rows}\n"
    )
    (classes / "wizard.json").write_text(
        json.dumps(wizard, ensure_ascii=False), encoding="utf-8"
    )
    spells = corpus / "spells"
    spells.mkdir()
    spell_specs = [
        ("法师戏法一", "wiz-cantrip-1", 0, ["法师"]),
        ("法师戏法二", "wiz-cantrip-2", 0, ["法师"]),
        ("法师戏法三", "wiz-cantrip-3", 0, ["法师"]),
        *[
            (f"法师一环{index}", f"wiz-level1-{index}", 1, ["法师"])
            for index in range(1, 9)
        ],
        ("牧师一环", "cleric-level1", 1, ["牧师"]),
        ("法师二环", "wiz-level2", 2, ["法师"]),
    ]
    for name, stable_id, level, spell_classes in spell_specs:
        record = {
            "name": name,
            "stable_id": stable_id,
            "edition": "2024",
            "officiality": "official",
            "source_relative_path": (
                f"玩家手册2024/法术详述/{level}环.{name}/{name}.htm"
            ),
            "content_markdown": f"# {name}\n测试规则文本",
            "spell": {"level": level, "classes": spell_classes},
        }
        (spells / f"{stable_id}.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
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
    fighter = next(
        item for item in response.json()["classes"] if item["name"] == "战士"
    )
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


def test_advancement_materializes_all_prior_class_feature_levels(
    advancement_client: TestClient,
) -> None:
    campaign = _campaign(advancement_client)
    created = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "补齐职业运行时",
            "class_name": "战士",
            "level": 1,
            "experience": 900,
            "hp": 12,
            "max_hp": 12,
            "ability_scores": {"constitution": 14, "strength": 16},
            "class_levels": {"战士": 1},
        },
    ).json()

    response = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
        "/advancement/preview",
        json={
            "character_version": created["version"],
            "class_name": "战士",
            "dm_override_reason": "运行时物化夹具不重复构造法术选择",
        },
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    class_features = [
        item
        for item in preview["after"]["features"]
        if isinstance(item, dict)
        and item.get("kind") == "class_feature"
        and item.get("class_name") == "战士"
    ]
    assert {int(item["class_level"]) for item in class_features} == {1, 2}
    assert preview["after"]["feature_runtime"]["progression"]["class_levels"] == {
        "战士": 2
    }


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


def test_subclass_runtime_materializes_prior_and_current_feature_levels(
    advancement_client: TestClient,
) -> None:
    campaign = _campaign(advancement_client)
    created = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "补齐子职运行时",
            "class_name": "战士",
            "level": 2,
            "experience": 14_000,
            "hp": 20,
            "max_hp": 20,
            "ability_scores": {"constitution": 14, "strength": 16},
            "class_levels": {"战士": 2},
        },
    ).json()
    steps = [
        {"class_name": "战士", "subclass_name": "勇士"},
        {"class_name": "战士", "ability_increases": {"strength": 2}},
        {"class_name": "战士"},
        {"class_name": "战士"},
    ]
    response = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
        "/advancement/batch/preview",
        json={
            "character_version": created["version"],
            "steps": [
                {
                    **step,
                    "dm_override_reason": "子职运行时回填夹具不重复构造选择",
                }
                for step in steps
            ],
        },
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    subclass_features = [
        item
        for item in preview["after"]["features"]
        if isinstance(item, dict) and item.get("kind") == "subclass_feature"
    ]
    assert {int(item["class_level"]) for item in subclass_features} == {3, 6}
    assert all(item.get("feature_id") for item in subclass_features)


def test_subclass_actions_enter_canonical_runtime_blocks_without_becoming_fake_buttons(
    advancement_client: TestClient,
) -> None:
    campaign = _campaign(advancement_client)
    created = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "子职动作积木",
            "class_name": "战士",
            "level": 2,
            "experience": 900,
            "hp": 20,
            "max_hp": 20,
            "ability_scores": {"constitution": 14, "strength": 16},
            "class_levels": {"战士": 2},
        },
    ).json()
    response = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
        "/advancement/preview",
        json={
            "character_version": created["version"],
            "class_name": "战士",
            "subclass_name": "勇士",
        },
    )
    assert response.status_code == 200, response.text
    registry = response.json()["runtime_registry"]

    subclass_action = next(
        item
        for item in registry["actions"].values()
        if item.get("kind") == "subclass_feature_action"
    )
    assert subclass_action["runtime"]["automation_status"] == "partial"
    canonical = next(
        block
        for block in registry["feature_blocks"]
        if block["block_type"] == "action"
        and block["payload"].get("kind") == "subclass_feature_action"
    )
    assert canonical["automation_status"] == "partial"
    assert canonical["requires_dm_adjudication"] is True
    assert not any(
        action.get("name") == subclass_action.get("name")
        for action in feature_runtime_action_projections(registry)
    )


def test_wizard_advancement_rejects_wrong_class_level_and_preparation(
    advancement_client: TestClient,
) -> None:
    campaign = _campaign(advancement_client)
    initial_spells = [
        *[
            {
                "name": f"法师戏法{label}",
                "source_record_id": f"wiz-cantrip-{index}",
                "spell_level": 0,
                "classes": ["法师"],
                "prepared": True,
            }
            for index, label in enumerate(("一", "二", "三"), 1)
        ],
        *[
            {
                "name": f"法师一环{index}",
                "source_record_id": f"wiz-level1-{index}",
                "spell_level": 1,
                "classes": ["法师"],
                "prepared": index <= 4,
            }
            for index in range(1, 7)
        ],
    ]
    created = advancement_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "成长法师",
            "class_name": "法师",
            "level": 1,
            "experience": 300,
            "hp": 8,
            "max_hp": 8,
            "ability_scores": {"constitution": 14, "intelligence": 16},
            "class_levels": {"法师": 1},
            "spells": initial_spells,
        },
    ).json()
    path = (
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
        "/advancement/preview"
    )
    base = {
        "character_version": created["version"],
        "class_name": "法师",
    }

    wrong_class = advancement_client.post(
        path,
        json={
            **base,
            "spell_additions": [
                {
                    "name": "牧师一环",
                    "source_record_id": "cleric-level1",
                    "prepared": False,
                }
            ],
        },
    )
    assert wrong_class.status_code == 400
    assert "不属于法师法术表" in wrong_class.text

    too_high = advancement_client.post(
        path,
        json={
            **base,
            "spell_additions": [
                {
                    "name": "法师二环",
                    "source_record_id": "wiz-level2",
                    "prepared": False,
                }
            ],
        },
    )
    assert too_high.status_code == 400
    assert "最高只能选择1环" in too_high.text

    over_prepared = advancement_client.post(
        path,
        json={
            **base,
            "spell_additions": [
                {
                    "name": "法师一环7",
                    "source_record_id": "wiz-level1-7",
                    "prepared": True,
                },
                {
                    "name": "法师一环8",
                    "source_record_id": "wiz-level1-8",
                    "prepared": True,
                },
            ],
        },
    )
    assert over_prepared.status_code == 400
    assert "必须准备5个" in over_prepared.text

    valid = advancement_client.post(
        path,
        json={
            **base,
            "spell_additions": [
                {
                    "name": "法师一环7",
                    "source_record_id": "wiz-level1-7",
                    "prepared": True,
                },
                {
                    "name": "法师一环8",
                    "source_record_id": "wiz-level1-8",
                    "prepared": False,
                },
            ],
        },
    )
    assert valid.status_code == 200, valid.text
    assert next(
        item
        for item in valid.json()["choice_requirements"]
        if item["key"] == "spellbook_additions"
    )["maximum"] == 2
