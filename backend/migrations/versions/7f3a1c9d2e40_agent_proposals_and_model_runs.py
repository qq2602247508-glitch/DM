"""agent proposals and model runs

Revision ID: 7f3a1c9d2e40
Revises: fb7d3fc91b8a
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f3a1c9d2e40"
down_revision: str | None = "fb7d3fc91b8a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "state_change_proposals",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column(
            "tool_name",
            sa.String(length=80),
            server_default="update_campaign_state",
            nullable=False,
        ),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("payload_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("created_by_model", sa.String(length=200), nullable=False),
        sa.Column("request_id", sa.String(length=120), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
            "entity_type IN ('character','npc','quest','event')",
            name="ck_proposal_entity",
        ),
        sa.CheckConstraint(
            "operation IN ('create','update','delete')", name="ck_proposal_operation"
        ),
        sa.CheckConstraint(
            "status IN ('pending','confirmed','rejected','conflict')",
            name="ck_proposal_status",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("state_change_proposals") as batch_op:
        batch_op.create_index(
            "ix_proposals_campaign_status_created",
            ["campaign_id", "status", "created_at", "id"],
            unique=False,
        )
    op.create_table(
        "model_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=120), nullable=False),
        sa.Column("model_role", sa.String(length=30), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("latency_ms >= 0", name="ck_model_run_latency"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("model_runs") as batch_op:
        batch_op.create_index(
            "ix_model_runs_campaign_request",
            ["campaign_id", "request_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("model_runs") as batch_op:
        batch_op.drop_index("ix_model_runs_campaign_request")
    op.drop_table("model_runs")
    with op.batch_alter_table("state_change_proposals") as batch_op:
        batch_op.drop_index("ix_proposals_campaign_status_created")
    op.drop_table("state_change_proposals")
