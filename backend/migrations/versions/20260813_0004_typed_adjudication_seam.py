"""add source-bound typed adjudication seam fields

Revision ID: 20260813_0004
Revises: 20260813_0003
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0004"
down_revision: str | None = "20260813_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("rules_kernel_adjudications") as batch:
        batch.add_column(sa.Column("source_record_id", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("source_fingerprint", sa.String(length=128), nullable=True))
        batch.add_column(
            sa.Column("source_clause_ids", sa.JSON(), server_default="[]", nullable=True)
        )
        batch.add_column(sa.Column("target_context", sa.JSON(), server_default="{}", nullable=True))
        batch.add_column(
            sa.Column("effect_envelope", sa.JSON(), server_default="{}", nullable=True)
        )
        batch.add_column(sa.Column("decision_kind", sa.String(length=50), nullable=True))
        batch.add_column(
            sa.Column("producer_provenance", sa.JSON(), server_default="{}", nullable=True)
        )
    op.execute(
        sa.text(
            "UPDATE rules_kernel_adjudications "
            "SET source_record_id = COALESCE(content_id, 'legacy-unbound'), "
            "source_fingerprint = 'legacy-unbound', "
            "source_clause_ids = '[]', target_context = '{}', effect_envelope = '{}', "
            "decision_kind = 'target_selection', producer_provenance = '{}'"
        )
    )
    with op.batch_alter_table("rules_kernel_adjudications") as batch:
        batch.alter_column("source_record_id", nullable=False)
        batch.alter_column("source_fingerprint", nullable=False)
        batch.alter_column("source_clause_ids", nullable=False)
        batch.alter_column("target_context", nullable=False)
        batch.alter_column("effect_envelope", nullable=False)
        batch.alter_column("decision_kind", nullable=False)
        batch.alter_column("producer_provenance", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("rules_kernel_adjudications") as batch:
        for name in (
            "producer_provenance",
            "decision_kind",
            "effect_envelope",
            "target_context",
            "source_clause_ids",
            "source_fingerprint",
            "source_record_id",
        ):
            batch.drop_column(name)
