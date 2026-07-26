"""add atomic combat settlements

Revision ID: d02f8c41e6ab
Revises: c91e4b7a2d30
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d02f8c41e6ab"
down_revision: str | None = "c91e4b7a2d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "combat_settlements",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("combat_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="confirmed",
            nullable=False,
        ),
        sa.Column("resolution_type", sa.String(length=30), nullable=False),
        sa.Column("xp_allocations", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("writebacks", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("result_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
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
            "status IN ('confirmed','reverted','conflict')",
            name="ck_combat_settlement_status",
        ),
        sa.CheckConstraint(
            "resolution_type IN "
            "('victory','defeat','retreat','negotiated','bypassed','other')",
            name="ck_combat_settlement_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["combat_id"],
            ["combats.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["operation_transactions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("combat_id", name="uq_combat_settlement_combat"),
        sa.UniqueConstraint(
            "campaign_id",
            "idempotency_key",
            name="uq_combat_settlement_campaign_idempotency",
        ),
    )
    op.create_index(
        "ix_combat_settlements_campaign_confirmed",
        "combat_settlements",
        ["campaign_id", "confirmed_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_combat_settlements_campaign_confirmed",
        table_name="combat_settlements",
    )
    op.drop_table("combat_settlements")
