"""add persistent exploration grids, clock and travel

Revision ID: 9a1e2d3c4b5a
Revises: ef3a9b4c1d72
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "9a1e2d3c4b5a"
down_revision = "ef3a9b4c1d72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _idcols() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
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
    ]


def upgrade() -> None:
    op.create_table(
        "scene_grids",
        *_idcols(),
        sa.Column(
            "scene_id",
            sa.String(36),
            sa.ForeignKey("scenes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("width", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("cell_size_ft", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("mode", sa.String(20), nullable=False, server_default="narrative"),
        sa.Column("public_description", sa.Text()),
        sa.Column("dm_description", sa.Text()),
        sa.Column("layers_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "width >= 1 AND width <= 100 AND height >= 1 AND height <= 100",
            name="ck_scene_grid_size",
        ),
        sa.CheckConstraint(
            "cell_size_ft >= 1 AND cell_size_ft <= 100", name="ck_scene_grid_cell_size"
        ),
        sa.CheckConstraint(
            "mode IN ('narrative','exploration','combat')", name="ck_scene_grid_mode"
        ),
    )
    op.create_table(
        "scene_tokens",
        *_idcols(),
        sa.Column(
            "scene_id",
            sa.String(36),
            sa.ForeignKey("scenes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_id", sa.String(36)),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("row", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("col", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("size_cells", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("elevation_ft", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "entity_type IN ('character','npc','monster','marker')", name="ck_scene_token_type"
        ),
        sa.CheckConstraint(
            "row >= 1 AND col >= 1 AND size_cells >= 1 AND size_cells <= 4",
            name="ck_scene_token_coords",
        ),
    )
    op.create_index("ix_scene_tokens_scene", "scene_tokens", ["scene_id", "id"])
    op.create_table(
        "scene_objects",
        *_idcols(),
        sa.Column(
            "scene_id",
            sa.String(36),
            sa.ForeignKey("scenes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_type", sa.String(30), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("row", sa.Integer(), nullable=False),
        sa.Column("col", sa.Integer(), nullable=False),
        sa.Column("width_cells", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("height_cells", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("interaction_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "object_type IN ('wall','door','cover','terrain','light','trap','treasure',"
            "'furniture','portal')",
            name="ck_scene_object_type",
        ),
        sa.CheckConstraint(
            "state IN ('active','open','closed','destroyed','disarmed','picked_up')",
            name="ck_scene_object_state",
        ),
        sa.CheckConstraint(
            "visibility IN ('public','dm','hidden')", name="ck_scene_object_visibility"
        ),
    )
    op.create_index("ix_scene_objects_scene", "scene_objects", ["scene_id", "id"])
    op.create_table(
        "visibility_states",
        *_idcols(),
        sa.Column(
            "scene_id",
            sa.String(36),
            sa.ForeignKey("scenes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("viewer_key", sa.String(100), nullable=False),
        sa.Column("explored_cells", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("visible_cells", sa.JSON(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("scene_id", "viewer_key", name="uq_visibility_scene_viewer"),
    )
    op.create_table(
        "world_clock",
        *_idcols(),
        sa.Column(
            "campaign_id",
            sa.String(36),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("current_time", sa.DateTime(timezone=True)),
        sa.Column(
            "calendar_name", sa.String(100), nullable=False, server_default="Fantasy Calendar"
        ),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_table(
        "exploration_turns",
        *_idcols(),
        sa.Column(
            "campaign_id",
            sa.String(36),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scene_id",
            sa.String(36),
            sa.ForeignKey("scenes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.String(36),
            sa.ForeignKey("operation_transactions.id", ondelete="SET NULL"),
        ),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False, server_default="explore"),
        sa.Column("result_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.CheckConstraint("minutes >= 1 AND minutes <= 1440", name="ck_exploration_turn_minutes"),
    )
    op.create_index(
        "ix_exploration_turns_scene", "exploration_turns", ["scene_id", "created_at", "id"]
    )
    op.create_table(
        "travel_legs",
        *_idcols(),
        sa.Column(
            "campaign_id",
            sa.String(36),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_location_id", sa.String(36), sa.ForeignKey("locations.id", ondelete="SET NULL")
        ),
        sa.Column(
            "to_location_id",
            sa.String(36),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.String(36),
            sa.ForeignKey("operation_transactions.id", ondelete="SET NULL"),
        ),
        sa.Column("distance_miles", sa.Float(), nullable=False),
        sa.Column("pace", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("details_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.CheckConstraint("distance_miles >= 0", name="ck_travel_leg_distance"),
        sa.CheckConstraint("pace IN ('fast','normal','slow')", name="ck_travel_leg_pace"),
        sa.CheckConstraint("duration_minutes >= 0", name="ck_travel_leg_duration"),
        sa.CheckConstraint(
            "status IN ('planned','completed','interrupted')", name="ck_travel_leg_status"
        ),
    )
    op.create_index("ix_travel_legs_campaign", "travel_legs", ["campaign_id", "created_at", "id"])


def downgrade() -> None:
    for table in (
        "travel_legs",
        "exploration_turns",
        "world_clock",
        "visibility_states",
        "scene_objects",
        "scene_tokens",
        "scene_grids",
    ):
        op.drop_table(table)
