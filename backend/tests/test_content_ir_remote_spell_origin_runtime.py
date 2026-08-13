from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.engine import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import Combatant, OperationTransaction

ROOT = Path(__file__).resolve().parents[2]
COMPILE_RESULT = ROOT / "data/content-ir/compiled/batch-II/compile-result.json"
SOURCE_ID = "fixture:remote-origin-service"
SOURCE_FINGERPRINT = "remote-origin-service-fingerprint"


def _runtime() -> dict[str, Any]:
    result = json.loads(COMPILE_RESULT.read_text(encoding="utf-8"))
    candidates = [
        row["runtime_spell_definition"]
        for row in result["results"]
        if isinstance(row.get("runtime_spell_definition"), dict)
    ]
    runtime = next(
        item
        for item in candidates
        if any(
            isinstance(effect, dict)
            and effect.get("type") == "damage"
            and effect.get("damage_type")
            for effect in item.get("resolution", {}).get("effects", [])
        )
    )
    runtime = copy.deepcopy(runtime)
    runtime["resolution"]["spell_origins"] = [
        {
            "resolution_kind": "remote_spell_origin",
            "origin_contract": {
                "schema": "remote.spell.origin.v1",
                "origin_kind": "entity",
                "origin_binding": "entity_lifecycle",
                "target_kind": "one_creature",
                "max_range_ft": 30,
                "require_line_of_effect": True,
            },
            "source_provenance": {
                "source_record_id": SOURCE_ID,
                "source_fingerprint": SOURCE_FINGERPRINT,
            },
        }
    ]
    return runtime


def _setup(
    client: TestClient,
    *,
    blocked: bool = False,
    origin_position: tuple[int, int] = (1, 1),
    target_position: tuple[int, int] = (1, 5),
) -> dict[str, Any]:
    runtime = _runtime()
    slot_level = int(runtime["level"])
    campaign = client.post("/api/v1/campaigns", json={"name": "Remote origin service"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "远程施法者",
            "hp": 20,
            "max_hp": 20,
            "spellcasting": {
                "slots": {
                    str(level): {"current": 2, "max": 2}
                    for level in range(1, max(9, slot_level) + 1)
                }
            },
        },
    ).json()
    known = client.post(
        f"{base}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": runtime["name"],
            "spell_level": runtime["level"],
            "prepared": True,
            "metadata_json": {"content_ir_runtime": runtime},
        },
    )
    assert known.status_code == 201, known.text
    character = client.get(f"{base}/characters/{character['id']}").json()
    cells = [{"row": 1, "col": 3, "kind": "wall"}] if blocked else []
    scene = client.post(f"{base}/scenes", json={"name": "Origin scene"}).json()
    grid = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={
            "width": 20,
            "height": 20,
            "cell_size_ft": 5,
            "mode": "combat",
            "layers_json": {"cells": cells},
        },
    )
    assert grid.status_code == 201, grid.text
    combat = client.post(
        f"{base}/combats",
        json={"name": "Origin combat", "scene_id": scene["id"]},
    ).json()
    root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "施法者",
            "entity_type": "character",
            "entity_id": character["id"],
            "hp": 20,
            "max_hp": 20,
            "initiative": 20,
            "snapshot_json": {
                "grid_position": {"row": 10, "col": 10},
                "feature_runtime": {
                    "entity_lifecycle": [
                        {
                            "schema": "entity.lifecycle.v1",
                            "entity_type": "remote_origin",
                            "source_id": SOURCE_ID,
                            "source_fingerprint": SOURCE_FINGERPRINT,
                            "status": "entered",
                            "active_entries": 1,
                            "version": 2,
                            "authorized_origin_ids": ["origin"],
                            "metadata": {"owner_id": "OWNER"},
                        }
                    ]
                },
            },
        },
    ).json()
    # The lifecycle owner and authorized origin are bound after both rows exist.
    # This keeps the test fixture honest about actor authorization without
    # adding a new API.
    engine = create_database_engine(client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        row = session.get(Combatant, actor["id"])
        assert row is not None
        snapshot = copy.deepcopy(row.snapshot_json)
    origin = client.post(
        f"{root}/combatants",
        json={
            "display_name": "远程源实体",
            "entity_type": "npc",
            "hp": 10,
            "max_hp": 10,
            "initiative": 15,
            "snapshot_json": {
                "grid_position": {"row": origin_position[0], "col": origin_position[1]}
            },
        },
    ).json()
    target = client.post(
        f"{root}/combatants",
        json={
            "display_name": "目标",
            "entity_type": "monster",
            "hp": 30,
            "max_hp": 30,
            "initiative": 10,
            "snapshot_json": {
                "grid_position": {"row": target_position[0], "col": target_position[1]}
            },
        },
    ).json()
    with Session(engine) as session, session.begin():
        row = session.get(Combatant, actor["id"])
        assert row is not None
        snapshot = copy.deepcopy(row.snapshot_json)
        lifecycle = snapshot["feature_runtime"]["entity_lifecycle"][0]
        lifecycle["metadata"]["owner_id"] = row.id
        lifecycle["authorized_origin_ids"] = [origin["id"]]
        row.snapshot_json = snapshot
    return {
        "base": base,
        "character": character,
        "known": known.json(),
        "combat": combat,
        "actor": actor,
        "origin": origin,
        "target": target,
        "runtime": runtime,
    }


def _body(scene: dict[str, Any], key: str, *, origin_id: str | None = None) -> dict[str, Any]:
    runtime = scene["runtime"]
    return {
        "content_kind": "spell",
        "runtime_id": runtime["spell_id"],
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": runtime["level"],
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": scene["target"]["id"],
        "target_version": scene["target"]["version"],
        "resolution_total": 4,
        "origin_id": origin_id or scene["origin"]["id"],
        "idempotency_key": key,
        "save_succeeded": (
            False if runtime["resolution"].get("saving_throw") else None
        ),
    }


def test_remote_spell_origin_real_service_receipt_preview_confirm_replay(
    campaign_client: TestClient,
) -> None:
    scene = _setup(campaign_client)
    body = _body(scene, "remote-origin-service-001")
    preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview", json=body
    )
    assert preview.status_code == 200, preview.text
    receipt = preview.json()["remote_spell_origin"]
    assert receipt["origin_id"] == scene["origin"]["id"]
    assert receipt["target_ids"] == [scene["target"]["id"]]
    assert receipt["distances_ft"] == {scene["target"]["id"]: 20}
    assert receipt["line_of_effect"] == {scene["target"]["id"]: True}

    confirm_body = {**body, "preview_token": preview.json()["preview_token"]}
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm", json=confirm_body
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["remote_spell_origin"] == receipt
    assert confirmed.json()["production_runtime_full"] is True
    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        operations = session.scalars(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == scene["base"].rsplit("/", 1)[-1],
                OperationTransaction.idempotency_key == "content-ir:remote-origin-service-001",
            )
        ).all()
    assert len(operations) == 1
    assert operations[0].after_snapshot["remote_spell_origin"] == receipt
    replay = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm", json=confirm_body
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True


def test_remote_spell_origin_rejects_stale_actor_before_application(
    campaign_client: TestClient,
) -> None:
    scene = _setup(campaign_client)
    body = _body(scene, "remote-origin-service-stale")
    preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview", json=body
    )
    assert preview.status_code == 200, preview.text
    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        actor = session.get(Combatant, scene["actor"]["id"])
        assert actor is not None
        actor.version += 1
    stale = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert stale.status_code == 409, stale.text


def test_remote_spell_origin_fails_closed_for_unauthorized_origin_range_and_line(
    campaign_client: TestClient,
) -> None:
    unauthorized = _setup(campaign_client)
    response = campaign_client.post(
        f"{unauthorized['base']}/content-ir/runtime/preview",
        json=_body(
            unauthorized,
            "remote-origin-unauthorized",
            origin_id=unauthorized["target"]["id"],
        ),
    )
    assert response.status_code == 400
    assert "authorization" in response.text

    out_of_range = _setup(
        campaign_client, origin_position=(1, 1), target_position=(10, 10)
    )
    response = campaign_client.post(
        f"{out_of_range['base']}/content-ir/runtime/preview",
        json=_body(out_of_range, "remote-origin-range"),
    )
    assert response.status_code == 400
    assert "outside range" in response.text

    blocked = _setup(campaign_client, blocked=True)
    response = campaign_client.post(
        f"{blocked['base']}/content-ir/runtime/preview",
        json=_body(blocked, "remote-origin-line"),
    )
    assert response.status_code == 400
    assert "line of effect" in response.text
