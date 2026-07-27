"""add LAN player rooms and sessions

Revision ID: a4c7e2f91b30
Revises: f2b3c4d5e6a7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4c7e2f91b30"
down_revision: str | None = "f2b3c4d5e6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamp() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "player_rooms",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("current_scene_id", sa.String(36)),
        sa.Column("current_combat_id", sa.String(36)),
        sa.Column("join_code_salt", sa.String(32), nullable=False),
        sa.Column("join_code_hash", sa.String(64), nullable=False),
        sa.Column("join_code_hint", sa.String(2), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("allow_character_creation", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *_stamp(),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_scene_id"], ["scenes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["current_combat_id"], ["combats.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('active','closed')", name="ck_player_room_status"),
        sa.UniqueConstraint("campaign_id", name="uq_player_room_campaign"),
    )
    op.create_index(
        "ix_player_rooms_status_expires", "player_rooms", ["status", "expires_at", "id"]
    )
    op.create_table(
        "player_sessions",
        sa.Column("room_id", sa.String(36), nullable=False),
        sa.Column("character_id", sa.String(36)),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        *_stamp(),
        sa.ForeignKeyConstraint(["room_id"], ["player_rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="SET NULL"),
        sa.CheckConstraint("length(trim(display_name)) > 0", name="ck_player_session_name"),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_player_session_status"),
        sa.UniqueConstraint("token_hash", name="uq_player_session_token_hash"),
    )
    op.create_index(
        "ix_player_sessions_room_status",
        "player_sessions",
        ["room_id", "status", "created_at", "id"],
    )
    op.create_index(
        "ix_player_sessions_character_status", "player_sessions", ["character_id", "status", "id"]
    )
    op.create_index(
        "uq_player_sessions_active_character",
        "player_sessions",
        ["room_id", "character_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active' AND character_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_player_sessions_active_character", table_name="player_sessions")
    op.drop_index("ix_player_sessions_character_status", table_name="player_sessions")
    op.drop_index("ix_player_sessions_room_status", table_name="player_sessions")
    op.drop_table("player_sessions")
    op.drop_index("ix_player_rooms_status_expires", table_name="player_rooms")
    op.drop_table("player_rooms")
