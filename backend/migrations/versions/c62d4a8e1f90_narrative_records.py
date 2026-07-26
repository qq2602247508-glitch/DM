"""add narrative records

Revision ID: c62d4a8e1f90
Revises: 9a1e2d3c4b5a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c62d4a8e1f90"
down_revision: str | None = "9a1e2d3c4b5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
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
    ]


def upgrade() -> None:
    op.create_table(
        "story_beats",
        *_timestamps(),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(30), server_default="planned", nullable=False),
        sa.Column("prerequisites", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("branches", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "quest_objectives",
        *_timestamps(),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("quest_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("objective_type", sa.String(40), server_default="custom", nullable=False),
        sa.Column("status", sa.String(30), server_default="active", nullable=False),
        sa.Column("hidden", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("details", sa.JSON(), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quest_id"], ["quests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "npc_memories",
        *_timestamps(),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("npc_id", sa.String(36), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("memory_kind", sa.String(30), server_default="witnessed", nullable=False),
        sa.Column("attitude_delta", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tags", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("secret", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["npc_id"], ["npcs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "faction_reputations",
        *_timestamps(),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("character_id", sa.String(36), nullable=False),
        sa.Column("faction_name", sa.String(200), nullable=False),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notes", sa.Text()),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id", "character_id", "faction_name", name="uq_faction_reputation"
        ),
    )
    op.create_table(
        "clue_discoveries",
        *_timestamps(),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("clue_id", sa.String(36), nullable=False),
        sa.Column("discoverer_character_id", sa.String(36)),
        sa.Column("method", sa.String(100), server_default="other", nullable=False),
        sa.Column("scene_id", sa.String(36)),
        sa.Column("notes", sa.Text()),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["clue_id"], ["clues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["discoverer_character_id"], ["characters.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "downtime_activities",
        *_timestamps(),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("character_id", sa.String(36), nullable=False),
        sa.Column("activity_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), server_default="planned", nullable=False),
        sa.Column("duration_days", sa.Integer(), server_default="1", nullable=False),
        sa.Column("progress_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("daily_cost_cp", sa.Integer(), server_default="0", nullable=False),
        sa.Column("details", sa.JSON(), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    for table in (
        "downtime_activities",
        "clue_discoveries",
        "faction_reputations",
        "npc_memories",
        "quest_objectives",
        "story_beats",
    ):
        op.drop_table(table)
