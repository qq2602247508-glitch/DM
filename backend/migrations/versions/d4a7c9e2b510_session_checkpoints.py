"""add authoritative server-side session checkpoints

Revision ID: d4a7c9e2b510
Revises: b9d4e6f812a0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7c9e2b510"
down_revision: str | None = "b9d4e6f812a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamp() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
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
    op.create_table(
        "campaign_session_states",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("current_scene_id", sa.String(36)),
        sa.Column("active_combat_id", sa.String(36)),
        sa.Column("restored_checkpoint_id", sa.String(36)),
        sa.Column("entries_json", sa.JSON(), server_default="[]", nullable=False),
        *_stamp(),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_scene_id"], ["scenes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["active_combat_id"], ["combats.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("campaign_id", name="uq_campaign_session_state_campaign"),
    )
    op.create_table(
        "session_checkpoints",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("scene_id", sa.String(36)),
        sa.Column("active_combat_id", sa.String(36)),
        sa.Column("base_campaign_version", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("entries_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("snapshot_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("dependencies_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True)),
        sa.Column("restore_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notes", sa.Text()),
        *_stamp(),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["active_combat_id"], ["combats.id"], ondelete="SET NULL"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_session_checkpoint_name"),
        sa.CheckConstraint("schema_version = 1", name="ck_session_checkpoint_schema"),
        sa.CheckConstraint(
            "status IN ('active','archived')", name="ck_session_checkpoint_status"
        ),
        sa.CheckConstraint(
            "base_campaign_version >= 1", name="ck_session_checkpoint_campaign_version"
        ),
        sa.CheckConstraint("restore_count >= 0", name="ck_session_checkpoint_restore_count"),
    )
    op.create_index(
        "ix_session_checkpoints_campaign_created",
        "session_checkpoints",
        ["campaign_id", "status", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_session_checkpoints_campaign_created", table_name="session_checkpoints"
    )
    op.drop_table("session_checkpoints")
    op.drop_table("campaign_session_states")
