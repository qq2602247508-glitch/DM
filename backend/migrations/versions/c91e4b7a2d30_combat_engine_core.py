"""add combat engine core state and logs

Revision ID: c91e4b7a2d30
Revises: b8f1d7c2a490
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c91e4b7a2d30"
down_revision: str | None = "b8f1d7c2a490"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("combatants") as batch_op:
        batch_op.drop_constraint("ck_combatant_hp", type_="check")
        batch_op.add_column(
            sa.Column("temporary_hp", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("max_hp_reduction", sa.Integer(), server_default="0", nullable=False)
        )
        for name in (
            "damage_resistances",
            "damage_vulnerabilities",
            "damage_immunities",
            "condition_immunities",
        ):
            batch_op.add_column(sa.Column(name, sa.JSON(), server_default="[]", nullable=False))
        batch_op.add_column(
            sa.Column("concentration", sa.JSON(), server_default="{}", nullable=False)
        )
        batch_op.add_column(
            sa.Column("speed_ft", sa.Integer(), server_default="30", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "movement_remaining_ft",
                sa.Integer(),
                server_default="30",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("action_available", sa.Boolean(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "bonus_action_available",
                sa.Boolean(),
                server_default="1",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("reaction_available", sa.Boolean(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("snapshot_json", sa.JSON(), server_default="{}", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_combatant_hp",
            "hp >= 0 AND max_hp >= 0 AND hp + max_hp_reduction <= max_hp",
        )
        batch_op.create_check_constraint(
            "ck_combatant_temporary_hp",
            "temporary_hp >= 0",
        )
        batch_op.create_check_constraint(
            "ck_combatant_max_hp_reduction",
            "max_hp_reduction >= 0 AND max_hp_reduction <= max_hp",
        )
        batch_op.create_check_constraint("ck_combatant_speed", "speed_ft >= 0")
        batch_op.create_check_constraint(
            "ck_combatant_movement_remaining",
            "movement_remaining_ft >= 0",
        )

    op.create_table(
        "combat_actions",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("combat_id", sa.String(length=36), nullable=False),
        sa.Column("actor_combatant_id", sa.String(length=36), nullable=True),
        sa.Column("transaction_id", sa.String(length=36), nullable=True),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("target_combatant_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("request_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("result_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("dm_override", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="confirmed", nullable=False),
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
            "status IN ('previewed','confirmed','reverted','conflict')",
            name="ck_combat_action_status",
        ),
        sa.CheckConstraint("round_number >= 1", name="ck_combat_action_round"),
        sa.CheckConstraint("turn_index >= 0", name="ck_combat_action_turn"),
        sa.CheckConstraint(
            "length(trim(summary)) > 0",
            name="ck_combat_action_summary",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["combat_id"], ["combats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["actor_combatant_id"],
            ["combatants.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["operation_transactions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "combat_id",
            "idempotency_key",
            name="uq_combat_action_combat_idempotency",
        ),
    )
    op.create_index(
        "ix_combat_actions_combat_created",
        "combat_actions",
        ["combat_id", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "combat_effects",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("combat_id", sa.String(length=36), nullable=False),
        sa.Column("target_combatant_id", sa.String(length=36), nullable=False),
        sa.Column("source_combatant_id", sa.String(length=36), nullable=True),
        sa.Column("source_action_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("effect_type", sa.String(length=50), nullable=False),
        sa.Column("details_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("started_round", sa.Integer(), nullable=False),
        sa.Column(
            "duration_unit",
            sa.String(length=30),
            server_default="until_removed",
            nullable=False,
        ),
        sa.Column("duration_value", sa.Integer(), nullable=True),
        sa.Column("ends_round", sa.Integer(), nullable=True),
        sa.Column(
            "requires_concentration",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("save_dc", sa.Integer(), nullable=True),
        sa.Column("save_ability", sa.String(length=30), nullable=True),
        sa.Column("trigger_timing", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="active", nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
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
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_combat_effect_name"),
        sa.CheckConstraint("started_round >= 1", name="ck_combat_effect_started_round"),
        sa.CheckConstraint(
            "duration_value IS NULL OR duration_value >= 0",
            name="ck_combat_effect_duration",
        ),
        sa.CheckConstraint(
            "ends_round IS NULL OR ends_round >= started_round",
            name="ck_combat_effect_ends_round",
        ),
        sa.CheckConstraint(
            "save_dc IS NULL OR save_dc >= 0",
            name="ck_combat_effect_save_dc",
        ),
        sa.CheckConstraint(
            "status IN ('active','ended')",
            name="ck_combat_effect_status",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["combat_id"], ["combats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["target_combatant_id"],
            ["combatants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_combatant_id"],
            ["combatants.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_action_id"],
            ["combat_actions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_combat_effects_target_status",
        "combat_effects",
        ["target_combatant_id", "status", "id"],
        unique=False,
    )

    op.create_table(
        "death_saves",
        sa.Column("combatant_id", sa.String(length=36), nullable=False),
        sa.Column("successes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stable", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("dead", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "pending_death_confirmation",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_roll", sa.Integer(), nullable=True),
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
            "successes >= 0 AND successes <= 3",
            name="ck_death_save_successes",
        ),
        sa.CheckConstraint(
            "failures >= 0 AND failures <= 3",
            name="ck_death_save_failures",
        ),
        sa.CheckConstraint(
            "last_roll IS NULL OR (last_roll >= 1 AND last_roll <= 20)",
            name="ck_death_save_last_roll",
        ),
        sa.ForeignKeyConstraint(["combatant_id"], ["combatants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("combatant_id", name="uq_death_save_combatant"),
    )

    op.create_table(
        "combat_reinforcements",
        sa.Column("combat_id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("target_round", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("deployed", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
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
            "entity_type IN ('character','npc','monster')",
            name="ck_combat_reinforcement_type",
        ),
        sa.CheckConstraint(
            "target_round >= 1",
            name="ck_combat_reinforcement_round",
        ),
        sa.CheckConstraint(
            "quantity >= 1",
            name="ck_combat_reinforcement_quantity",
        ),
        sa.ForeignKeyConstraint(["combat_id"], ["combats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["encounter_adjustment_proposals.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_combat_reinforcements_combat_round",
        "combat_reinforcements",
        ["combat_id", "target_round", "deployed", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_combat_reinforcements_combat_round",
        table_name="combat_reinforcements",
    )
    op.drop_table("combat_reinforcements")
    op.drop_table("death_saves")
    op.drop_index(
        "ix_combat_effects_target_status",
        table_name="combat_effects",
    )
    op.drop_table("combat_effects")
    op.drop_index(
        "ix_combat_actions_combat_created",
        table_name="combat_actions",
    )
    op.drop_table("combat_actions")

    with op.batch_alter_table("combatants") as batch_op:
        batch_op.drop_constraint("ck_combatant_movement_remaining", type_="check")
        batch_op.drop_constraint("ck_combatant_speed", type_="check")
        batch_op.drop_constraint("ck_combatant_max_hp_reduction", type_="check")
        batch_op.drop_constraint("ck_combatant_temporary_hp", type_="check")
        batch_op.drop_constraint("ck_combatant_hp", type_="check")
        batch_op.create_check_constraint(
            "ck_combatant_hp",
            "hp >= 0 AND max_hp >= 0 AND hp <= max_hp",
        )
        for name in (
            "snapshot_json",
            "reaction_available",
            "bonus_action_available",
            "action_available",
            "movement_remaining_ft",
            "speed_ft",
            "concentration",
            "condition_immunities",
            "damage_immunities",
            "damage_vulnerabilities",
            "damage_resistances",
            "max_hp_reduction",
            "temporary_hp",
        ):
            batch_op.drop_column(name)
