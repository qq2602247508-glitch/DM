"""add player handouts and action requests

Revision ID: fa8b1c2d3e40
Revises: f20d8a4b7c61
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fa8b1c2d3e40"
down_revision: str | None = "f20d8a4b7c61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "handouts",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("published", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("length(trim(title)) > 0", name="ck_handout_title_nonempty"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_handouts_campaign_published",
        "handouts",
        ["campaign_id", "published", "sort_order", "id"],
    )
    op.create_table(
        "player_action_requests",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("character_id", sa.String(36), nullable=False),
        sa.Column("player_key", sa.String(100), nullable=False),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("payload_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("character_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("dm_note", sa.Text()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint("length(trim(action_type)) > 0", name="ck_player_action_type_nonempty"),
        sa.CheckConstraint("character_version >= 1", name="ck_player_action_character_version"),
        sa.CheckConstraint(
            "status IN ('pending','accepted','rejected','stale')", name="ck_player_action_status"
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id", "idempotency_key", name="uq_player_action_campaign_idempotency"
        ),
    )
    op.create_index(
        "ix_player_action_campaign_status",
        "player_action_requests",
        ["campaign_id", "status", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_player_action_campaign_status", table_name="player_action_requests")
    op.drop_table("player_action_requests")
    op.drop_index("ix_handouts_campaign_published", table_name="handouts")
    op.drop_table("handouts")
