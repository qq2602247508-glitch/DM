from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dnd_dm_assistant.infrastructure.database.models import Base, Timestamped


class CampaignSessionState(Timestamped, Base):
    """The small, authoritative server-side state of the DM game table."""

    __tablename__ = "campaign_session_states"

    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    current_scene_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="SET NULL")
    )
    active_combat_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("combats.id", ondelete="SET NULL")
    )
    restored_checkpoint_id: Mapped[str | None] = mapped_column(String(36))
    entries_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )


class SessionCheckpoint(Timestamped, Base):
    """An immutable campaign checkpoint; restoring it never mutates the checkpoint."""

    __tablename__ = "session_checkpoints"

    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    scene_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="SET NULL")
    )
    active_combat_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("combats.id", ondelete="SET NULL")
    )
    base_campaign_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    entries_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    dependencies_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restore_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_session_checkpoint_name"),
        CheckConstraint("schema_version = 1", name="ck_session_checkpoint_schema"),
        CheckConstraint(
            "status IN ('active','archived')", name="ck_session_checkpoint_status"
        ),
        CheckConstraint(
            "base_campaign_version >= 1",
            name="ck_session_checkpoint_campaign_version",
        ),
        CheckConstraint("restore_count >= 0", name="ck_session_checkpoint_restore_count"),
        Index(
            "ix_session_checkpoints_campaign_created",
            "campaign_id",
            "status",
            "created_at",
            "id",
        ),
    )
