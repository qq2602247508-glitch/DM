"""link combats to persistent scenes

Revision ID: e91c53a72b10
Revises: d82b7a91e450
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e91c53a72b10"
down_revision: str | None = "d82b7a91e450"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("combats") as batch_op:
        batch_op.add_column(sa.Column("scene_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_combats_scene_id_scenes",
            "scenes",
            ["scene_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_combats_scene_id", ["scene_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("combats") as batch_op:
        batch_op.drop_index("ix_combats_scene_id")
        batch_op.drop_constraint("fk_combats_scene_id_scenes", type_="foreignkey")
        batch_op.drop_column("scene_id")
