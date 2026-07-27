from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dnd_dm_assistant.api.player_gateway import create_player_gateway
from dnd_dm_assistant.config import Settings


@pytest.fixture
def gateway(tmp_path: Path) -> Iterator[TestClient]:
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><title>Player Gateway</title><main>player-shell</main>",
        encoding="utf-8",
    )
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'gateway.db'}",
    )
    with TestClient(create_player_gateway(settings, static_dir=static_dir)) as client:
        yield client


def test_gateway_serves_health_and_built_player_shell(gateway: TestClient) -> None:
    health = gateway.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "player-gateway"}
    assert health.headers["cache-control"] == "no-store"
    assert health.headers["x-frame-options"] == "DENY"

    frontend = gateway.get("/")
    assert frontend.status_code == 200
    assert "player-shell" in frontend.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/campaigns"),
        ("GET", "/api/v1/campaigns/private-campaign/state"),
        ("POST", "/api/v1/campaigns/private-campaign/player-room"),
        ("GET", "/api/v1/system/diagnostics"),
        ("POST", "/api/v1/knowledge/search"),
        ("POST", "/api/v1/campaigns/private-campaign/assistant/turns"),
    ],
)
def test_gateway_does_not_mount_dm_routes(
    gateway: TestClient, method: str, path: str
) -> None:
    response = gateway.request(method, path, json={})
    assert response.status_code == 404


def test_gateway_route_table_contains_only_public_api() -> None:
    app = create_player_gateway(Settings(environment="test"), static_dir=Path("/missing"))
    api_paths = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/")
    }
    assert "/api/v1/health" in api_paths
    assert not any(path.startswith("/api/v1/campaigns") for path in api_paths)
    assert not any(path.startswith("/api/v1/system") for path in api_paths)
    assert not any(path.startswith("/api/v1/knowledge") for path in api_paths)


def test_gateway_mounts_public_room_router_before_api_deny_rule(
    gateway: TestClient,
) -> None:
    missing_join_body = gateway.post("/api/v1/player-room/join", json={})
    assert missing_join_body.status_code == 422

    unauthenticated_snapshot = gateway.get("/api/v1/player-room/me")
    assert unauthenticated_snapshot.status_code == 401
