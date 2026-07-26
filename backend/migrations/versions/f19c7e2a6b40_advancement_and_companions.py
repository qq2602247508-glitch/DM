"""add advancement history and character companions

Revision ID: f19c7e2a6b40
Revises: ef3a9b4c1d72
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f19c7e2a6b40"
down_revision: str | None = "ef3a9b4c1d72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.String(36), nullable=False),
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
            sa.Column("class_levels", sa.JSON(), server_default="{}", nullable=False)
        )
        batch_op.add_column(
            sa.Column("subclass_choices", sa.JSON(), server_default="{}", nullable=False)
        )

    op.create_table(
        "advancement_records",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("character_id", sa.String(36), nullable=False),
        sa.Column("operation_transaction_id", sa.String(36), nullable=True),
        sa.Column("class_name", sa.String(100), nullable=False),
        sa.Column("subclass_name", sa.String(100), nullable=True),
        sa.Column("from_level", sa.Integer(), nullable=False),
        sa.Column("to_level", sa.Integer(), nullable=False),
        sa.Column("choices_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("result_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("preview_token", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), server_default="confirmed", nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "from_level >= 1 AND to_level >= 2 AND to_level <= 20 "
            "AND to_level = from_level + 1",
            name="ck_advancement_level_step",
        ),
        sa.CheckConstraint(
            "status IN ('confirmed','reverted','conflict')",
            name="ck_advancement_status",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["operation_transaction_id"],
            ["operation_transactions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "idempotency_key",
            name="uq_advancement_campaign_idempotency",
        ),
    )
    op.create_index(
        "ix_advancement_character_level",
        "advancement_records",
        ["character_id", "to_level", "created_at", "id"],
    )
    op.create_table(
        "character_companions",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("owner_character_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("companion_type", sa.String(30), nullable=False),
        sa.Column("source_record_id", sa.String(100), nullable=True),
        sa.Column("template_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("hp", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_hp", sa.Integer(), server_default="1", nullable=False),
        sa.Column("armor_class", sa.Integer(), server_default="10", nullable=False),
        sa.Column("speed", sa.Integer(), server_default="30", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_companion_name_nonempty"),
        sa.CheckConstraint(
            "companion_type IN "
            "('familiar','animal_companion','summon','wild_shape','form')",
            name="ck_companion_type",
        ),
        sa.CheckConstraint(
            "hp >= 0 AND max_hp >= 1 AND hp <= max_hp",
            name="ck_companion_hp",
        ),
        sa.CheckConstraint(
            "armor_class >= 0 AND armor_class <= 99",
            name="ck_companion_ac",
        ),
        sa.CheckConstraint(
            "speed >= 0 AND speed <= 1000",
            name="ck_companion_speed",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_character_id"],
            ["characters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_companions_campaign_owner",
        "character_companions",
        ["campaign_id", "owner_character_id", "active", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_companions_campaign_owner", table_name="character_companions")
    op.drop_table("character_companions")
    op.drop_index("ix_advancement_character_level", table_name="advancement_records")
    op.drop_table("advancement_records")
    with op.batch_alter_table("characters") as batch_op:
        batch_op.drop_column("subclass_choices")
        batch_op.drop_column("class_levels")
