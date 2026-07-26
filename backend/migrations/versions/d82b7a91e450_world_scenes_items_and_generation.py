"""world scenes items and generation

Revision ID: d82b7a91e450
Revises: c4e8a2f9d610
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d82b7a91e450"
down_revision: str | None = "c4e8a2f9d610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], ...]:
    return (
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
    )


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(
            sa.Column("ruleset", sa.String(length=30), server_default="dnd5e", nullable=False)
        )
        batch_op.add_column(
            sa.Column("primary_rules_year", sa.Integer(), server_default="2024", nullable=False)
        )
        batch_op.add_column(
            sa.Column("allow_legacy", sa.Boolean(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "encumbrance_mode",
                sa.String(length=30),
                server_default="standard",
                nullable=False,
            )
        )
        batch_op.create_check_constraint("ck_campaign_ruleset", "ruleset = 'dnd5e'")
        batch_op.create_check_constraint(
            "ck_campaign_rules_year", "primary_rules_year = 2024"
        )
        batch_op.create_check_constraint(
            "ck_campaign_encumbrance",
            "encumbrance_mode IN ('standard','variant','none')",
        )

    with op.batch_alter_table("locations") as batch_op:
        batch_op.add_column(sa.Column("parent_location_id", sa.String(length=36)))
        batch_op.add_column(
            sa.Column("depth", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("interactive_objects", sa.JSON(), server_default="[]", nullable=False)
        )
        batch_op.add_column(sa.Column("secrets", sa.Text()))
        batch_op.add_column(
            sa.Column("discovered", sa.Boolean(), server_default="1", nullable=False)
        )
        batch_op.create_foreign_key(
            "fk_locations_parent",
            "locations",
            ["parent_location_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_location_depth", "depth >= 1 AND depth <= 10"
        )

    with op.batch_alter_table("npcs") as batch_op:
        batch_op.add_column(
            sa.Column("armor_class", sa.Integer(), server_default="10", nullable=False)
        )
        batch_op.add_column(sa.Column("hp", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(
            sa.Column("max_hp", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("speed", sa.Integer(), server_default="30", nullable=False)
        )
        batch_op.add_column(
            sa.Column("ability_scores", sa.JSON(), server_default="{}", nullable=False)
        )
        batch_op.add_column(sa.Column("challenge_rating", sa.String(length=30)))
        batch_op.add_column(
            sa.Column("actions", sa.JSON(), server_default="[]", nullable=False)
        )
        batch_op.add_column(
            sa.Column("equipment", sa.JSON(), server_default="[]", nullable=False)
        )
        batch_op.create_check_constraint("ck_npc_ac", "armor_class >= 0 AND armor_class <= 99")
        batch_op.create_check_constraint(
            "ck_npc_hp", "hp >= 0 AND max_hp >= 0 AND hp <= max_hp"
        )

    op.create_table(
        "world_items",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("category", sa.String(length=50), server_default="misc", nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("unit_weight_lb", sa.Float(), server_default="0", nullable=False),
        sa.Column("price_cp", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source_record_id", sa.String(length=100)),
        sa.Column("source_label", sa.String(length=30), server_default="custom", nullable=False),
        sa.Column("location_id", sa.String(length=36)),
        sa.Column("owner_character_id", sa.String(length=36)),
        sa.Column("is_equipped", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("is_hidden", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_world_item_name_nonempty"),
        sa.CheckConstraint("quantity >= 1", name="ck_world_item_quantity"),
        sa.CheckConstraint("unit_weight_lb >= 0", name="ck_world_item_weight"),
        sa.CheckConstraint("price_cp >= 0", name="ck_world_item_price"),
        sa.CheckConstraint(
            "NOT (location_id IS NOT NULL AND owner_character_id IS NOT NULL)",
            name="ck_world_item_single_holder",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["owner_character_id"], ["characters.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_world_items_campaign_location",
        "world_items",
        ["campaign_id", "location_id", "id"],
    )
    op.create_index(
        "ix_world_items_campaign_owner",
        "world_items",
        ["campaign_id", "owner_character_id", "id"],
    )

    op.create_table(
        "monster_instances",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_record_id", sa.String(length=100)),
        sa.Column("source_name", sa.String(length=200)),
        sa.Column("armor_class", sa.Integer(), server_default="10", nullable=False),
        sa.Column("hp", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_hp", sa.Integer(), server_default="1", nullable=False),
        sa.Column("speed", sa.Integer(), server_default="30", nullable=False),
        sa.Column("ability_scores", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("challenge_rating", sa.String(length=30)),
        sa.Column("actions", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_monster_name_nonempty"),
        sa.CheckConstraint("armor_class >= 0 AND armor_class <= 99", name="ck_monster_ac"),
        sa.CheckConstraint(
            "hp >= 0 AND max_hp >= 0 AND hp <= max_hp", name="ck_monster_hp"
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_monsters_campaign_created",
        "monster_instances",
        ["campaign_id", "created_at", "id"],
    )

    op.create_table(
        "scenes",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("location_id", sa.String(length=36)),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(length=30), server_default="active", nullable=False),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_scene_name_nonempty"),
        sa.CheckConstraint("status IN ('draft','active','closed')", name="ck_scene_status"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scenes_campaign_status",
        "scenes",
        ["campaign_id", "status", "created_at", "id"],
    )

    op.create_table(
        "scene_participants",
        sa.Column("scene_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=30), server_default="present", nullable=False),
        sa.Column("visible", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint(
            "entity_type IN ('character','npc','monster')",
            name="ck_scene_participant_type",
        ),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scene_id", "entity_type", "entity_id", name="uq_scene_participant"
        ),
    )
    op.create_index(
        "ix_scene_participants_scene",
        "scene_participants",
        ["scene_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scene_participants_scene", table_name="scene_participants")
    op.drop_table("scene_participants")
    op.drop_index("ix_scenes_campaign_status", table_name="scenes")
    op.drop_table("scenes")
    op.drop_index("ix_monsters_campaign_created", table_name="monster_instances")
    op.drop_table("monster_instances")
    op.drop_index("ix_world_items_campaign_owner", table_name="world_items")
    op.drop_index("ix_world_items_campaign_location", table_name="world_items")
    op.drop_table("world_items")
    with op.batch_alter_table("npcs") as batch_op:
        batch_op.drop_constraint("ck_npc_hp", type_="check")
        batch_op.drop_constraint("ck_npc_ac", type_="check")
        batch_op.drop_column("equipment")
        batch_op.drop_column("actions")
        batch_op.drop_column("challenge_rating")
        batch_op.drop_column("ability_scores")
        batch_op.drop_column("speed")
        batch_op.drop_column("max_hp")
        batch_op.drop_column("hp")
        batch_op.drop_column("armor_class")
    with op.batch_alter_table("locations") as batch_op:
        batch_op.drop_constraint("ck_location_depth", type_="check")
        batch_op.drop_constraint("fk_locations_parent", type_="foreignkey")
        batch_op.drop_column("discovered")
        batch_op.drop_column("secrets")
        batch_op.drop_column("interactive_objects")
        batch_op.drop_column("depth")
        batch_op.drop_column("parent_location_id")
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.drop_constraint("ck_campaign_encumbrance", type_="check")
        batch_op.drop_constraint("ck_campaign_rules_year", type_="check")
        batch_op.drop_constraint("ck_campaign_ruleset", type_="check")
        batch_op.drop_column("encumbrance_mode")
        batch_op.drop_column("allow_legacy")
        batch_op.drop_column("primary_rules_year")
        batch_op.drop_column("ruleset")
