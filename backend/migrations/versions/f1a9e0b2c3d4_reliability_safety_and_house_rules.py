"""add local recovery points, safe mode and explicit house-rule overrides

Revision ID: f1a9e0b2c3d4
Revises: fa8b1c2d3e40
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1a9e0b2c3d4"
down_revision = "fa8b1c2d3e40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_table(
        "recovery_points",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("file_name", sa.String(length=300), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_request_id", sa.String(length=120), nullable=False),
        sa.Column("preview_token", sa.String(length=200), nullable=True),
        sa.Column("previewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_recovery_points_created", "recovery_points", ["created_at", "id"])
    op.create_table(
        "house_rule_overrides",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.String(length=36),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_key", sa.String(length=160), nullable=False),
        sa.Column("core_value_json", sa.JSON(), nullable=False),
        sa.Column("override_value_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
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
        sa.UniqueConstraint("campaign_id", "rule_key", name="uq_house_rule_campaign_key"),
    )
    op.create_index(
        "ix_house_rule_campaign", "house_rule_overrides", ["campaign_id", "created_at", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_house_rule_campaign", table_name="house_rule_overrides")
    op.drop_table("house_rule_overrides")
    op.drop_index("ix_recovery_points_created", table_name="recovery_points")
    op.drop_table("recovery_points")
    op.drop_table("system_settings")
