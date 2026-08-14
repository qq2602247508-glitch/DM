"""Dedicated Round XLII regression receipt for Genie Bottled Respite."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from dnd_dm_assistant.application import content_ir_production_evidence, tashas_whole_pack
from dnd_dm_assistant.application.tashas_whole_pack import build_migration

ROOT = Path(__file__).resolve().parents[2]
FEATURE_ID = "content.tashas-cauldron.round2.feature.genie-bottled-respite"
VALIDATOR = ROOT / "scripts/validate-tashas-feature-production-consumer-round-XLII.py"
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XLII-2026-08-13.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XLII.json"
BASELINE = ROOT / "reports/tashas-production-reconciliation-round-XXV-2026-08-12.json"
BASELINE_SHA256 = "1ca123067fedbcf6e8592afc8272f1e6f935280d475658c45613e4545094f8c7"
RESULTS_SHA256 = "430572cbea12360a75e98935626a6d82635a767504ee4957341844b674f8314d"
REPORT_SHA256 = "1ac0d3e2ebd52bf44df33d075e0194105d228d28e88bb69a21849adc6ecdcfe5"


def _load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("round_xlii_validator", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_round_xlii_validator_receipt_and_canonical_counts_are_locked() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    migration = build_migration(ROOT)
    validator = _load_validator()
    spec, _compile_result, runtime, consumers = validator._load_runtime()

    assert report["decision"] == "promoted"
    assert results["all_required_checks_passed"] is True
    assert results["production_runtime_full_ids"] == [FEATURE_ID]
    assert results["compile_only_ids"] == []
    assert results["registry_consumers"] == [
        "vessel.external_sound.v1",
        "vessel.space.v1",
    ]
    assert report["checks"]["source_complete_and_provenance"] is True
    assert report["checks"]["external_sound_typed_and_producer_bound"] is True
    assert spec.source_completeness == "complete"
    assert spec.source_record_id == "98620543cf94e974361c6567"
    assert spec.source_fingerprint == (
        "e81b718b2ee8728e75cf77c2f00c33312a283a9e12d3654d9bb377a64ec745c7"
    )
    assert consumers == ["vessel.external_sound.v1", "vessel.space.v1"]
    assert runtime["vessel_external_sound"][0]["sound_contract"] == {
        "schema": "vessel.external_sound.v1",
        "channel": "hearing",
        "source_facts_authority": "asserted_input",
        "state_mutated": False,
        "producer_bound": True,
    }
    assert results["checks"]["name_branch_count_zero"] is True
    assert results["checks"]["protected_paths_unchanged"] is True

    assert report["baseline_artifact"]["path"] == str(BASELINE.relative_to(ROOT))
    assert report["baseline_artifact"]["sha256"] == BASELINE_SHA256
    assert _sha256(BASELINE) == BASELINE_SHA256

    assert results["after_counts"]["tasha"] == {
        "authored": 106,
        "compile": 105,
        "preview": 105,
        "production": 103,
        "compile_only": 0,
    }
    assert migration["game_usable"] == 105
    assert results["after_counts"]["project"] == {
        "production": 203,
        "compile_only": 35,
        "unique_compiled": 111,
    }
    assert results["count_delta"]["tasha"]["production"] == 1
    assert results["count_delta"]["tasha"]["compile_only"] == -1
    assert results["count_delta"]["selected_atom_status"] == {
        "production_full": 1,
        "compile_only": -1,
    }

    assert RESULTS.is_file() and REPORT.is_file()
    loaded_evidence = content_ir_production_evidence.load_production_runtime_evidence(
        ROOT,
        pack_id="tashas-cauldron",
    )[FEATURE_ID]
    assert loaded_evidence["evidence_path"] == str(RESULTS.relative_to(ROOT))
    assert loaded_evidence["production_runtime_full"] is True
    assert loaded_evidence["checks"]["external_sound_typed_and_producer_bound"] is True
    assert results["evidence_by_id"][FEATURE_ID]["registry_consumers"] == results[
        "registry_consumers"
    ]
    assert report["evidence_by_id"][FEATURE_ID]["all_required_checks_passed"] is True

    assert _sha256(RESULTS) == RESULTS_SHA256
    assert _sha256(REPORT) == REPORT_SHA256


def test_round_xlii_missing_production_evidence_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    original_loader = tashas_whole_pack.load_production_runtime_evidence

    def without_round_xlii_evidence(
        repo_root: Path, **kwargs: Any
    ) -> dict[str, dict[str, Any]]:
        evidence = original_loader(repo_root, **kwargs)
        evidence.pop(FEATURE_ID, None)
        return evidence

    monkeypatch.setattr(
        tashas_whole_pack,
        "load_production_runtime_evidence",
        without_round_xlii_evidence,
    )
    monkeypatch.setattr(validator, "REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(validator, "RESULT_PATH", tmp_path / "result.json")
    monkeypatch.setattr(
        validator,
        "_run_real_e2e",
        lambda: {
            "passed": True,
            "returncode": 0,
            "pytest_summary": "",
            "warning_present": False,
        },
    )

    assert validator.main() == 1
    degraded = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert degraded["all_required_checks_passed"] is False
    assert degraded["production_runtime_full_ids"] == []
    assert degraded["compile_only_ids"] == [FEATURE_ID]
    assert degraded["checks"]["selected_atom_currently_production_full"] is False
    assert next(
        atom
        for atom in build_migration(ROOT)["atoms"]
        if atom.get("content_id") == FEATURE_ID
    )["migration_status"] == "compile_only"


def test_round_xlii_validator_subprocess_isolated_and_byte_identical(
    tmp_path: Path,
) -> None:
    outputs = []
    for index in (1, 2):
        result_path = tmp_path / f"result-{index}.json"
        report_path = tmp_path / f"report-{index}.json"
        completed = subprocess.run(
            [str(ROOT / "backend/.venv/bin/python"), str(VALIDATOR)],
            cwd=ROOT,
            env={
                **os.environ,
                "ROUND_XLII_RESULT_PATH": str(result_path),
                "ROUND_XLII_REPORT_PATH": str(report_path),
            },
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode()
        outputs.append((completed.stdout, result_path.read_bytes(), report_path.read_bytes()))

    assert outputs[0] == outputs[1]
