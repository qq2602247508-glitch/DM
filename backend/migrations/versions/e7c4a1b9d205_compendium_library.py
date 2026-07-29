"""add reusable campaign compendium entries

Revision ID: e7c4a1b9d205
Revises: d4a7c9e2b510
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7c4a1b9d205"
down_revision: str | None = "d4a7c9e2b510"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compendium_entries",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("entry_type", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "source_kind",
            sa.String(length=30),
            server_default="original",
            nullable=False,
        ),
        sa.Column("source_record_id", sa.String(length=100), nullable=True),
        sa.Column("source_name", sa.String(length=200), nullable=True),
        sa.Column("family_key", sa.String(length=100), nullable=True),
        sa.Column("tags", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("filters_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("rules_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "entry_type IN "
            "('spell','feature','monster','equipment','item','npc','location','scene')",
            name="ck_compendium_entry_type",
        ),
        sa.CheckConstraint(
            "source_kind IN ('official','original','ai_generated','dm_modified','third_party')",
            name="ck_compendium_source_kind",
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_compendium_name_nonempty"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "entry_type",
            "name",
            "source_kind",
            name="uq_compendium_campaign_type_name_source",
        ),
    )
    op.create_index(
        "ix_compendium_campaign_type_name",
        "compendium_entries",
        ["campaign_id", "entry_type", "name", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_compendium_campaign_type_name", table_name="compendium_entries")
    op.drop_table("compendium_entries")
