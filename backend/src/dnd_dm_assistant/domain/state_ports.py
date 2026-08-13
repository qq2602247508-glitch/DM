from __future__ import annotations

from typing import Any, Protocol

from dnd_dm_assistant.domain.campaign_state import CampaignState


class CampaignStateGateway(Protocol):
    """Infrastructure-neutral port for structured campaign state use cases."""

    def create(
        self,
        entity_type: str,
        data: dict[str, Any],
        *,
        campaign_id: str | None = None,
        request_id: str = "unknown",
    ) -> dict[str, Any]: ...

    def create_audible_sound_event(
        self,
        campaign_id: str,
        data: dict[str, Any],
        *,
        request_id: str = "unknown",
    ) -> dict[str, Any]: ...

    def get(
        self, entity_type: str, entity_id: str, *, campaign_id: str | None = None
    ) -> dict[str, Any]: ...

    def list(
        self,
        entity_type: str,
        *,
        campaign_id: str | None,
        limit: int = 100,
        offset: int = 0,
        open_only: bool = False,
        parent_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]: ...

    def update(
        self,
        entity_type: str,
        entity_id: str,
        data: dict[str, Any],
        *,
        campaign_id: str | None = None,
        expected_version: int,
        request_id: str = "unknown",
    ) -> dict[str, Any]: ...

    def delete(
        self,
        entity_type: str,
        entity_id: str,
        *,
        campaign_id: str | None = None,
        expected_version: int,
        request_id: str = "unknown",
    ) -> None: ...

    def state(self, campaign_id: str, *, limit: int = 100) -> CampaignState: ...
