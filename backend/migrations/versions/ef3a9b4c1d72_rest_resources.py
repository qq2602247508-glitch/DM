"""add rest records and normalized resource pools

Revision ID: ef3a9b4c1d72
Revises: d02f8c41e6ab
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ef3a9b4c1d72"
down_revision: str | None = "d02f8c41e6ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
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
    ]


def upgrade() -> None:
    with op.batch_alter_table("characters") as batch_op:
        batch_op.add_column(
            sa.Column(
                "max_hp_reduction",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "ability_score_reductions",
                sa.JSON(),
                server_default="{}",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "death_saves",
                sa.JSON(),
                server_default='{"successes":0,"failures":0}',
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_character_max_hp_reduction",
            "max_hp_reduction >= 0 AND max_hp_reduction <= max_hp",
        )

    op.create_table(
        "resource_pools",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("character_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=50), server_default="other", nullable=False),
        sa.Column("current", sa.Integer(), server_default="0", nullable=False),
        sa.Column("maximum", sa.Integer(), server_default="0", nullable=False),
        sa.Column("recovery_timing", sa.String(length=30), server_default="manual", nullable=False),
        sa.Column("recovery_amount", sa.Integer(), nullable=True),
        sa.Column("die_size", sa.Integer(), nullable=True),
        sa.Column("source_record_id", sa.String(length=100), nullable=True),
        sa.Column("rule_key", sa.String(length=200), nullable=True),
        sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("length(trim(key)) > 0", name="ck_resource_pool_key_nonempty"),
        sa.CheckConstraint("length(trim(label)) > 0", name="ck_resource_pool_label_nonempty"),
        sa.CheckConstraint(
            "current >= 0 AND maximum >= 0 AND current <= maximum", name="ck_resource_pool_bounds"
        ),
        sa.CheckConstraint(
            "recovery_amount IS NULL OR recovery_amount >= 0",
            name="ck_resource_pool_recovery_amount",
        ),
        sa.CheckConstraint("die_size IS NULL OR die_size >= 2", name="ck_resource_pool_die_size"),
        sa.CheckConstraint(
            "category IN ('class_feature','spell_slot','hit_die','item','other')",
            name="ck_resource_pool_category",
        ),
        sa.CheckConstraint(
            "recovery_timing IN ('short_rest','long_rest','both','dawn','manual','none')",
            name="ck_resource_pool_recovery_timing",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("character_id", "key", name="uq_resource_pool_character_key"),
    )
    op.create_index(
        "ix_resource_pools_campaign_character",
        "resource_pools",
        ["campaign_id", "character_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_pools_character_timing",
        "resource_pools",
        ["character_id", "recovery_timing", "id"],
        unique=False,
    )

    op.create_table(
        "rest_records",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("operation_transaction_id", sa.String(length=36), nullable=True),
        sa.Column("rest_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("duration_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("interrupted", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("world_time_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("world_time_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("result_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("rest_type IN ('short','long')", name="ck_rest_record_type"),
        sa.CheckConstraint(
            "status IN ('pending','completed','interrupted','failed','reverted')",
            name="ck_rest_record_status",
        ),
        sa.CheckConstraint("duration_minutes >= 0", name="ck_rest_record_duration"),
        sa.CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_rest_record_completion_after_start",
        ),
        sa.CheckConstraint(
            "interrupted = 0 OR status = 'interrupted'", name="ck_rest_record_interrupted_status"
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["operation_transaction_id"], ["operation_transactions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id", "idempotency_key", name="uq_rest_record_campaign_idempotency"
        ),
        sa.UniqueConstraint(
            "operation_transaction_id", name="uq_rest_record_operation_transaction"
        ),
    )
    op.create_index(
        "ix_rest_records_campaign_created",
        "rest_records",
        ["campaign_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_rest_records_campaign_status",
        "rest_records",
        ["campaign_id", "status", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "rest_recovery_entries",
        sa.Column("rest_record_id", sa.String(length=36), nullable=False),
        sa.Column("character_id", sa.String(length=36), nullable=False),
        sa.Column("resource_pool_id", sa.String(length=36), nullable=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("before_value", sa.Integer(), nullable=True),
        sa.Column("after_value", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("die_roll", sa.Integer(), nullable=True),
        sa.Column("modifier", sa.Integer(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("rule_reference", sa.String(length=200), nullable=True),
        sa.Column("selected", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("applied", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "type IN ('hp','resource','hit_die','spell_slot','condition','other')",
            name="ck_rest_recovery_entry_type",
        ),
        sa.CheckConstraint("amount IS NULL OR amount >= 0", name="ck_rest_recovery_entry_amount"),
        sa.CheckConstraint(
            "die_roll IS NULL OR die_roll >= 1", name="ck_rest_recovery_entry_die_roll"
        ),
        sa.CheckConstraint(
            "status IN ('pending','applied','skipped','failed','reverted')",
            name="ck_rest_recovery_entry_status",
        ),
        sa.CheckConstraint(
            "applied = 0 OR status = 'applied'", name="ck_rest_recovery_entry_applied_status"
        ),
        sa.ForeignKeyConstraint(["rest_record_id"], ["rest_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_pool_id"], ["resource_pools.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rest_recovery_entries_rest",
        "rest_recovery_entries",
        ["rest_record_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_rest_recovery_entries_character",
        "rest_recovery_entries",
        ["character_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_rest_recovery_entries_character", table_name="rest_recovery_entries")
    op.drop_index("ix_rest_recovery_entries_rest", table_name="rest_recovery_entries")
    op.drop_table("rest_recovery_entries")
    op.drop_index("ix_rest_records_campaign_status", table_name="rest_records")
    op.drop_index("ix_rest_records_campaign_created", table_name="rest_records")
    op.drop_table("rest_records")
    op.drop_index("ix_resource_pools_character_timing", table_name="resource_pools")
    op.drop_index("ix_resource_pools_campaign_character", table_name="resource_pools")
    op.drop_table("resource_pools")
    with op.batch_alter_table("characters") as batch_op:
        batch_op.drop_constraint(
            "ck_character_max_hp_reduction",
            type_="check",
        )
        batch_op.drop_column("death_saves")
        batch_op.drop_column("ability_score_reductions")
        batch_op.drop_column("max_hp_reduction")
