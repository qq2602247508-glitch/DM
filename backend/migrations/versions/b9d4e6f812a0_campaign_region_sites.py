"""add campaign region maps and multi-level adventure sites

Revision ID: b9d4e6f812a0
Revises: a4c7e2f91b30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9d4e6f812a0"
down_revision: str | None = "a4c7e2f91b30"
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
        "region_maps",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("location_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("width", sa.Integer(), server_default="24", nullable=False),
        sa.Column("height", sa.Integer(), server_default="16", nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("map_json", sa.JSON(), server_default="{}", nullable=False),
        *_stamp(),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.CheckConstraint("width >= 8 AND width <= 100", name="ck_region_map_width"),
        sa.CheckConstraint("height >= 8 AND height <= 100", name="ck_region_map_height"),
        sa.UniqueConstraint("campaign_id", "location_id", name="uq_region_map_location"),
    )
    op.create_index(
        "ix_region_maps_campaign_created",
        "region_maps",
        ["campaign_id", "created_at", "id"],
    )
    op.create_table(
        "adventure_sites",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("region_map_id", sa.String(36), nullable=False),
        sa.Column("location_id", sa.String(36), nullable=False),
        sa.Column("site_type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("theme", sa.String(100), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("maximum_levels", sa.Integer(), nullable=False),
        sa.Column("party_level", sa.Integer(), nullable=False),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("generation_parameters", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("map_position", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("generation_request_id", sa.String(100), nullable=True),
        *_stamp(),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["region_map_id"], ["region_maps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.CheckConstraint("site_type IN ('building','dungeon')", name="ck_site_type"),
        sa.CheckConstraint("maximum_levels >= 1 AND maximum_levels <= 20", name="ck_site_levels"),
        sa.CheckConstraint("party_level >= 1 AND party_level <= 20", name="ck_site_party_level"),
        sa.CheckConstraint("party_size >= 1 AND party_size <= 12", name="ck_site_party_size"),
        sa.CheckConstraint("status IN ('draft','active','archived')", name="ck_site_status"),
        sa.UniqueConstraint("campaign_id", "location_id", name="uq_site_location"),
        sa.UniqueConstraint(
            "campaign_id", "generation_request_id", name="uq_site_generation_request"
        ),
    )
    op.create_index(
        "ix_sites_campaign_region",
        "adventure_sites",
        ["campaign_id", "region_map_id", "created_at", "id"],
    )
    op.create_table(
        "site_levels",
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("location_id", sa.String(36), nullable=False),
        sa.Column("level_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("encounter_budget_xp", sa.Integer(), nullable=False),
        sa.Column("reward_budget_gp", sa.Integer(), nullable=False),
        sa.Column("layout_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("generation_json", sa.JSON(), server_default="{}", nullable=False),
        *_stamp(),
        sa.ForeignKeyConstraint(["site_id"], ["adventure_sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.CheckConstraint("level_index >= 1 AND level_index <= 20", name="ck_site_level_index"),
        sa.CheckConstraint(
            "difficulty IN ('low','moderate','high')", name="ck_site_level_difficulty"
        ),
        sa.CheckConstraint("encounter_budget_xp >= 0", name="ck_site_level_xp"),
        sa.CheckConstraint("reward_budget_gp >= 0", name="ck_site_level_reward"),
        sa.UniqueConstraint("site_id", "level_index", name="uq_site_level_index"),
    )
    op.create_index("ix_site_levels_site_index", "site_levels", ["site_id", "level_index", "id"])
    op.create_table(
        "site_rooms",
        sa.Column("site_level_id", sa.String(36), nullable=False),
        sa.Column("location_id", sa.String(36), nullable=False),
        sa.Column("room_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("room_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("bounds_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("encounter_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("reward_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("interactive_objects", sa.JSON(), server_default="[]", nullable=False),
        *_stamp(),
        sa.ForeignKeyConstraint(["site_level_id"], ["site_levels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.CheckConstraint("room_index >= 1", name="ck_site_room_index"),
        sa.UniqueConstraint("site_level_id", "room_index", name="uq_site_room_index"),
    )
    op.create_index(
        "ix_site_rooms_level_index", "site_rooms", ["site_level_id", "room_index", "id"]
    )
    op.create_table(
        "site_connectors",
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("from_level_index", sa.Integer(), nullable=False),
        sa.Column("from_room_index", sa.Integer()),
        sa.Column("to_level_index", sa.Integer(), nullable=False),
        sa.Column("to_room_index", sa.Integer()),
        sa.Column("connector_type", sa.String(20), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), server_default="closed", nullable=False),
        sa.Column("position_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
        *_stamp(),
        sa.ForeignKeyConstraint(["site_id"], ["adventure_sites.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "connector_type IN ('door','stairs_up','stairs_down','secret_door','portal')",
            name="ck_site_connector_type",
        ),
        sa.CheckConstraint(
            "state IN ('open','closed','locked','hidden')", name="ck_site_connector_state"
        ),
    )
    op.create_index(
        "ix_site_connectors_site_levels",
        "site_connectors",
        ["site_id", "from_level_index", "to_level_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_site_connectors_site_levels", table_name="site_connectors")
    op.drop_table("site_connectors")
    op.drop_index("ix_site_rooms_level_index", table_name="site_rooms")
    op.drop_table("site_rooms")
    op.drop_index("ix_site_levels_site_index", table_name="site_levels")
    op.drop_table("site_levels")
    op.drop_index("ix_sites_campaign_region", table_name="adventure_sites")
    op.drop_table("adventure_sites")
    op.drop_index("ix_region_maps_campaign_created", table_name="region_maps")
    op.drop_table("region_maps")
