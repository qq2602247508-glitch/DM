"""add rule-driven character fields

Revision ID: f42d8b1c907e
Revises: e91c53a72b10
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f42d8b1c907e"
down_revision: str | None = "e91c53a72b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("characters") as batch_op:
        batch_op.add_column(sa.Column("background", sa.String(length=100), nullable=True))
        for name, default in (
            ("proficiencies", "[]"),
            ("features", "[]"),
            ("actions", "[]"),
            ("spells", "[]"),
        ):
            batch_op.add_column(sa.Column(name, sa.JSON(), server_default=default, nullable=False))
        for name in ("skills", "resources", "spellcasting"):
            batch_op.add_column(sa.Column(name, sa.JSON(), server_default="{}", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("characters") as batch_op:
        for name in (
            "spellcasting",
            "spells",
            "resources",
            "actions",
            "features",
            "skills",
            "proficiencies",
            "background",
        ):
            batch_op.drop_column(name)
