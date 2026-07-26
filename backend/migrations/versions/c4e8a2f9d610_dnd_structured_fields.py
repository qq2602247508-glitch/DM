"""add structured D&D campaign fields

Revision ID: c4e8a2f9d610
Revises: 7f3a1c9d2e40
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a2f9d610"
down_revision: str | None = "7f3a1c9d2e40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("characters") as batch_op:
        batch_op.add_column(sa.Column("race", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column("armor_class", sa.Integer(), server_default="10", nullable=False)
        )
        batch_op.add_column(sa.Column("speed", sa.Integer(), server_default="30", nullable=False))
        batch_op.add_column(
            sa.Column("ability_scores", sa.JSON(), server_default="{}", nullable=False)
        )
        batch_op.add_column(
            sa.Column("equipment", sa.JSON(), server_default="[]", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_character_ac", "armor_class >= 0 AND armor_class <= 99"
        )
        batch_op.create_check_constraint(
            "ck_character_speed", "speed >= 0 AND speed <= 1000"
        )

    with op.batch_alter_table("npcs") as batch_op:
        batch_op.add_column(sa.Column("alignment", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("attitude", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("goal", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("fear", sa.Text(), nullable=True))

    with op.batch_alter_table("quests") as batch_op:
        batch_op.add_column(
            sa.Column("quest_type", sa.String(length=30), server_default="side", nullable=False)
        )
        batch_op.add_column(sa.Column("giver", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("reward", sa.Text(), nullable=True))

    with op.batch_alter_table("clues") as batch_op:
        batch_op.add_column(sa.Column("player_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("dm_truth", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("verified", sa.Boolean(), server_default="0", nullable=False)
        )

    with op.batch_alter_table("combatants") as batch_op:
        batch_op.add_column(
            sa.Column("armor_class", sa.Integer(), server_default="10", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_combatant_ac", "armor_class >= 0 AND armor_class <= 99"
        )


def downgrade() -> None:
    with op.batch_alter_table("combatants") as batch_op:
        batch_op.drop_constraint("ck_combatant_ac", type_="check")
        batch_op.drop_column("armor_class")
    with op.batch_alter_table("clues") as batch_op:
        batch_op.drop_column("verified")
        batch_op.drop_column("dm_truth")
        batch_op.drop_column("player_text")
    with op.batch_alter_table("quests") as batch_op:
        batch_op.drop_column("reward")
        batch_op.drop_column("giver")
        batch_op.drop_column("quest_type")
    with op.batch_alter_table("npcs") as batch_op:
        batch_op.drop_column("fear")
        batch_op.drop_column("goal")
        batch_op.drop_column("attitude")
        batch_op.drop_column("alignment")
    with op.batch_alter_table("characters") as batch_op:
        batch_op.drop_constraint("ck_character_speed", type_="check")
        batch_op.drop_constraint("ck_character_ac", type_="check")
        batch_op.drop_column("equipment")
        batch_op.drop_column("ability_scores")
        batch_op.drop_column("speed")
        batch_op.drop_column("armor_class")
        batch_op.drop_column("race")
