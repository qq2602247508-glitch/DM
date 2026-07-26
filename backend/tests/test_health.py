from __future__ import annotations

from fastapi.testclient import TestClient

from dnd_dm_assistant.api.dependencies import get_runtime_integrations
from dnd_dm_assistant.domain.runtime_status import (
    ConfiguredModelStatus,
    RuntimeModelStatus,
)


def test_health_returns_typed_status(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "environment": "test",
    }
    assert response.headers["X-Request-ID"]


def test_missing_route_uses_stable_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/missing", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 404
    assert response.json() == {
        "code": "http_404",
        "message": "Not Found",
        "details": None,
        "request_id": "test-request",
    }


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    allowed = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    denied = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "access-control-allow-origin" not in denied.headers


def test_runtime_models_reports_installed_configured_models(client: TestClient) -> None:
    class FakeRuntime:
        async def model_status(self) -> RuntimeModelStatus:
            return RuntimeModelStatus(
                ollama_available=True,
                think_enabled=False,
                installed_models=("bge-m3:latest", "qwen3:30b-instruct"),
                models=(
                    ConfiguredModelStatus(
                        role="intent",
                        model="qwen3:30b-instruct",
                        configured=True,
                        installed=True,
                    ),
                    ConfiguredModelStatus(
                        role="reasoning",
                        model="qwen3:30b-instruct",
                        configured=True,
                        installed=True,
                    ),
                    ConfiguredModelStatus(
                        role="embedding",
                        model="bge-m3:latest",
                        configured=True,
                        installed=True,
                    ),
                ),
            )

    client.app.dependency_overrides[get_runtime_integrations] = lambda: FakeRuntime()
    try:
        response = client.get("/api/v1/runtime/models")
    finally:
        client.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["ollama_available"] is True
    assert response.json()["think_enabled"] is False
    assert all(item["installed"] for item in response.json()["models"])
