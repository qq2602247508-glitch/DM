"""add campaign-scoped opt-in source-book content packs

Revision ID: e3c6a8f2b917
Revises: d2f4a7b9c1e3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3c6a8f2b917"
down_revision: str | None = "d2f4a7b9c1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "enabled_content_packs",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "enabled_content_packs")
