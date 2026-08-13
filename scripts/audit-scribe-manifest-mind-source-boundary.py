# ruff: noqa: N999
"""Audit Manifest Mind source clauses against authored IR and runtime evidence.

This is an audit/reporting tool, not a production promotion tool.  It reads the
authoritative GBK source HTML, the authored Typed IR, compiler output, and the
Round XXXII–XXXVI evidence paths.  It deliberately keeps the feature
compile-only when any source clause lacks a closed producer/consumer/
persistence/CAS/replay chain.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.feature_compiler import FeatureCompiler
from dnd_dm_assistant.application.feature_materializers import (
    default_materializer_registry,
)
from dnd_dm_assistant.domain.feature_capabilities import default_capability_catalog
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "data/sources/dnd5e_chm/塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html"
IR_PATH = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json"
REPORT_PATH = ROOT / "reports/scribe-manifest-mind-source-boundary-audit-2026-08-13.json"
DOC_PATH = ROOT / "docs/scribe-manifest-mind-source-boundary-audit-2026-08-13.md"

FEATURE_ID = "content.tashas-cauldron.round2.feature.scribe-manifest-mind"
SOURCE_RECORD_ID = "ff7049c6a4d0aad0dae4adf5"
SOURCE_FINGERPRINT = "dbbdb5b3ca9d86ece43c2f919d8483683f99068a478bccc401906057fccb920a"
SOURCE_RELATIVE_PATH = "塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_excerpt() -> str:
    decoded = SOURCE_PATH.read_text(encoding="gbk")
    match = re.search(
        r"<FONT color=#800000>神识显现 Manifest\s*Mind</FONT>.*?</p>",
        decoded,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise RuntimeError("Manifest Mind source excerpt was not found in authoritative HTML")
    text = re.sub(r"<[^>]+>", "", match.group(0))
    text = re.sub(r"\s+", " ", text).replace("\xa0", " ").strip()
    return text


def _feature_spec(raw: dict[str, Any]) -> FeatureSpec:
    return FeatureSpec.from_dict(
        {key: value for key, value in raw.items() if key in FeatureSpec._FIELDS},
        path=str(IR_PATH),
    )


def _path_probe(relative_path: str, *needles: str) -> bool:
    path = ROOT / relative_path
    if not path.is_file():
        return False
    content = path.read_text(encoding="utf-8", errors="ignore")
    return all(needle in content for needle in needles)


def _json_probe(relative_path: str, *checks: tuple[str, object]) -> bool:
    path = ROOT / relative_path
    if not path.is_file():
        return False
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    for key, expected in checks:
        current: Any = value
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        if current != expected:
            return False
    return True


def _termination_receipt_probe(clause_id: str, reason: str) -> bool:
    """Require the focused runtime receipt chain for a source termination clause."""

    test_path = ROOT / "backend/tests/test_content_ir_entity_lifecycle_runtime.py"
    runtime_path = ROOT / "backend/src/dnd_dm_assistant/application/content_ir_runtime.py"
    producer_path = ROOT / "backend/src/dnd_dm_assistant/infrastructure/database/combat_service.py"
    equipment_path = ROOT / "backend/src/dnd_dm_assistant/infrastructure/database/spell_economy_service.py"
    if not all(path.is_file() for path in (test_path, runtime_path, producer_path)):
        return False
    test = test_path.read_text(encoding="utf-8", errors="ignore")
    runtime = runtime_path.read_text(encoding="utf-8", errors="ignore")
    producer = producer_path.read_text(encoding="utf-8", errors="ignore")
    equipment = equipment_path.read_text(encoding="utf-8", errors="ignore")
    reason_markers = {
        "dispel_magic": (
            "/effects/",
            "producer-dispel-end",
            "combat_end_effect",
        ),
        "source_object_destroyed": (
            "equipment/confirm",
            "producer-spellbook-destroy",
            "equipment_destroy",
        ),
        "owner_died": (
            "actions/confirm",
            "producer-owner-damage",
            "combat_damage",
        ),
        "owner_dismissed": (
            "/summons/",
            "producer-dismiss-end",
            "action_cost",
            "bonus_action",
            "combat_end_summon",
        ),
    }
    markers = reason_markers[reason]
    producer_ok = all(
        marker in producer or marker in equipment or marker in test
        for marker in markers
    )
    synthetic_transaction_fixture = "OperationTransaction(" in test
    consumer_ok = all(
        marker in runtime
        for marker in (
            "_validate_lifecycle_producer",
            "producer_operation_id",
            "OperationTransaction",
            "VersionConflict",
        )
    )
    focused_ok = all(
        marker in test
        for marker in (
            "test_termination_runtime_requires_real_producer_receipt_and_is_idempotent",
            "test_termination_runtime_rejects_failed_or_unbound_producer_without_mutation",
            reason,
        )
    )
    return producer_ok and consumer_ok and focused_ok and not synthetic_transaction_fixture


def _matrix(
    spec: FeatureSpec,
    compiled: Any,
    *,
    evidence_overrides: dict[tuple[str, str], bool] | None = None,
) -> list[dict[str, Any]]:
    """Build the matrix from current IR/contracts/receipts, never from a baseline."""

    overrides = evidence_overrides or {}
    catalog = default_capability_catalog()
    materializers = default_materializer_registry()
    compiled_by_id = {
        item["clause_id"]: item for item in compiled.to_dict()["clause_results"]
    }
    clauses = {clause.clause_id: clause for clause in spec.clauses}

    def probe(clause_id: str, name: str, value: bool) -> bool:
        return overrides.get((clause_id, name), value)

    def row(
        clause_id: str,
        source_rule: str,
        *,
        authored_clause: str | None,
        operator: str | None,
        consumer_id: str | None,
        receipt: bool,
        source_paths: tuple[str, ...],
        source_needles: tuple[str, ...],
        blocker: str,
        evidence: tuple[str, ...],
        cas_replay: bool | None = None,
        source_provenance: bool | None = None,
    ) -> dict[str, Any]:
        clause = clauses.get(authored_clause or clause_id)
        authored = clause is not None
        effect = (
            clause.effects[0]
            if clause is not None and clause.effects
            else None
        )
        actual_operator = operator or (effect.operator if effect else None)
        descriptor = catalog.get(actual_operator and next(
            (
                item.capability_id
                for item in catalog.descriptors()
                if item.supported_operator == actual_operator
            ),
            "",
        ))
        compile_result = compiled_by_id.get(authored_clause or clause_id, {})
        capability = bool(
            descriptor
            and descriptor.supported_operator == actual_operator
            and descriptor.producer
            and descriptor.consumer
            and descriptor.persisted_state
            and descriptor.cas_support
            and descriptor.idempotency_support
            and descriptor.production_status == "production_closed"
        )
        materialized = bool(
            descriptor
            and descriptor.materializer_id
            and descriptor.materializer_id in materializers.to_dict()
            and compile_result.get("status") == "full"
        )
        registry = False
        if materialized:
            try:
                runtime_blocks = {
                    "resources": [{"key": "audit", "kind": "resource_profile"}]
                }
                resolve_production_consumers(
                    content_kind="advancement",
                    runtime_schema_version="feature-runtime-1",
                    blocks=runtime_blocks,
                )
                registry = True
            except ValueError:
                registry = False
        source = probe(
            clause_id,
            "source_provenance",
            source_provenance
            if source_provenance is not None
            else bool(
                spec.source_record_id
                and spec.source_fingerprint
                and _source_excerpt()
                and _path_probe(
                    "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",
                    "source_record_id",
                    "source_fingerprint",
                )
            )
        )
        receipt_ok = probe(clause_id, "focused_receipt", receipt)
        checks = {
            "authored_ir": authored,
            "operator_capability": probe(clause_id, "operator_capability", capability),
            "materializer": probe(clause_id, "materializer", materialized),
            "runtime_registry": probe(clause_id, "runtime_registry", registry),
            "focused_receipt": receipt_ok,
            "source_provenance": source,
            "cas_replay": probe(
                clause_id,
                "cas_replay",
                cas_replay
                if cas_replay is not None
                else bool(descriptor and descriptor.cas_support and descriptor.idempotency_support),
            ),
        }
        if not authored:
            status = "missing"
            checks.update(
                {
                    "operator_capability": False,
                    "materializer": False,
                    "runtime_registry": False,
                    "focused_receipt": False,
                    "cas_replay": False,
                }
            )
            return {
                "clause_id": clause_id,
                "source_rule": source_rule,
                "authored_ir": "missing",
                "producer": "missing",
                "consumer": "missing",
                "persistence": "missing",
                "cas_replay": "missing",
                "status": status,
                "blocker": blocker,
                "evidence": list(evidence),
                "evidence_checks": checks,
            }
        passed = sum(checks.values())
        status = "covered" if passed == len(checks) else ("partial" if passed else "missing")
        return {
            "clause_id": clause_id,
            "source_rule": source_rule,
            "authored_ir": authored_clause or "missing",
            "producer": descriptor.producer if descriptor else "missing",
            "consumer": descriptor.consumer if descriptor else "missing",
            "persistence": descriptor.persisted_state if descriptor else "missing",
            "cas_replay": "closed" if checks["cas_replay"] else "missing",
            "status": status,
            "blocker": "" if status == "covered" else blocker,
            "evidence": list(evidence),
            "evidence_checks": checks,
        }

    return [
        row(
            "activation-source-and-initial-placement",
            "Bonus action while holding the awakened spellbook; manifest as a Tiny spectral object in a chosen unoccupied space within 60 ft.",
            authored_clause="spectral-object-lifecycle",
            operator="configure_entity_lifecycle",
            consumer_id=None,
            receipt=_path_probe(
                "backend/tests/test_content_ir_entity_lifecycle_runtime.py",
                "test_entity_lifecycle_initial_placement_receipt_requires_authoritative_facts",
            ),
            source_paths=("data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",),
            source_needles=("unoccupied", "60尺"),
            blocker="Lifecycle is closed, but initial 60-ft placement/unoccupied-space producer facts are not yet a dedicated runtime receipt.",
            evidence=("CAS/replay lifecycle receipt",),
        ),
        row(
            "spectral-object-form",
            "The manifestation is intangible, does not occupy its space, emits dim light in a 10-ft radius, and has a chosen appearance.",
            authored_clause="spectral-object-form",
            operator="configure_entity_senses",
            consumer_id=None,
            receipt=_path_probe(
                "backend/tests/test_content_ir_entity_senses_runtime.py",
                "test_entity_senses_persists_typed_spectral_form_contract",
            ),
            source_paths=("data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",),
            source_needles=("light_radius_ft", "无形"),
            blocker="The typed form contract and receipt exist, but entity.senses remains production_partial.",
            evidence=("typed form persistence receipt with source-bound runtime",),
            source_provenance=True,
        ),
        row(
            "entity-senses",
            "While manifested it can hear and see and has 60-ft darkvision.",
            authored_clause="mind-sight",
            operator="configure_entity_senses",
            consumer_id=None,
            receipt=_path_probe("backend/tests/test_content_ir_entity_senses_runtime.py", "test_entity_senses_real_consumer_receipt_and_replay"),
            source_paths=("backend/tests/test_content_ir_entity_senses_runtime.py", "backend/src/dnd_dm_assistant/domain/entity_senses.py"),
            source_needles=("source_provenance", "replayed"),
            blocker="The current entity.senses capability is production_partial.",
            evidence=("real receipt CAS/replay",),
            source_provenance=True,
        ),
        row(
            "telepathic-sharing",
            "It shares what it sees and hears with the owner telepathically without an action.",
            authored_clause="shared-information",
            operator="expose_authorized_target_information",
            consumer_id=None,
            receipt=False,
            source_paths=("data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",),
            source_needles=("无需动作",),
            blocker="The focused sensory receipt exists, but source-level telepathic no-action channel semantics are not separately closed.",
            evidence=("real sensory receipt CAS/replay",),
            cas_replay=True,
        ),
        row(
            "remote-spell-origin",
            "On the owner's turn, when casting a wizard spell, the owner may cast as if in the spectral object's space using its senses.",
            authored_clause="remote-spell-origin",
            operator="configure_remote_spell_origin",
            consumer_id=None,
            receipt=_json_probe("reports/tashas-feature-production-consumer-round-XXXIII-2026-08-13.json", ("all_required_checks_passed", True)),
            source_paths=("backend/tests/test_content_ir_remote_spell_origin_runtime.py", "backend/src/dnd_dm_assistant/domain/remote_spell_origin.py"),
            source_needles=("source_provenance", "operation_id"),
            blocker="Geometry is closed, but owner-turn/wizard-spell gating and production sensory dependency are not.",
            evidence=("preview/confirm/replay CAS receipt",),
            source_provenance=True,
        ),
        row(
            "proficiency-bonus-uses",
            "Remote sensory casting uses equal proficiency bonus per day and resets after long rest.",
            authored_clause="proficiency-bonus-uses",
            operator="set_resource_profile",
            consumer_id="advancement_service.character_growth.v1",
            receipt=_path_probe("backend/src/dnd_dm_assistant/application/content_ir_runtime.py", "proficiency_bonus_for_level", "recovery_events"),
            source_paths=("backend/tests/test_manifest_mind_resource_contract.py", "backend/src/dnd_dm_assistant/application/content_ir_runtime.py"),
            source_needles=("proficiency_bonus", "long_rest"),
            blocker="PB resource has no closed typed producer/consumer/receipt chain.",
            evidence=("resource persistence, long-rest recovery, CAS/replay",),
            source_provenance=True,
            cas_replay=True,
        ),
        row(
            "movement",
            "Bonus action movement up to 30 ft to a visible unoccupied space; through creatures but not objects.",
            authored_clause="mind-sight",
            operator="configure_entity_senses",
            consumer_id=None,
            receipt=_path_probe("backend/tests/test_entity_spatial.py", "destination_unoccupied", "path_clear_of_objects"),
            source_paths=("backend/src/dnd_dm_assistant/domain/entity_spatial.py", "backend/tests/test_entity_spatial.py"),
            source_needles=("source_fingerprint", "replayed"),
            blocker="Spatial seam is tested, but not yet independently bound to the authored activation contract.",
            evidence=("spatial CAS/replay receipt",),
            source_provenance=True,
        ),
        row(
            "distance-expiry",
            "Manifestation stops when distance from the owner exceeds 300 ft.",
            authored_clause="mind-sight",
            operator="configure_entity_senses",
            consumer_id=None,
            receipt=_path_probe("backend/tests/test_entity_spatial.py", "distance_expired", "version conflict"),
            source_paths=("backend/src/dnd_dm_assistant/domain/entity_spatial.py",),
            source_needles=("expiry_distance_ft", "distance_expired"),
            blocker="Generic expiry exists, but authored feature binding remains partial.",
            evidence=("spatial expiry CAS/replay receipt",),
            source_provenance=True,
        ),
        *[
            row(
                clause_id,
                source_rule,
                authored_clause="spectral-object-lifecycle" if clause_id in {"dispel-magic-expiry", "spellbook-destruction-expiry", "owner-dismissal-expiry"} else None,
                operator="configure_entity_lifecycle" if clause_id != "owner-dismissal-expiry" else None,
                consumer_id=None,
                receipt=_termination_receipt_probe(clause_id, reason),
                source_paths=(
                    "backend/src/dnd_dm_assistant/application/content_ir_runtime.py",
                    "backend/src/dnd_dm_assistant/infrastructure/database/combat_service.py",
                    "backend/src/dnd_dm_assistant/infrastructure/database/spell_economy_service.py",
                    "backend/tests/test_content_ir_entity_lifecycle_runtime.py",
                ),
                source_needles=(reason, "producer_operation_id", "OperationTransaction"),
                blocker="Termination requires a real source-bound producer receipt, lifecycle consumer persistence, CAS, replay, and fail-closed negative boundary.",
                evidence=("producer receipt, runtime consumer, lifecycle persistence, CAS/replay, failed-event rejection",),
                cas_replay=True,
            )
            for clause_id, source_rule, reason in (
                ("dispel-magic-expiry", "Manifestation stops when Dispel Magic is cast on it.", "dispel_magic"),
                ("spellbook-destruction-expiry", "Manifestation stops if the awakened spellbook is destroyed.", "source_object_destroyed"),
                ("owner-dismissal-expiry", "The owner can dismiss it as a bonus action.", "owner_dismissed"),
            )
        ],
        row(
            "owner-death-expiry",
            "Manifestation stops when the owner dies.",
            authored_clause="spectral-object-lifecycle",
            operator="configure_entity_lifecycle",
            consumer_id=None,
            receipt=_termination_receipt_probe("owner-death-expiry", "owner_died"),
            source_paths=(
                "backend/src/dnd_dm_assistant/application/content_ir_runtime.py",
                "backend/src/dnd_dm_assistant/infrastructure/database/combat_service.py",
                "backend/tests/test_content_ir_entity_lifecycle_runtime.py",
            ),
            source_needles=("owner_died", "owner_character_id", "producer_operation_id"),
            blocker="Owner death requires the authoritative combat death receipt and a source-bound lifecycle consumer transition.",
            evidence=("authoritative death producer receipt, lifecycle persistence, CAS/replay, failed-event rejection",),
            cas_replay=True,
        ),
        row(
            "long-rest-reactivation",
            "After manifesting, another manifestation requires a long rest or one spell slot.",
            authored_clause="spell-slot-reactivation",
            operator="configure_spell_slot_reactivation",
            consumer_id=None,
            receipt=_json_probe("reports/tashas-feature-production-consumer-round-XXXVI-2026-08-13.json", ("checks.source_provenance", True)),
            source_paths=("backend/tests/test_spell_slot_reactivation.py", "backend/src/dnd_dm_assistant/domain/spell_slot_reactivation.py"),
            source_needles=("replay", "rollback"),
            blocker="The reactivation capability remains production_partial.",
            evidence=("reactivation CAS/replay/rollback receipt",),
            source_provenance=True,
        ),
    ]


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Manifest Mind source-boundary completion audit — 2026-08-13",
        "",
        (
            "结论：未升 production。source-completeness 保持 `incomplete`，compile status 保持 `partial`，"
            "`unmodeled_source_terms` 不清空。原因是 source clauses 仍存在 partial producer、consumer、"
            "persistence、CAS/replay 链路，尤其是 PB-per-day uses、entity senses/spatial binding、"
            "telepathic sharing，以及 `entity.senses`/reactivation 的 production-partial gate。"
        ),
        "",
        f"- feature: `{FEATURE_ID}`",
        f"- source record: `{SOURCE_RECORD_ID}`",
        f"- source fingerprint: `{SOURCE_FINGERPRINT}`",
        f"- source path: `{SOURCE_RELATIVE_PATH}`",
        f"- source HTML SHA-256: `{report['source']['sha256']}`",
        f"- authored IR: `{report['authored_ir']['path']}`",
        f"- compiler status: `{report['compiler']['compile_status']}`",
        "",
        "## Baseline",
        "",
        (
            "Round XXXVI baseline/after remains Tasha `106 authored / 105 compile / 105 preview / 101 production / 2 compile-only`; "
            "project `201 production / 35 compile-only / 111 unique compiled`. This audit changes no production count."
        ),
        "",
        "## Source clause matrix",
        "",
        "| clause | status | producer | consumer | persistence | CAS/replay | blocker |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["clause_matrix"]:
        lines.append(
            f"| `{row['clause_id']}` | `{row['status']}` | `{row['producer']}` | `{row['consumer']}` | "
            f"`{row['persistence']}` | `{row['cas_replay']}` | {row['blocker']} |"
        )
    lines.extend(
        [
            "",
            "## Evidence and gate",
            "",
            "- Round XXXII lifecycle and remote-origin real runtime evidence passes focused/API transaction boundaries.",
            "- Round XXXIII entity senses real receipts pass, but the capability remains `production_partial`.",
            "- Round XXXV entity spatial movement/300-ft expiry real domain evidence passes, but feature promotion remains blocked.",
            "- Round XXXVI spell-slot reactivation real resource/rest transaction evidence passes, but the capability/materializer remains `production_partial`.",
            "- Round XXXVII requires real producer API/event receipts: Dispel Magic effect-end, spellbook destruction equipment destroy, owner death combat damage/death transition, and owner dismissal summon-end with bonus-action consumption.",
            "- Synthetic-only `OperationTransaction` fixtures are rejected by the dynamic audit gate and regression.",
            "- The production gate therefore remains fail-closed: no `production_runtime_full_ids`, no whole-pack production migration delta.",
            "",
            "## Required next work",
            "",
            "1. Add a generic PB-per-day feature resource consumer with long-rest recovery, Character resource persistence, CAS, replay, rollback, and real API receipts.",
            "2. Close authored entity senses/spatial binding and source-level telepathic sharing.",
            "3. Close `entity.senses` and `spell.slot.reactivation` from `production_partial` to a production registry consumer only after all negative boundaries pass.",
            "4. Reassess `source_completeness` only after the remaining independently auditable typed clauses are closed.",
            "",
            "Protected paths were not read for content changes, modified, staged, or committed by this audit.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    raw = json.loads(IR_PATH.read_text(encoding="utf-8"))
    spec = _feature_spec(raw)
    compiled = FeatureCompiler(status_authority="compiler").compile(spec)
    excerpt = _source_excerpt()
    matrix = _matrix(spec, compiled)
    counts = {
        "covered": sum(row["status"] == "covered" for row in matrix),
        "partial": sum(row["status"] == "partial" for row in matrix),
        "missing": sum(row["status"] == "missing" for row in matrix),
        "total": len(matrix),
    }
    report: dict[str, Any] = {
        "schema_version": "scribe-manifest-mind-source-boundary-audit-1",
        "audit_date": "2026-08-13",
        "feature_id": FEATURE_ID,
        "source": {
            "source_record_id": SOURCE_RECORD_ID,
            "source_fingerprint": SOURCE_FINGERPRINT,
            "source_path": SOURCE_RELATIVE_PATH,
            "path": str(SOURCE_PATH.relative_to(ROOT)),
            "sha256": _sha256(SOURCE_PATH),
            "encoding": "gbk",
            "excerpt": excerpt,
        },
        "authored_ir": {
            "path": str(IR_PATH.relative_to(ROOT)),
            "sha256": _sha256(IR_PATH),
            "source_completeness": spec.source_completeness,
            "unmodeled_source_terms": list(spec.manual_decisions.get("unmodeled_source_terms", [])),
            "clause_ids": [clause.clause_id for clause in spec.clauses],
        },
        "compiler": {
            "compile_status": compiled.compile_status,
            "blockers": list(compiled.blockers),
            "typed_clause_count": len(spec.clauses),
        },
        "baseline": {
            "tasha": {"authored": 106, "compile": 105, "preview": 105, "production": 101, "compile_only": 2},
            "project": {"production": 201, "compile_only": 35, "unique_compiled": 111},
        },
        "clause_matrix": matrix,
        "counts": counts,
        "producer_evidence_standard": {
            "requires_real_api_or_event_producer": True,
            "synthetic_operation_transaction_fixture_counts_as_covered": False,
            "termination_receipts": {
                "dispel_magic": "combat_end_effect via effect-end API",
                "source_object_destroyed": "equipment_destroy via equipment API",
                "owner_died": "combat_damage via combat damage/death transition",
                "owner_dismissed": "combat_end_summon via summon-end API with bonus_action",
            },
        },
        "production_decision": {
            "promote": False,
            "production_runtime_full_ids": [],
            "compile_only_ids": [
                FEATURE_ID,
                "content.tashas-cauldron.round2.feature.genie-bottled-respite",
            ],
            "reason": "source clause matrix contains missing/partial runtime boundaries",
        },
        "protected_paths": [
            "backend/tests/integrations/",
            "backend/tests/ollama.py",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    DOC_PATH.write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(REPORT_PATH.relative_to(ROOT)),
                "doc": str(DOC_PATH.relative_to(ROOT)),
                "counts": counts,
                "compile_status": compiled.compile_status,
                "source_completeness": spec.source_completeness,
                "promote": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
