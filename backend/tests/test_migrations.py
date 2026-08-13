from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_alembic_upgrades_empty_database(tmp_path: Path, monkeypatch: Any) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)

    config = Config("backend/alembic.ini")
    command.upgrade(config, "head")

    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {
        "alembic_version",
        "system_metadata",
        "campaigns",
        "characters",
        "character_conditions",
        "npcs",
        "locations",
        "location_connections",
        "quests",
        "clues",
        "events",
        "combats",
        "combatants",
        "audit_log",
        "state_change_proposals",
        "model_runs",
        "operation_transactions",
        "encounter_adjustment_proposals",
        "combat_actions",
        "combat_effects",
        "death_saves",
        "combat_reinforcements",
        "combat_settlements",
        "handouts",
        "player_action_requests",
        "region_maps",
        "adventure_sites",
        "site_levels",
        "site_rooms",
        "site_connectors",
        "campaign_session_states",
        "session_checkpoints",
        "vessel_spaces",
        "rules_kernel_adjudications",
    } <= tables

    engine = create_engine(database_url)
    adjudication_columns = {
        column["name"] for column in inspect(engine).get_columns("rules_kernel_adjudications")
    }
    assert {
        "source_record_id",
        "source_fingerprint",
        "source_clause_ids",
        "target_context",
        "effect_envelope",
        "decision_kind",
        "producer_provenance",
    } <= adjudication_columns
    assert inspect(engine).get_pk_constraint("vessel_spaces")["constrained_columns"] == [
        "vessel_id"
    ]
    row = {
        "id": "audit-id-1",
        "vessel_id": "same-vessel",
        "campaign_id": "campaign-1",
        "owner_character_id": "character-1",
        "source_record_id": "source-1",
        "source_fingerprint": "fingerprint-1",
        "status": "outside",
        "state_json": "{}",
        "occupants_json": "[]",
        "items_json": "[]",
        "metadata_json": "{}",
    }
    insert = text(
        "INSERT INTO vessel_spaces "
        "(id, vessel_id, campaign_id, owner_character_id, source_record_id, "
        "source_fingerprint, status, state_json, occupants_json, items_json, metadata_json) "
        "VALUES (:id, :vessel_id, :campaign_id, :owner_character_id, :source_record_id, "
        ":source_fingerprint, :status, :state_json, :occupants_json, :items_json, :metadata_json)"
    )
    with engine.begin() as connection:
        connection.execute(insert, row)
        try:
            connection.execute(insert, {**row, "id": "audit-id-2"})
        except IntegrityError:
            pass
        else:
            raise AssertionError("duplicate vessel_id must violate the database primary key")
