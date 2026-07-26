from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dnd_dm_assistant.application.campaigns import CampaignService
from dnd_dm_assistant.domain.campaign_state import CampaignState


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def create(
        self,
        entity_type: str,
        data: dict[str, Any],
        *,
        campaign_id: str | None = None,
        request_id: str = "unknown",
    ) -> dict[str, Any]:
        self.calls.append(("create", (entity_type, data, campaign_id, request_id)))
        return {"id": "fake", **data}

    def get(
        self, entity_type: str, entity_id: str, *, campaign_id: str | None = None
    ) -> dict[str, Any]:
        return {"id": entity_id, "campaign_id": campaign_id, "type": entity_type}

    def list(
        self,
        entity_type: str,
        *,
        campaign_id: str | None,
        limit: int = 100,
        offset: int = 0,
        open_only: bool = False,
        parent_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        return ()

    def update(
        self,
        entity_type: str,
        entity_id: str,
        data: dict[str, Any],
        *,
        campaign_id: str | None = None,
        expected_version: int,
        request_id: str = "unknown",
    ) -> dict[str, Any]:
        return {"id": entity_id, "version": expected_version + 1, **data}

    def delete(
        self,
        entity_type: str,
        entity_id: str,
        *,
        campaign_id: str | None = None,
        expected_version: int,
        request_id: str = "unknown",
    ) -> None:
        self.calls.append(("delete", entity_id))

    def state(self, campaign_id: str, *, limit: int = 100) -> CampaignState:
        return CampaignState(
            campaign={"id": campaign_id},
            characters=(),
            npcs=(),
            locations=(),
            quests=(),
            open_clues=(),
            active_combats=(),
            as_of=datetime.now(UTC),
        )


def test_application_service_is_persistence_neutral() -> None:
    gateway = FakeGateway()
    service = CampaignService(gateway)
    created = service.create("campaign", {"name": "No database"}, request_id="fake-request")
    assert created == {"id": "fake", "name": "No database"}
    assert gateway.calls == [
        ("create", ("campaign", {"name": "No database"}, None, "fake-request"))
    ]
    assert service.state("campaign-1").campaign == {"id": "campaign-1"}
