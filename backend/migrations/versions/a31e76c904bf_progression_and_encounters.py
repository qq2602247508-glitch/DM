"""add progression and encounter fields

Revision ID: a31e76c904bf
Revises: f42d8b1c907e
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a31e76c904bf"
down_revision: str | None = "f42d8b1c907e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("characters") as batch_op:
        batch_op.add_column(
            sa.Column("experience", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.create_check_constraint("ck_character_experience", "experience >= 0")

    with op.batch_alter_table("quests") as batch_op:
        batch_op.add_column(
            sa.Column("xp_reward", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("xp_awarded", sa.Boolean(), server_default="0", nullable=False)
        )

    with op.batch_alter_table("combats") as batch_op:
        batch_op.add_column(sa.Column("difficulty", sa.String(length=30), nullable=True))
        batch_op.add_column(
            sa.Column("base_xp", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("difficulty_adjustments", sa.JSON(), server_default="[]", nullable=False)
        )
        batch_op.add_column(
            sa.Column("xp_awarded", sa.Boolean(), server_default="0", nullable=False)
        )
        batch_op.create_check_constraint("ck_combat_base_xp", "base_xp >= 0")


def downgrade() -> None:
    with op.batch_alter_table("combats") as batch_op:
        batch_op.drop_constraint("ck_combat_base_xp", type_="check")
        batch_op.drop_column("xp_awarded")
        batch_op.drop_column("difficulty_adjustments")
        batch_op.drop_column("base_xp")
        batch_op.drop_column("difficulty")

    with op.batch_alter_table("quests") as batch_op:
        batch_op.drop_column("xp_awarded")
        batch_op.drop_column("xp_reward")

    with op.batch_alter_table("characters") as batch_op:
        batch_op.drop_constraint("ck_character_experience", type_="check")
        batch_op.drop_column("experience")
