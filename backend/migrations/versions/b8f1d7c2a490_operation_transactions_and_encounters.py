"""add operation transactions and encounter adjustment proposals

Revision ID: b8f1d7c2a490
Revises: a31e76c904bf
Create Date: 2026-07-26 18:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b8f1d7c2a490"
down_revision: str | None = "a31e76c904bf"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "operation_transactions",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("operation_type", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="applied", nullable=False),
        sa.Column("before_snapshot", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("after_snapshot", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=30), server_default="dm", nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
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
            "source IN ('dm','game_table','combat','system')",
            name="ck_operation_transaction_source",
        ),
        sa.CheckConstraint(
            "status IN ('pending','applied','reverted','conflict','failed')",
            name="ck_operation_transaction_status",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "idempotency_key",
            name="uq_operation_transaction_campaign_idempotency",
        ),
    )
    op.create_index(
        "ix_operation_transactions_campaign_created",
        "operation_transactions",
        ["campaign_id", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "encounter_adjustment_proposals",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=False),
        sa.Column("combat_id", sa.String(length=36), nullable=True),
        sa.Column("source_event_id", sa.String(length=36), nullable=True),
        sa.Column("operation_transaction_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("difficulty_shift", sa.Integer(), server_default="0", nullable=False),
        sa.Column("operations_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("inverse_operations_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
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
            "difficulty_shift IN (-1,0,1)",
            name="ck_encounter_adjustment_difficulty_shift",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_encounter_adjustment_reason",
        ),
        sa.CheckConstraint(
            "status IN ('pending','applied','rejected','reverted','conflict')",
            name="ck_encounter_adjustment_status",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_encounter_adjustment_title",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["combat_id"], ["combats.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_event_id"], ["events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["operation_transaction_id"],
            ["operation_transactions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_encounter_adjustments_campaign_status",
        "encounter_adjustment_proposals",
        ["campaign_id", "status", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_encounter_adjustments_scene_combat",
        "encounter_adjustment_proposals",
        ["scene_id", "combat_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_encounter_adjustments_scene_combat",
        table_name="encounter_adjustment_proposals",
    )
    op.drop_index(
        "ix_encounter_adjustments_campaign_status",
        table_name="encounter_adjustment_proposals",
    )
    op.drop_table("encounter_adjustment_proposals")
    op.drop_index(
        "ix_operation_transactions_campaign_created",
        table_name="operation_transactions",
    )
    op.drop_table("operation_transactions")
