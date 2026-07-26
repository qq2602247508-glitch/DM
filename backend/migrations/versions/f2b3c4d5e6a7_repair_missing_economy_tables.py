"""repair economy tables missing from previously stamped local databases

Revision ID: f2b3c4d5e6a7
Revises: f1a9e0b2c3d4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2b3c4d5e6a7"
down_revision: str | None = "f1a9e0b2c3d4"
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
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "known_spells" not in existing:
        op.create_table(
            "known_spells",
            sa.Column("campaign_id", sa.String(36), nullable=False),
            sa.Column("character_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("spell_level", sa.Integer(), server_default="0", nullable=False),
            sa.Column("source_reference", sa.String(200)),
            sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
            *_stamp(),
            sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
            sa.CheckConstraint("length(trim(name)) > 0", name="ck_known_spell_name"),
            sa.CheckConstraint(
                "spell_level >= 0 AND spell_level <= 9",
                name="ck_known_spell_level",
            ),
            sa.UniqueConstraint(
                "character_id",
                "name",
                name="uq_known_spell_character_name",
            ),
        )
        op.create_index(
            "ix_known_spells_character",
            "known_spells",
            ["character_id", "created_at", "id"],
        )

    if "prepared_spells" not in existing:
        op.create_table(
            "prepared_spells",
            sa.Column("known_spell_id", sa.String(36), nullable=False),
            sa.Column("character_id", sa.String(36), nullable=False),
            sa.Column("prepared", sa.Boolean(), server_default="1", nullable=False),
            *_stamp(),
            sa.ForeignKeyConstraint(
                ["known_spell_id"],
                ["known_spells.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "character_id",
                "known_spell_id",
                name="uq_prepared_spell_character_known",
            ),
        )

    if "equipment_instances" not in existing:
        op.create_table(
            "equipment_instances",
            sa.Column("campaign_id", sa.String(36), nullable=False),
            sa.Column("character_id", sa.String(36)),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("category", sa.String(30), server_default="gear", nullable=False),
            sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
            sa.Column("armor_class", sa.Integer()),
            sa.Column("equipped", sa.Boolean(), server_default="0", nullable=False),
            sa.Column(
                "attunement_required",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            ),
            sa.Column("charges", sa.Integer()),
            sa.Column("max_charges", sa.Integer()),
            sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
            *_stamp(),
            sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="SET NULL"),
            sa.CheckConstraint("length(trim(name)) > 0", name="ck_equipment_name"),
            sa.CheckConstraint("quantity >= 0", name="ck_equipment_quantity"),
            sa.CheckConstraint(
                "charges IS NULL OR (charges >= 0 AND max_charges IS NOT NULL "
                "AND charges <= max_charges)",
                name="ck_equipment_charges",
            ),
        )
        op.create_index(
            "ix_equipment_campaign_character",
            "equipment_instances",
            ["campaign_id", "character_id", "id"],
        )

    if "attunements" not in existing:
        op.create_table(
            "attunements",
            sa.Column("character_id", sa.String(36), nullable=False),
            sa.Column("equipment_instance_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(20), server_default="active", nullable=False),
            *_stamp(),
            sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["equipment_instance_id"],
                ["equipment_instances.id"],
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(
                "status IN ('active','ended')",
                name="ck_attunement_status",
            ),
            sa.UniqueConstraint(
                "equipment_instance_id",
                name="uq_attunement_equipment",
            ),
        )
        op.create_index(
            "ix_attunements_character_status",
            "attunements",
            ["character_id", "status", "id"],
        )

    if "wallets" not in existing:
        op.create_table(
            "wallets",
            sa.Column("campaign_id", sa.String(36), nullable=False),
            sa.Column("character_id", sa.String(36)),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("copper", sa.Integer(), server_default="0", nullable=False),
            *_stamp(),
            sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
            sa.CheckConstraint("copper >= 0", name="ck_wallet_copper"),
            sa.UniqueConstraint(
                "campaign_id",
                "character_id",
                name="uq_wallet_campaign_character",
            ),
        )

    if "currency_transactions" not in existing:
        op.create_table(
            "currency_transactions",
            sa.Column("campaign_id", sa.String(36), nullable=False),
            sa.Column("wallet_id", sa.String(36), nullable=False),
            sa.Column("amount_copper", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
            *_stamp(),
            sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
            sa.CheckConstraint(
                "kind IN ('purchase','sale','split','adjustment')",
                name="ck_currency_transaction_kind",
            ),
            sa.UniqueConstraint(
                "campaign_id",
                "idempotency_key",
                name="uq_currency_transaction_idempotency",
            ),
        )
        op.create_index(
            "ix_currency_transactions_wallet",
            "currency_transactions",
            ["wallet_id", "created_at", "id"],
        )

    if "shop_inventories" not in existing:
        op.create_table(
            "shop_inventories",
            sa.Column("campaign_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("quantity", sa.Integer(), server_default="0", nullable=False),
            sa.Column("price_copper", sa.Integer(), server_default="0", nullable=False),
            sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
            *_stamp(),
            sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
            sa.CheckConstraint("length(trim(name)) > 0", name="ck_shop_inventory_name"),
            sa.CheckConstraint(
                "quantity >= 0 AND price_copper >= 0",
                name="ck_shop_inventory_bounds",
            ),
        )
        op.create_index(
            "ix_shop_inventory_campaign",
            "shop_inventories",
            ["campaign_id", "created_at", "id"],
        )


def downgrade() -> None:
    # Repair migrations must never remove tables that may have been created by
    # the original b41c9e7a2d30 migration.
    pass
