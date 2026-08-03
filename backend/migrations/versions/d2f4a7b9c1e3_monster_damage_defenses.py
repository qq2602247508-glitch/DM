"""store monster damage defenses for combat instantiation

Revision ID: d2f4a7b9c1e3
Revises: c8d1e5f7a902
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f4a7b9c1e3"
down_revision: str | None = "c8d1e5f7a902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in (
        "damage_resistances",
        "damage_vulnerabilities",
        "damage_immunities",
        "condition_immunities",
    ):
        op.add_column(
            "monster_instances",
            sa.Column(name, sa.JSON(), server_default="[]", nullable=False),
        )


def downgrade() -> None:
    for name in (
        "condition_immunities",
        "damage_immunities",
        "damage_vulnerabilities",
        "damage_resistances",
    ):
        op.drop_column("monster_instances", name)
