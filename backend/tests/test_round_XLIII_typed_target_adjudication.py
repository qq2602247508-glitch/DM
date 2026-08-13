from __future__ import annotations

import json
import runpy
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/validate-round-XLIII-typed-target-adjudication.py"
REPORT = ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"


def test_round_xliii_audit_is_conservative_and_deterministic() -> None:
    namespace = runpy.run_path(str(SCRIPT))
    first = namespace["build_report"]()
    second = namespace["build_report"]()
    assert first["after"]["promoted_ids"] == []
    assert len(first["after"]["retained_compile_only_ids"]) == 5
    assert first["count_delta"] == {"compile_only": 0, "production": 0, "unique_compiled": 0}
    assert first["report_fingerprint"] == second["report_fingerprint"]
    assert first["focused_tests"]["passed"] is True
    assert set(first["source_boundary_matrix"]) == {
        "core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb",
        "core-phb-2024:spell:83b7d94b77f332dd71310bbe",
        "core-phb-2024:spell:b9db026fa1853bca5b6f1c13",
        "core-phb-2024:spell:d82624a42cf6c33ccec927b8",
        "core-phb-2024:spell:dd9cb25c63b7e13194c7d01c",
    }
    saved = json.loads(REPORT.read_text(encoding="utf-8"))
    assert saved["report_fingerprint"] == first["report_fingerprint"]
    assert (
        subprocess.run(
            ["git", "check-ignore", "--no-index", str(REPORT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        != 0
    )


def _typed_command(ids: dict[str, str], command_id: str) -> tuple[dict, dict]:
    source_binding = {
        "content_id": "core-phb-2024:spell:typed-seam",
        "source_record_id": "typed-seam-record",
        "source_fingerprint": "a" * 64,
        "clause_ids": ["core-phb-2024:spell:typed-seam:clause:target"],
    }
    contract = {
        "decision_kind": "target_selection",
        "target_context": {
            "campaign_id": ids["campaign_id"],
            "scene_id": ids["scene_id"],
            "actor_id": ids["actor_id"],
            "target_kind": "single_entity",
            "target_id": ids["target_id"],
            "target_type": "creature",
        },
        "effect_envelope": {
            "allowed_effect_kinds": ["modifier"],
            "allowed_fields": ["stat", "operation", "value", "duration"],
            "duration": {"unit": "rounds", "value": 1},
            "source_semantics": ["typed-target"],
        },
        "source_binding": source_binding,
    }
    command = {
        "schema_version": "rules-kernel-1",
        "command_id": command_id,
        "idempotency_key": f"idempotency-{command_id}",
        "campaign_id": ids["campaign_id"],
        "scene_id": ids["scene_id"],
        "combat_id": ids["combat_id"],
        "actor_id": ids["actor_id"],
        "content_id": source_binding["content_id"],
        "content_kind": "spell",
        "action_kind": "adjudication",
        "target_intent": {
            "target_ids": [ids["target_id"]],
            "target_kind": "one_creature",
        },
        "expected_versions": {
            "actor_version": 1,
            "target_versions": {ids["target_id"]: 1},
            "combat_version": 1,
            "scene_version": 1,
        },
        "metadata": {
            "clause_types": ["target_semantics"],
            "adjudication": {
                "category": "target_semantics",
                "source_text_evidence": "Source-bound typed target contract.",
                "allowed_decision_schema": ["approved_targets", "notes"],
            },
            "typed_adjudication": contract,
        },
    }
    return command, contract


def test_round_xliii_legacy_adjudication_is_fail_closed(campaign_client: TestClient) -> None:
    from backend.tests.test_rules_kernel import _seed_kernel_graph

    ids = _seed_kernel_graph(campaign_client)
    command = {
        "schema_version": "rules-kernel-1",
        "command_id": "command-legacy-unbound-1",
        "idempotency_key": "idempotency-legacy-unbound-1",
        "campaign_id": ids["campaign_id"],
        "scene_id": ids["scene_id"],
        "combat_id": ids["combat_id"],
        "actor_id": ids["actor_id"],
        "content_id": "legacy-content",
        "content_kind": "system",
        "action_kind": "adjudication",
        "target_intent": {"target_kind": "freeform", "semantic": "freeform"},
        "expected_versions": {
            "actor_version": 1,
            "combat_version": 1,
            "scene_version": 1,
        },
        "metadata": {
            "clause_types": ["target_semantics"],
            "adjudication": {
                "source_text_evidence": "Historical unbound adjudication."
            },
        },
    }
    preview = campaign_client.post("/api/v1/rules-kernel/preview", json=command)
    assert preview.status_code == 200, preview.text
    adjudication_id = preview.json()["required_adjudications"][0]["adjudication_id"]
    decision = {"adjudication_id": adjudication_id, "status": "approved"}
    resolved = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={"permission": "dm", "decision": decision},
    )
    assert resolved.status_code == 200, resolved.text
    confirmed = campaign_client.post(
        "/api/v1/rules-kernel/confirm",
        json={
            **command,
            "preview_version": 1,
            "adjudication_decisions": [decision],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["adjudication_receipt"] == {}
    assert result["operation_transaction_id"] is None


def test_round_xliii_typed_resolution_rejects_target_and_contract_drift(
    campaign_client: TestClient,
) -> None:
    from backend.tests.test_rules_kernel import _seed_kernel_graph

    ids = _seed_kernel_graph(campaign_client)
    command, contract = _typed_command(ids, "command-typed-drift-1")
    preview = campaign_client.post("/api/v1/rules-kernel/preview", json=command)
    assert preview.status_code == 200, preview.text
    request = preview.json()["required_adjudications"][0]
    adjudication_id = request["adjudication_id"]
    wrong_target = {
        "adjudication_id": adjudication_id,
        "status": "approved",
        "approved_targets": [ids["actor_id"]],
        "typed_contract": contract,
    }
    target_response = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={"permission": "dm", "decision": wrong_target},
    )
    assert target_response.status_code == 400
    assert "target" in target_response.text

    changed_contract = json.loads(json.dumps(contract))
    changed_contract["effect_envelope"]["duration"]["value"] = 2
    contract_response = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={
            "permission": "dm",
            "decision": {
                "adjudication_id": adjudication_id,
                "status": "approved",
                "approved_targets": [ids["target_id"]],
                "typed_contract": changed_contract,
            },
        },
    )
    assert contract_response.status_code == 400
    assert "frozen contract" in contract_response.text


def test_round_xliii_typed_resolution_rejects_payload_drift_on_replay(
    campaign_client: TestClient,
) -> None:
    from backend.tests.test_rules_kernel import _seed_kernel_graph

    ids = _seed_kernel_graph(campaign_client)
    command, contract = _typed_command(ids, "command-typed-replay-drift-1")
    preview = campaign_client.post("/api/v1/rules-kernel/preview", json=command)
    assert preview.status_code == 200, preview.text
    adjudication_id = preview.json()["required_adjudications"][0]["adjudication_id"]
    decision = {
        "adjudication_id": adjudication_id,
        "status": "approved",
        "approved_targets": [ids["target_id"]],
        "typed_contract": contract,
    }
    first = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={"permission": "dm", "idempotency_key": "replay-drift-key", "decision": decision},
    )
    assert first.status_code == 200, first.text
    drift = dict(decision)
    drift["notes"] = "forged after resolution"
    second = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={"permission": "dm", "idempotency_key": "replay-drift-key", "decision": drift},
    )
    assert second.status_code == 400
    assert "payload drift" in second.text


def test_round_xliii_adjudication_stale_cas_and_expiry_fail_closed(
    campaign_client: TestClient,
) -> None:
    from backend.tests.test_rules_kernel import _seed_kernel_graph
    from sqlalchemy.orm import Session

    from dnd_dm_assistant.infrastructure.database import create_database_engine
    from dnd_dm_assistant.infrastructure.database.models import (
        RulesKernelAdjudicationWindow,
    )

    ids = _seed_kernel_graph(campaign_client)
    command, contract = _typed_command(ids, "command-typed-cas-expiry-1")
    preview = campaign_client.post("/api/v1/rules-kernel/preview", json=command)
    assert preview.status_code == 200, preview.text
    adjudication_id = preview.json()["required_adjudications"][0]["adjudication_id"]
    decision = {
        "adjudication_id": adjudication_id,
        "status": "approved",
        "approved_targets": [ids["target_id"]],
        "typed_contract": contract,
    }
    stale = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={
            "permission": "dm",
            "expected_version": 99,
            "decision": decision,
        },
    )
    assert stale.status_code == 409

    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        window = session.get(RulesKernelAdjudicationWindow, adjudication_id)
        assert window is not None
        window.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    expired = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={"permission": "dm", "decision": decision},
    )
    assert expired.status_code == 400
    assert "expired" in expired.text
