"""add optimistic versions to narrative records

Revision ID: f20d8a4b7c61
Revises: f19c7e2a6b40
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f20d8a4b7c61"
down_revision: str | None = "f19c7e2a6b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "story_beats",
    "quest_objectives",
    "npc_memories",
    "faction_reputations",
    "clue_discoveries",
    "downtime_activities",
)


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "version")
