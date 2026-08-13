"""add formal vessel containment persistence"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0003"
down_revision: str | None = "20260811_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vessel_spaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("vessel_id", sa.String(length=200), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("owner_character_id", sa.String(length=36), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=True),
        sa.Column("combat_id", sa.String(length=36), nullable=True),
        sa.Column("source_record_id", sa.String(length=200), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("state_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("occupants_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("items_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("termination_reason", sa.String(length=100), nullable=True),
        sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("vessel_id"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_character_id"], ["characters.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["combat_id"], ["combats.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('outside','inside','destroyed','removed')",
            name="ck_vessel_space_status",
        ),
    )
    op.create_index(
        "ix_vessel_spaces_campaign_status",
        "vessel_spaces",
        ["campaign_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_vessel_spaces_owner_campaign",
        "vessel_spaces",
        ["owner_character_id", "campaign_id", "vessel_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_vessel_spaces_owner_campaign", table_name="vessel_spaces")
    op.drop_index("ix_vessel_spaces_campaign_status", table_name="vessel_spaces")
    op.drop_table("vessel_spaces")
