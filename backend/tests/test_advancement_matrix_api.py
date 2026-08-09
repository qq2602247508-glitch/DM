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
from dnd_dm_assistant.domain.noncombat_actions import skill_modifier


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
    class_levels: dict[str, int] | None = None,
    skills: dict[str, Any] | None = None,
    proficiencies: list[Any] | None = None,
    features: list[Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"{class_name}-{suffix}",
        "class_name": class_name,
        "level": level,
        "experience": experience,
        "hp": 12,
        "max_hp": 12,
        "ability_scores": _abilities(),
        "class_levels": class_levels or {class_name: level},
    }
    if skills is not None:
        body["skills"] = skills
    if proficiencies is not None:
        body["proficiencies"] = proficiencies
    if features is not None:
        body["features"] = features
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
    return f"/api/v1/campaigns/{campaign_id}/characters/{character_id}/advancement/preview"


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
                "dm_override_reason": "矩阵夹具不重复构造1级完整法术与职业选项",
            },
        )
        assert response.status_code == 200, f"{class_name} level 2 preview failed: {response.text}"
        preview = response.json()
        assert preview["class_name"] == class_name
        assert preview["class_level"] == 2
        assert preview["to_level"] == 2
        assert isinstance(preview["choice_requirements"], list)
        assert isinstance(preview["resource_updates"], dict)
        observed.add(class_name)
    assert observed == set(CORE_CLASSES_2024)


def test_batch_advancement_persists_each_step_and_runtime_sheet_state(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
) -> None:
    fighter = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="战士",
        level=1,
        experience=900,
        suffix="批量运行时",
    )
    subclass = _class_option(character_options, "战士")["subclasses"][0]["name"]
    base_path = (
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{fighter['id']}/advancement/batch"
    )
    request = {
        "character_version": fighter["version"],
        "steps": [
            {
                "class_name": "战士",
                "dm_override_reason": "矩阵夹具仅验证逐级事务状态",
            },
            {
                "class_name": "战士",
                "subclass_name": subclass,
                "dm_override_reason": "矩阵夹具仅验证逐级事务状态",
            },
        ],
    }
    preview_response = matrix_client.post(f"{base_path}/preview", json=request)
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["to_level"] == 3
    assert [step["to_level"] for step in preview["steps"]] == [2, 3]
    assert preview["after"]["resources"]["action_surge"]["recovery"] == "short_rest"
    weapon_mastery = next(
        feature
        for feature in preview["after"]["features"]
        if isinstance(feature, dict) and feature.get("name") == "武器精通"
    )
    assert weapon_mastery["runtime"]["automation_status"] == "full"
    assert (
        "weapon_mastery_reconfiguration:战士"
        in weapon_mastery["runtime"]["registry"]["actions"]
    )

    confirmed_response = matrix_client.post(
        f"{base_path}/confirm",
        json={
            **request,
            "preview_token": preview["preview_token"],
            "idempotency_key": "batch-runtime-state-0001",
        },
    )
    assert confirmed_response.status_code == 200, confirmed_response.text
    confirmed = confirmed_response.json()
    assert len(confirmed["advancement_record_ids"]) == 2
    persisted = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{fighter['id']}"
    ).json()
    assert persisted["level"] == 3
    assert persisted["resources"]["action_surge"]["max"] == 1
    assert (
        len(
            matrix_client.get(
                f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{fighter['id']}/advancement"
            ).json()["items"]
        )
        >= 2
    )


def test_battle_master_level_three_persists_superiority_pool_and_maneuver_choices(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
) -> None:
    fighter = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="战士",
        level=2,
        experience=900,
        suffix="战斗大师卓越骰",
    )
    path = _preview_path(matrix_campaign["id"], fighter["id"])
    request = {
        "character_version": fighter["version"],
        "class_name": "战士",
        "subclass_name": "战斗大师",
        "subclass_feature_choices": {
            "4955e27f4cfda13483c0d1fd:3:1": ["伏击", "领导风范", "战术预估"],
            "4955e27f4cfda13483c0d1fd:3:2": ["skill:洞悉", "tool:铁匠工具"],
            "4955e27f4cfda13483c0d1fd:3:1:dc_ability": ["strength"],
        },
    }
    preview = matrix_client.post(path, json=request)
    assert preview.status_code == 200, preview.text
    bad_request = {
        **request,
        "subclass_feature_choices": {
            **request["subclass_feature_choices"],
            "4955e27f4cfda13483c0d1fd:3:1": ["伏击", "伏击", "战术预估"],
        },
    }
    rejected = matrix_client.post(path, json=bad_request)
    assert rejected.status_code == 400
    assert "不能重复选择" in rejected.text
    after = preview.json()["after"]
    pool = after["resources"]["superiority_dice"]
    assert (pool["max"], pool["current"], pool["value"], pool["die_size"]) == (
        4,
        4,
        "d8",
        8,
    )
    battle_master_grant = next(
        item
        for item in after["features"]
        if item.get("feature_id") == "4955e27f4cfda13483c0d1fd:3:1"
    )
    registry = battle_master_grant["runtime"]["registry"]
    assert registry["selected_maneuvers"] == [
        "ambush",
        "commanding_presence",
        "tactical_assessment",
    ]
    confirm = matrix_client.post(
        path.replace("/advancement/preview", "/advancement/confirm"),
        json={
            **request,
            "preview_token": preview.json()["preview_token"],
            "idempotency_key": "battle-master-superiority-dice-0001",
        },
    )
    assert confirm.status_code == 200, confirm.text
    persisted = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{fighter['id']}"
    ).json()
    assert persisted["resources"]["superiority_dice"]["value"] == "d8"
    assert persisted["resources"]["superiority_dice"]["current"] == 4


def test_asi_is_an_atomic_sheet_grant_and_preview_exposes_runtime_registry(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
) -> None:
    fighter = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="战士",
        level=3,
        experience=2700,
        suffix="属性提升运行时",
    )
    path = _preview_path(matrix_campaign["id"], fighter["id"])

    incomplete = matrix_client.post(
        path,
        json={
            "character_version": fighter["version"],
            "class_name": "战士",
            "ability_increases": {"strength": 1},
        },
    )
    assert incomplete.status_code == 400
    assert "exactly 2" in incomplete.text

    preview_response = matrix_client.post(
        path,
        json={
            "character_version": fighter["version"],
            "class_name": "战士",
            "ability_increases": {"strength": 2},
            "feature_choices_by_key": {"weapon_mastery": ["长剑"]},
        },
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["after"]["ability_scores"]["strength"] == 16
    asi = next(
        item for item in preview["features_gained"] if item.get("kind") == "ability_score_increase"
    )
    assert asi["runtime"]["automation_status"] == "full"
    assert asi["runtime"]["execution"]["delta"] == {"strength": 2}
    assert preview["runtime_registry"]["progression"]["proficiency_bonus"] == 2
    assert preview["after"]["feature_runtime"] == preview["runtime_registry"]

    confirmed_response = matrix_client.post(
        path.replace("/preview", "/confirm"),
        json={
            "character_version": fighter["version"],
            "class_name": "战士",
            "ability_increases": {"strength": 2},
            "feature_choices_by_key": {"weapon_mastery": ["长剑"]},
            "preview_token": preview["preview_token"],
            "idempotency_key": "asi-runtime-registry-0001",
        },
    )
    assert confirmed_response.status_code == 200, confirmed_response.text
    persisted = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{fighter['id']}"
    ).json()
    assert persisted["ability_scores"]["strength"] == 16
    assert any(
        isinstance(item, dict)
        and item.get("kind") == "weapon_mastery"
        and item.get("name") == "长剑"
        for item in persisted["proficiencies"]
    )
    assert any(
        item.get("kind") == "ability_score_increase"
        for item in persisted["features"]
        if isinstance(item, dict)
    )


def test_sorcerer_metamagic_acquisition_and_level_replacement_are_transactional(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
) -> None:
    sorcerer_cantrips = [
        item
        for item in character_options["spells"]
        if item["level"] == 0 and "术士" in item["classes"]
    ][:4]
    sorcerer_spells = [
        item
        for item in character_options["spells"]
        if item["level"] == 1 and "术士" in item["classes"]
    ][:6]
    sorcerer = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="术士",
        level=1,
        experience=900,
        suffix="超魔法资产",
        spells=[
            *[
                {**item, "spell_level": 0, "class_name": "术士", "prepared": True}
                for item in sorcerer_cantrips
            ],
            *[
                {**item, "spell_level": 1, "class_name": "术士", "prepared": True}
                for item in sorcerer_spells[:4]
            ],
        ],
    )
    path = _preview_path(matrix_campaign["id"], sorcerer["id"])
    request = {
        "character_version": sorcerer["version"],
        "class_name": "术士",
        "feature_choices_by_key": {
            "metamagic_options": ["谨慎法术", "远程法术"],
        },
    }
    preview = matrix_client.post(path, json=request)
    assert preview.status_code == 200, preview.text
    confirm = matrix_client.post(
        path.replace("/preview", "/confirm"),
        json={
            **request,
            "preview_token": preview.json()["preview_token"],
            "idempotency_key": "metamagic-level-two-0001",
        },
    )
    assert confirm.status_code == 200, confirm.text
    level_two = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{sorcerer['id']}"
    ).json()
    options = [
        item
        for item in level_two["features"]
        if isinstance(item, dict) and item.get("kind") == "metamagic_option"
    ]
    assert {item["asset_id"] for item in options} == {
        "metamagic:careful-spell",
        "metamagic:distant-spell",
    }

    replacement_request = {
        "character_version": level_two["version"],
        "class_name": "术士",
        "subclass_name": "狂野术法",
        "feature_choices_by_key": {
            "metamagic_replacement": ["谨慎法术->强效法术"],
        },
        "spell_additions": [
            {**item, "spell_level": 1, "class_name": "术士", "prepared": True}
            for item in sorcerer_spells[4:6]
        ],
    }
    replacement_preview = matrix_client.post(path, json=replacement_request)
    assert replacement_preview.status_code == 200, replacement_preview.text
    replacement_confirm = matrix_client.post(
        path.replace("/preview", "/confirm"),
        json={
            **replacement_request,
            "preview_token": replacement_preview.json()["preview_token"],
            "idempotency_key": "metamagic-level-three-replace-0001",
        },
    )
    assert replacement_confirm.status_code == 200, replacement_confirm.text
    persisted = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{sorcerer['id']}"
    ).json()
    assert {
        item["asset_id"]
        for item in persisted["features"]
        if isinstance(item, dict) and item.get("kind") == "metamagic_option"
    } == {"metamagic:distant-spell", "metamagic:empowered-spell"}


def test_paladin_style_cantrip_replacement_updates_sheet_and_known_spell_assets(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
) -> None:
    catalog = {item["name"]: item for item in character_options["spells"]}
    old_spell = catalog["圣火术"]
    paladin_spells = [
        item
        for item in character_options["spells"]
        if item["level"] == 1 and "圣武士" in item["classes"]
    ][:4]
    subclass = "复仇之誓"
    paladin = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="圣武士",
        level=2,
        experience=900,
        suffix="战斗风格戏法替换",
        spells=[
            *[
                {
                    **old_spell,
                    "spell_level": 0,
                    "class_name": "圣武士",
                    "prepared": True,
                    "always_prepared": True,
                    "spellcasting_ability": "charisma",
                    "source_feature_id": "blessed_warrior_cantrips",
                    "granted_spell_access": True,
                }
            ],
            *[
                {
                    **item,
                    "spell_level": 1,
                    "class_name": "圣武士",
                    "prepared": True,
                }
                for item in paladin_spells
            ],
        ],
    )
    path = _preview_path(matrix_campaign["id"], paladin["id"])
    request = {
        "character_version": paladin["version"],
        "class_name": "圣武士",
        "subclass_name": subclass,
        "feature_choices_by_key": {
            "blessed_warrior_cantrip_replacement": ["圣火术->神导术"],
        },
    }
    preview = matrix_client.post(path, json=request)
    assert preview.status_code == 200, preview.text
    confirm = matrix_client.post(
        path.replace("/preview", "/confirm"),
        json={
            **request,
            "preview_token": preview.json()["preview_token"],
            "idempotency_key": "blessed-warrior-cantrip-replace-0001",
        },
    )
    assert confirm.status_code == 200, confirm.text
    persisted = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{paladin['id']}"
    ).json()
    source_spells = [
        item
        for item in persisted["spells"]
        if isinstance(item, dict) and item.get("source_feature_id") == "blessed_warrior_cantrips"
    ]
    assert [item["name"] for item in source_spells] == ["神导术"]
    assets = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{paladin['id']}/assets"
    )
    assert assets.status_code == 200, assets.text
    known = [item for item in assets.json()["spells"] if item["name"] == "神导术"]
    assert len(known) == 1
    assert known[0]["prepared"] is True
    assert known[0]["metadata_json"]["source_feature_id"] == "blessed_warrior_cantrips"


@pytest.mark.parametrize(
    ("class_name", "subclass_marker", "feature_marker", "expected_proficiencies"),
    [
        ("游荡者", "刺客", "刺客工具", ("易容工具", "毒药工具")),
        ("武僧", "命流武者", "操命本事", ("洞悉", "医药", "草药工具")),
    ],
)
def test_fixed_subclass_proficiencies_persist_through_level_up(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
    class_name: str,
    subclass_marker: str,
    feature_marker: str,
    expected_proficiencies: tuple[str, ...],
) -> None:
    assassin = next(
        item["name"]
        for item in _class_option(character_options, class_name)["subclasses"]
        if subclass_marker in item["name"]
    )
    rogue = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name=class_name,
        level=3,
        experience=2_700,
        suffix=f"{subclass_marker}固定熟练真实授予",
        subclass_name=assassin,
    )
    path = _preview_path(matrix_campaign["id"], rogue["id"])
    response = matrix_client.post(
        path,
        json={
            "character_version": rogue["version"],
            "class_name": class_name,
            "ability_increases": {"dexterity": 2},
        },
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    for proficiency in expected_proficiencies:
        assert proficiency in preview["after"]["proficiencies"]
    grant = next(
        item
        for item in preview["features_gained"]
        if item.get("name", "").startswith(feature_marker)
    )
    assert grant["runtime"]["automation_status"] == "full"

    confirmed = matrix_client.post(
        path.replace("/preview", "/confirm"),
        json={
            "character_version": rogue["version"],
            "class_name": class_name,
            "ability_increases": {"dexterity": 2},
            "preview_token": preview["preview_token"],
            "idempotency_key": f"{subclass_marker}-fixed-proficiency-0001",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    persisted = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{rogue['id']}"
    ).json()
    for proficiency in expected_proficiencies:
        assert proficiency in persisted["proficiencies"]


def test_typed_expertise_choice_persists_and_changes_real_skill_modifier(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
) -> None:
    subclass = _class_option(character_options, "游侠")["subclasses"][0]["name"]
    ranger = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="游侠",
        level=8,
        experience=48_000,
        suffix="专精真实消费",
        subclass_name=subclass,
    )
    patched = matrix_client.patch(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{ranger['id']}",
        headers={"If-Match": str(ranger["version"])},
        json={
            "skills": {
                "调查": {"proficient": True},
                "察觉": {"proficient": True},
            }
        },
    )
    assert patched.status_code == 200, patched.text
    ranger = patched.json()
    request = {
        "character_version": ranger["version"],
        "class_name": "游侠",
        "feature_choices_by_key": {"expertise": ["调查", "察觉"]},
        "dm_override_reason": "此回归只隔离专精授予，法术选择由DM覆盖",
    }
    path = _preview_path(matrix_campaign["id"], ranger["id"])
    preview_response = matrix_client.post(path, json=request)
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["progression_choices"] == {"expertise": ["调查", "察觉"]}
    assert preview["after"]["skills"]["调查"]["expertise"] is True
    assert preview["after"]["skills"]["察觉"]["expertise"] is True

    confirmed = matrix_client.post(
        path.replace("/preview", "/confirm"),
        json={
            **request,
            "preview_token": preview["preview_token"],
            "idempotency_key": "typed-expertise-persistence-0001",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    persisted = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{ranger['id']}"
    ).json()
    assert persisted["skills"]["调查"]["expertise"] is True
    modifier, reasons = skill_modifier(type("Sheet", (), persisted), "调查", "intelligence")
    assert modifier == 10  # INT +2 and level-9 expertise +8
    assert "专精 +8" in reasons


def test_subclass_fixed_spell_table_is_persisted_as_always_prepared(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
) -> None:
    paladin = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="圣武士",
        level=2,
        experience=900,
        suffix="誓言法术自动授予",
    )
    request = {
        "character_version": paladin["version"],
        "class_name": "圣武士",
        "subclass_name": "荣耀之誓",
        "dm_override_reason": "回归仅验证固定誓言法术表的自动准备，不覆盖法术目录规则",
    }
    preview = matrix_client.post(
        _preview_path(matrix_campaign["id"], paladin["id"]),
        json=request,
    )
    assert preview.status_code == 200, preview.text
    spells = preview.json()["after"]["spells"]
    by_name = {str(item.get("name")): item for item in spells}
    assert by_name["光导箭"]["always_prepared"] is True
    assert by_name["英雄气概"]["always_prepared"] is True


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
        json={
            **base,
            "subclass_name": subclass_name,
            "dm_override_reason": "子职矩阵夹具未构造完整法术状态",
        },
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["subclass_name"] == subclass_name
    requirement = next(
        item for item in valid.json()["choice_requirements"] if item["key"] == "subclass"
    )
    assert requirement["minimum"] == requirement["maximum"] == 1


def test_multiclass_preview_requires_the_campaign_extension(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
) -> None:
    character = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="战士",
        level=1,
        experience=300,
        suffix="未启用兼职",
    )
    path = _preview_path(matrix_campaign["id"], character["id"])
    blocked = matrix_client.post(
        path,
        json={"character_version": character["version"], "class_name": "法师"},
    )
    assert blocked.status_code == 400
    assert "未启用兼职" in blocked.text

    enabled_campaign = matrix_client.post(
        "/api/v1/campaigns",
        json={"name": "启用兼职", "enabled_rule_extensions": ["multiclassing"]},
    ).json()
    enabled_character = _create_character(
        matrix_client,
        enabled_campaign["id"],
        class_name="战士",
        level=1,
        experience=300,
        suffix="启用兼职",
    )
    allowed = matrix_client.post(
        _preview_path(enabled_campaign["id"], enabled_character["id"]),
        json={
            "character_version": enabled_character["version"],
            "class_name": "法师",
            "dm_override_reason": "兼职矩阵夹具未构造新职业1级法术状态",
        },
    )
    assert allowed.status_code == 200, allowed.text


def test_multiclass_upgrade_rebuilds_resources_for_every_owned_class(
    matrix_client: TestClient,
) -> None:
    campaign = matrix_client.post(
        "/api/v1/campaigns",
        json={
            "name": "兼职资源联动",
            "enabled_rule_extensions": ["multiclassing"],
        },
    ).json()
    character = _create_character(
        matrix_client,
        campaign["id"],
        class_name="战士",
        level=2,
        experience=900,
        suffix="跨职业资源",
        class_levels={"战士": 1, "法师": 1},
    )
    current = matrix_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    response = matrix_client.post(
        _preview_path(campaign["id"], character["id"]),
        json={
            "character_version": current["version"],
            "class_name": "法师",
            "dm_override_reason": "验证升级时回填另一职业资源",
        },
    )
    assert response.status_code == 200, response.text
    resources = response.json()["after"]["resources"]
    assert resources["second_wind"]["max"] >= 1
    assert resources["arcane_recovery"]["max"] == 1
    assert resources["spell_slots_1"]["max"] == 3
    runtime = response.json()["runtime_registry"]
    assert runtime["progression"]["class_levels"] == {"战士": 1, "法师": 2}
    assert runtime["progression"]["spell_slots"]["spell_slots_1"]["max"] == 3


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
        json={
            **base,
            "ability_increases": {"strength": 2},
            **(
                {"feature_choices_by_key": {"weapon_mastery": ["长剑"]}}
                if class_name in {"野蛮人", "战士"}
                else {}
            ),
            "feature_choices": [
                f"测试职业选项{index + 1}"
                for index in range(
                    sum(
                        item["minimum"]
                        for item in _class_option(character_options, class_name)["levels"][3][
                            "choice_requirements"
                        ]
                        if item["kind"] == "feature_option"
                    )
                )
            ],
        },
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["after"]["ability_scores"]["strength"] == 16


def test_strict_caster_state_feat_prerequisite_and_dm_character_consistency(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
) -> None:
    caster = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="吟游诗人",
        level=1,
        experience=300,
        suffix="缺失法术",
    )
    strict = matrix_client.post(
        _preview_path(matrix_campaign["id"], caster["id"]),
        json={"character_version": caster["version"], "class_name": "吟游诗人"},
    )
    assert strict.status_code == 400
    assert "戏法" in strict.text

    rogue_subclass = _class_option(character_options, "游荡者")["subclasses"][0]["name"]
    rogue = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="游荡者",
        level=3,
        experience=2_700,
        suffix="专长前置",
        subclass_name=rogue_subclass,
    )
    lowered_scores = {**_abilities(), "charisma": 8}
    lowered = matrix_client.patch(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{rogue['id']}",
        headers={"If-Match": str(rogue["version"])},
        json={"ability_scores": lowered_scores},
    )
    assert lowered.status_code == 200, lowered.text
    rogue = lowered.json()
    feat_path = _preview_path(matrix_campaign["id"], rogue["id"])
    blocked_feat = matrix_client.post(
        feat_path,
        json={
            "character_version": rogue["version"],
            "class_name": "游荡者",
            "feat_choice": "演员Actor",
        },
    )
    assert blocked_feat.status_code == 400
    assert "魅力13+" in blocked_feat.text

    hp_growth = matrix_client.post(
        feat_path,
        json={
            "character_version": rogue["version"],
            "class_name": "游荡者",
            "ability_increases": {"constitution": 2},
        },
    )
    assert hp_growth.status_code == 200, hp_growth.text
    assert hp_growth.json()["constitution_hp_adjustment"] == 4
    assert hp_growth.json()["hp_gain"] == 11

    invalid_create = matrix_client.post(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters",
        json={
            "name": "非法等级",
            "class_name": "战士",
            "level": 5,
            "class_levels": {"战士": 4},
        },
    )
    assert invalid_create.status_code == 400


def test_wizard_spell_matrix_rejects_wrong_class_ring_count_and_preparation(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
) -> None:
    spells = character_options["spells"]
    wizard_cantrips = [item for item in spells if item["level"] == 0 and "法师" in item["classes"]][
        :3
    ]
    wizard_level_one = [
        item for item in spells if item["level"] == 1 and "法师" in item["classes"]
    ][:8]
    wrong_class = next(
        item for item in spells if item["level"] == 1 and "法师" not in item["classes"]
    )
    too_high = next(item for item in spells if item["level"] == 2 and "法师" in item["classes"])
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
    assert replay.json()["advancement_record_id"] == first.json()["advancement_record_id"]

    updated = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{character['id']}"
    ).json()
    history = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{character['id']}/advancement"
    ).json()
    assert updated["level"] == 2
    assert len(history["items"]) == 1


def test_epic_boon_grant_is_authoritative_and_selected_feat_stays_separate(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
) -> None:
    boon = next(item for item in character_options["feats"] if item["category"] == "传奇恩惠")
    character = _create_character(
        matrix_client,
        matrix_campaign["id"],
        class_name="战士",
        level=18,
        experience=999_999,
        suffix="传奇恩惠授予",
    )
    body = {
        "character_version": character["version"],
        "class_name": "战士",
        "feat_choice": boon["name"],
    }
    path = _preview_path(matrix_campaign["id"], character["id"])

    missing = matrix_client.post(
        path,
        json={
            "character_version": character["version"],
            "class_name": "战士",
        },
    )
    assert missing.status_code == 400
    assert "feat choice" in missing.text

    preview_response = matrix_client.post(path, json=body)
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    class_grant = next(
        item
        for item in preview["features_gained"]
        if item.get("kind") == "class_feature" and "传奇恩惠" in item.get("name", "")
    )
    selected_feat = preview["feat_grant"]
    assert selected_feat["kind"] == "feat"
    assert selected_feat["name"] == boon["name"]
    assert class_grant["runtime"]["automation_status"] == "full"
    assert class_grant["runtime"]["registry"]["advancement"]["request_field"] == ("feat_choice")
    assert selected_feat["runtime"]["automation_status"] == "dm_only"
    assert selected_feat["runtime"]["execution"] == {
        "kind": "sheet_feat_grant",
        "grant_status": "full",
        "effect_status": "dm_only",
    }

    confirm_body = {
        **body,
        "preview_token": preview["preview_token"],
        "idempotency_key": "epic-boon-authoritative-grant-0001",
    }
    confirm_path = path.replace("/preview", "/confirm")
    first = matrix_client.post(confirm_path, json=confirm_body)
    replay = matrix_client.post(confirm_path, json=confirm_body)
    assert first.status_code == replay.status_code == 200
    assert replay.json()["advancement_record_id"] == first.json()["advancement_record_id"]
    persisted = matrix_client.get(
        f"/api/v1/campaigns/{matrix_campaign['id']}/characters/{character['id']}"
    ).json()
    assert persisted["level"] == 19
    assert (
        sum(
            isinstance(item, dict)
            and item.get("kind") == "feat"
            and item.get("name") == boon["name"]
            for item in persisted["features"]
        )
        == 1
    )


def test_fighting_style_grant_replacement_and_champion_additional_style_are_assets(
    matrix_client: TestClient,
    matrix_campaign: dict[str, Any],
    character_options: dict[str, Any],
) -> None:
    styles = [item for item in character_options["feats"] if item.get("category") == "战斗风格"]
    assert len(styles) >= 3
    campaign = matrix_client.post(
        "/api/v1/campaigns",
        json={"name": "战斗风格资产", "enabled_rule_extensions": ["multiclassing"]},
    ).json()
    character = _create_character(
        matrix_client,
        campaign["id"],
        class_name="吟游诗人",
        level=1,
        experience=10_000,
        suffix="战斗风格资产",
    )
    path = _preview_path(campaign["id"], character["id"])
    first_body = {
        "character_version": character["version"],
        "class_name": "战士",
        "feature_choices_by_key": {
            "fighting_style": [styles[0]["name"]],
            "weapon_mastery": ["长剑", "战锤", "长弓"],
        },
    }
    first_preview = matrix_client.post(path, json=first_body)
    assert first_preview.status_code == 200, first_preview.text
    selected = next(
        item
        for item in first_preview.json()["after"]["features"]
        if item.get("kind") == "feat" and item.get("name") == styles[0]["name"]
    )
    assert selected["runtime"]["execution"]["grant_status"] == "full"
    first = matrix_client.post(
        path.replace("/preview", "/confirm"),
        json={
            **first_body,
            "preview_token": first_preview.json()["preview_token"],
            "idempotency_key": "fighter-style-initial-0001",
        },
    )
    assert first.status_code == 200, first.text
    character = matrix_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    replacement_body = {
        "character_version": character["version"],
        "class_name": "战士",
        "feature_choices_by_key": {
            "fighting_style_replacement": [f"{styles[0]['name']}->{styles[1]['name']}"]
        },
    }
    replacement_preview = matrix_client.post(path, json=replacement_body)
    assert replacement_preview.status_code == 200, replacement_preview.text
    feature_names = {
        item.get("name")
        for item in replacement_preview.json()["after"]["features"]
        if isinstance(item, dict) and item.get("kind") == "feat"
    }
    assert styles[0]["name"] not in feature_names
    assert styles[1]["name"] in feature_names

    champion = next(
        item
        for item in _class_option(character_options, "战士")["subclasses"]
        if item["name"] == "勇士"
    )
    champion_character = _create_character(
        matrix_client,
        campaign["id"],
        class_name="战士",
        level=6,
        experience=99_999,
        suffix="冠军额外风格",
        subclass_name=champion["name"],
    )
    champion_path = _preview_path(campaign["id"], champion_character["id"])
    discovery = matrix_client.post(
        champion_path,
        json={
            "character_version": champion_character["version"],
            "class_name": "战士",
            "dm_override_reason": "只读取服务端生成的结构化子职 requirement id",
        },
    )
    assert discovery.status_code == 200, discovery.text
    requirement = next(
        item
        for item in discovery.json()["choice_requirements"]
        if item.get("key") == "additional_fighting_style"
    )
    champion_body = {
        "character_version": champion_character["version"],
        "class_name": "战士",
        "subclass_feature_choices": {requirement["feature_id"]: [styles[2]["name"]]},
    }
    champion_preview = matrix_client.post(champion_path, json=champion_body)
    assert champion_preview.status_code == 200, champion_preview.text
    assert any(
        item.get("kind") == "feat" and item.get("name") == styles[2]["name"]
        for item in champion_preview.json()["after"]["features"]
    )


def test_deft_explorer_and_primal_order_persist_real_sheet_assets(
    matrix_client: TestClient,
    character_options: dict[str, Any],
) -> None:
    campaign = matrix_client.post(
        "/api/v1/campaigns",
        json={"name": "成长选项资产", "enabled_rule_extensions": ["multiclassing"]},
    ).json()
    style = next(
        item["name"] for item in character_options["feats"] if item.get("category") == "战斗风格"
    )
    ranger = _create_character(
        matrix_client,
        campaign["id"],
        class_name="游侠",
        level=1,
        experience=10_000,
        suffix="熟练探险家",
        skills={"察觉": {"proficient": True}},
    )
    ranger_path = _preview_path(campaign["id"], ranger["id"])
    ranger_body = {
        "character_version": ranger["version"],
        "class_name": "游侠",
        "feature_choices_by_key": {
            "fighting_style": [style],
            "deft_explorer_expertise": ["察觉"],
            "deft_explorer_languages": ["精灵语", "矮人语"],
        },
        "dm_override_reason": "夹具不重复构造游侠一级已有准备法术，仅复核本级成长资产",
    }
    ranger_preview = matrix_client.post(ranger_path, json=ranger_body)
    assert ranger_preview.status_code == 200, ranger_preview.text
    ranger_after = ranger_preview.json()["after"]
    assert ranger_after["skills"]["察觉"]["expertise"] is True
    assert {"语言：精灵语", "语言：矮人语"} <= set(ranger_after["proficiencies"])
    ranger_sheet = {
        **ranger_after,
        "level": 2,
        "ability_scores": _abilities(),
    }
    assert skill_modifier(type("Sheet", (), ranger_sheet), "察觉", "wisdom")[0] == 6
    confirmed = matrix_client.post(
        ranger_path.replace("/preview", "/confirm"),
        json={
            **ranger_body,
            "preview_token": ranger_preview.json()["preview_token"],
            "idempotency_key": "deft-explorer-assets-0001",
        },
    )
    assert confirmed.status_code == 200, confirmed.text

    druid = _create_character(
        matrix_client,
        campaign["id"],
        class_name="吟游诗人",
        level=1,
        experience=10_000,
        suffix="原初职能",
    )
    druid_path = _preview_path(campaign["id"], druid["id"])
    druid_body = {
        "character_version": druid["version"],
        "class_name": "德鲁伊",
        "feature_choices_by_key": {"primal_order": ["warden"]},
        "dm_override_reason": "夹具不重复构造德鲁伊一级完整准备法术，仅复核守卫分支",
    }
    druid_preview = matrix_client.post(druid_path, json=druid_body)
    assert druid_preview.status_code == 200, druid_preview.text
    assert {"军用武器", "中甲"} <= set(druid_preview.json()["after"]["proficiencies"])
