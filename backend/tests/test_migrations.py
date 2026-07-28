from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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
    } <= tables
