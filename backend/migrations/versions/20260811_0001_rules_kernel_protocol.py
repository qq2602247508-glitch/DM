"""add durable rules-kernel command, workflow and scene-delta records

Revision ID: 20260811_0001
Revises: e3c6a8f2b917
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0001"
down_revision: str | None = "e3c6a8f2b917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "rules_kernel_commands",
        *_timestamps(),
        sa.Column("command_id", sa.String(length=120), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=True),
        sa.Column("combat_id", sa.String(length=36), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("action_kind", sa.String(length=50), nullable=False),
        sa.Column("command_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("preview_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("result_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="previewed", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["combat_id"], ["combats.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("command_id"),
        sa.UniqueConstraint("campaign_id", "idempotency_key", name="uq_rules_kernel_command_idempotency"),
    )
    op.create_index("ix_rules_kernel_commands_campaign_created", "rules_kernel_commands", ["campaign_id", "created_at", "id"])

    op.create_table(
        "rules_kernel_choice_windows",
        *_timestamps(),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("source_command_id", sa.String(length=120), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("content_id", sa.String(length=200), nullable=True),
        sa.Column("choice_kind", sa.String(length=40), nullable=False),
        sa.Column("option_source", sa.String(length=40), nullable=False),
        sa.Column("frozen_options", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("minimum_choices", sa.Integer(), server_default="1", nullable=False),
        sa.Column("maximum_choices", sa.Integer(), server_default="1", nullable=False),
        sa.Column("replacement_policy", sa.String(length=40), server_default="reject", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_versions", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("resolution", sa.JSON(), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_rules_kernel_choices_campaign_status", "rules_kernel_choice_windows", ["campaign_id", "status", "created_at", "id"])

    op.create_table(
        "rules_kernel_adjudications",
        *_timestamps(),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("source_command_id", sa.String(length=120), nullable=False),
        sa.Column("content_id", sa.String(length=200), nullable=True),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by", sa.String(length=30), server_default="player", nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("source_text_evidence", sa.Text(), nullable=False),
        sa.Column("typed_known_effects", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("open_questions", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("allowed_decision_schema", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("frozen_context", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("expected_versions", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="pending_dm", nullable=False),
        sa.Column("dm_decision", sa.JSON(), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_rules_kernel_adjudications_campaign_status", "rules_kernel_adjudications", ["campaign_id", "status", "created_at", "id"])

    op.create_table(
        "rules_kernel_scene_deltas",
        *_timestamps(),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=True),
        sa.Column("source_command_id", sa.String(length=120), nullable=False),
        sa.Column("delta_id", sa.String(length=160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("delta_type", sa.String(length=50), nullable=False),
        sa.Column("delta_json", sa.JSON(), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("delta_id"),
        sa.UniqueConstraint("campaign_id", "sequence", name="uq_rules_kernel_scene_delta_cursor"),
    )
    op.create_index("ix_rules_kernel_scene_deltas_scene_sequence", "rules_kernel_scene_deltas", ["scene_id", "sequence", "id"])


def downgrade() -> None:
    op.drop_index("ix_rules_kernel_scene_deltas_scene_sequence", table_name="rules_kernel_scene_deltas")
    op.drop_table("rules_kernel_scene_deltas")
    op.drop_index("ix_rules_kernel_adjudications_campaign_status", table_name="rules_kernel_adjudications")
    op.drop_table("rules_kernel_adjudications")
    op.drop_index("ix_rules_kernel_choices_campaign_status", table_name="rules_kernel_choice_windows")
    op.drop_table("rules_kernel_choice_windows")
    op.drop_index("ix_rules_kernel_commands_campaign_created", table_name="rules_kernel_commands")
    op.drop_table("rules_kernel_commands")

