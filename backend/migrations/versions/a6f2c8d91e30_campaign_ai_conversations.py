"""add per-campaign non-authoritative AI conversations

Revision ID: a6f2c8d91e30
Revises: e7c4a1b9d205
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a6f2c8d91e30"
down_revision: str | None = "e7c4a1b9d205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_ai_sessions",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id"),
    )
    op.create_table(
        "campaign_ai_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("message_kind", sa.String(length=30), nullable=False),
        sa.Column("authoritative", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("request_id", sa.String(length=120), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('dm','assistant')", name="ck_campaign_ai_message_role"),
        sa.CheckConstraint(
            "message_kind IN ('question','answer','confirmed_progress')",
            name="ck_campaign_ai_message_kind",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["campaign_ai_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "sequence_number", name="uq_campaign_ai_message_sequence"
        ),
    )
    op.create_index(
        "ix_campaign_ai_messages_session_created",
        "campaign_ai_messages",
        ["session_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_ai_messages_session_created", table_name="campaign_ai_messages")
    op.drop_table("campaign_ai_messages")
    op.drop_table("campaign_ai_sessions")
