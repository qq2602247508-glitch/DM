"""add explicit campaign rule extensions and rule atoms

Revision ID: c8d1e5f7a902
Revises: b7c3d9e1f204
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8d1e5f7a902"
down_revision: str | None = "b7c3d9e1f204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "enabled_rule_extensions",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
    )
    with op.batch_alter_table("compendium_entries", recreate="always") as batch:
        batch.drop_constraint("ck_compendium_entry_type", type_="check")
        batch.create_check_constraint(
            "ck_compendium_entry_type",
            "entry_type IN "
            "('spell','feature','monster','equipment','item','npc','location','scene','rule')",
        )


def downgrade() -> None:
    with op.batch_alter_table("compendium_entries", recreate="always") as batch:
        batch.drop_constraint("ck_compendium_entry_type", type_="check")
        batch.create_check_constraint(
            "ck_compendium_entry_type",
            "entry_type IN "
            "('spell','feature','monster','equipment','item','npc','location','scene')",
        )
    op.drop_column("campaigns", "enabled_rule_extensions")
