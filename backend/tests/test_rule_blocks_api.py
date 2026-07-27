from __future__ import annotations

from fastapi.testclient import TestClient


def test_compile_rule_blocks_api_returns_versioned_deterministic_plan(
    client: TestClient,
) -> None:
    body = {
        "source_kind": "item",
        "source": {
            "name": "治疗药水",
            "range": "自身",
            "damage": "治疗2d4+2",
            "resolution_kind": "heal",
            "resource_key": "inventory:healing-potion",
            "resource_cost": 1,
        },
    }
    first = client.post("/api/v1/rules/blocks/compile", json=body)
    second = client.post("/api/v1/rules/blocks/compile", json=body)

    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["rule_plan"]["schema_version"] == "1.0"
    assert first.json()["rule_plan"]["automation_ready"] is True
    assert any(
        block["kind"] == "heal"
        for block in first.json()["rule_plan"]["blocks"]
    )
    assert len(first.json()["execution_plan"]["rule_plan_fingerprint"]) == 64


def test_compile_rule_blocks_api_refuses_to_invent_missing_damage(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/rules/blocks/compile",
        json={
            "source_kind": "feature",
            "source": {
                "name": "神秘能力",
                "description": "对目标造成由DM决定的伤害。",
                "resolution_kind": "damage",
            },
        },
    )

    assert response.status_code == 200
    result = response.json()["rule_plan"]
    assert result["automation_ready"] is False
    assert all(block["kind"] != "damage" for block in result["blocks"])
