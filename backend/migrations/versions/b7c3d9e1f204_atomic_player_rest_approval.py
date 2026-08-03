"""make pending player rest requests unique per character

Revision ID: b7c3d9e1f204
Revises: a6f2c8d91e30
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision: str = "b7c3d9e1f204"
down_revision: str | None = "a6f2c8d91e30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_player_pending_rest_per_character",
        "player_action_requests",
        ["campaign_id", "character_id"],
        unique=True,
        sqlite_where=text("action_type = 'rest_request' AND status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_player_pending_rest_per_character",
        table_name="player_action_requests",
    )
