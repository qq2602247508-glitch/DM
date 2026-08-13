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

from dnd_dm_assistant.application.feature_compiler import FeatureCompiler
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


def _evidence(*paths: str) -> list[str]:
    return list(paths)


def _matrix() -> list[dict[str, Any]]:
    return [
        {
            "clause_id": "activation-source-and-initial-placement",
            "source_rule": "Bonus action while holding the awakened spellbook; manifest as a Tiny spectral object in a chosen unoccupied space within 60 ft.",
            "authored_ir": "spectral-object-lifecycle",
            "producer": "configure_entity_lifecycle",
            "consumer": "ContentIRRuntimeService advancement lifecycle consumer",
            "persistence": "Character.features[*].runtime.entity_lifecycles",
            "cas_replay": "OperationTransaction + character version CAS + operation replay",
            "status": "partial",
            "blocker": "The generic lifecycle stores lifecycle state but does not author/consume the 60-ft placement and unoccupied-space facts as this source clause.",
            "evidence": _evidence(
                "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",
                "backend/src/dnd_dm_assistant/domain/entity_lifecycle.py",
                "backend/src/dnd_dm_assistant/application/content_ir_runtime.py",
                "backend/tests/test_content_ir_entity_lifecycle_runtime.py",
            ),
        },
        {
            "clause_id": "spectral-object-form",
            "source_rule": "The manifestation is intangible, does not occupy its space, emits dim light in a 10-ft radius, and has a chosen appearance.",
            "authored_ir": "mind-sight (light_radius_ft only)",
            "producer": "configure_entity_senses",
            "consumer": "entity.senses materializer / sensory resolver",
            "persistence": "entity_senses runtime block",
            "cas_replay": "Generic feature runtime transaction boundary",
            "status": "partial",
            "blocker": "Intangible/non-occupying form and appearance choice have no typed producer, consumer, or persisted state; only light_radius_ft is represented.",
            "evidence": _evidence(
                "data/sources/dnd5e_chm/塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html",
                "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",
                "backend/src/dnd_dm_assistant/application/feature_materializers.py",
            ),
        },
        {
            "clause_id": "entity-senses",
            "source_rule": "While manifested it can hear and see and has 60-ft darkvision.",
            "authored_ir": "mind-sight",
            "producer": "configure_entity_senses",
            "consumer": "entity_sensory_profile_service / resolve_entity_senses",
            "persistence": "Character.features[*].runtime.entity_senses",
            "cas_replay": "Real runtime receipt has OperationTransaction + actor CAS + replay",
            "status": "partial",
            "blocker": "The capability and runtime consumer are explicitly production_partial; no production registry closure.",
            "evidence": _evidence(
                "backend/src/dnd_dm_assistant/domain/entity_senses.py",
                "backend/src/dnd_dm_assistant/application/content_ir_runtime.py",
                "backend/tests/test_content_ir_entity_senses_runtime.py",
                "scripts/validate-tashas-feature-production-consumer-round-XXXIII.py",
            ),
        },
        {
            "clause_id": "telepathic-sharing",
            "source_rule": "It shares what it sees and hears with the owner telepathically without an action.",
            "authored_ir": "shared-information",
            "producer": "expose_authorized_target_information",
            "consumer": "manifest-mind sensory information runtime path",
            "persistence": "Source-bound entity_senses/lifecycle snapshot",
            "cas_replay": "Preview/confirm/replay and actor CAS evidence exists",
            "status": "partial",
            "blocker": "Information resolution depends on the partial entity.senses capability; source-level no-action telepathy and complete channel semantics are not production-closed.",
            "evidence": _evidence(
                "backend/src/dnd_dm_assistant/application/feature_materializers.py",
                "backend/src/dnd_dm_assistant/application/content_ir_runtime.py",
                "backend/tests/test_content_ir_entity_senses_runtime.py",
                "backend/tests/test_tashas_feature_production_consumer_round_XXXIII.py",
            ),
        },
        {
            "clause_id": "remote-spell-origin",
            "source_rule": "On the owner's turn, when casting a wizard spell, the owner may cast as if in the spectral object's space using its senses.",
            "authored_ir": "remote-spell-origin",
            "producer": "configure_remote_spell_origin",
            "consumer": "remote.spell.origin.v1 spell runtime",
            "persistence": "Character feature runtime origin/lifecycle snapshot",
            "cas_replay": "Preview/confirm/replay, target authorization, CAS and OperationTransaction",
            "status": "partial",
            "blocker": "Origin geometry is closed, but the source's owner-turn/wizard-spell gating and dependency on a production-closed sensory profile are not fully closed.",
            "evidence": _evidence(
                "backend/src/dnd_dm_assistant/domain/remote_spell_origin.py",
                "backend/src/dnd_dm_assistant/application/content_ir_runtime.py",
                "backend/tests/test_content_ir_entity_senses_runtime.py",
                "docs/entity-lifecycle-contract-round-XXXII-2026-08-13.md",
            ),
        },
        {
            "clause_id": "proficiency-bonus-uses",
            "source_rule": "The remote sensory casting permission can be used a number of times per day equal to proficiency bonus and all uses return after a long rest.",
            "authored_ir": "missing",
            "producer": "missing",
            "consumer": "missing",
            "persistence": "missing",
            "cas_replay": "missing",
            "status": "missing",
            "blocker": "No typed resource clause, producer, consumer, long-rest recovery, transaction, CAS, or replay evidence exists for the PB-per-day limit.",
            "evidence": _evidence(
                "data/sources/dnd5e_chm/塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html",
                "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",
            ),
        },
        {
            "clause_id": "movement",
            "source_rule": "Bonus action movement up to 30 ft to a space the owner or object can see, unoccupied; it passes through creatures but not objects.",
            "authored_ir": "mind-sight.spatial",
            "producer": "entity.spatial.v1 movement producer",
            "consumer": "entity spatial runtime",
            "persistence": "entity lifecycle spatial state",
            "cas_replay": "Expected-version CAS + operation replay + rollback evidence",
            "status": "partial",
            "blocker": "The generic spatial seam is tested, but the authored feature remains partial and the source clause is nested under a senses operator rather than independently typed.",
            "evidence": _evidence(
                "backend/src/dnd_dm_assistant/domain/entity_spatial.py",
                "backend/tests/test_entity_spatial.py",
                "scripts/validate-tashas-feature-production-consumer-round-XXXV.py",
            ),
        },
        {
            "clause_id": "distance-expiry",
            "source_rule": "Manifestation stops when distance from the owner exceeds 300 ft.",
            "authored_ir": "mind-sight.spatial.expiry_distance_ft=300",
            "producer": "entity.spatial.v1 expiry producer",
            "consumer": "entity lifecycle expiry transition",
            "persistence": "entity lifecycle status",
            "cas_replay": "CAS/replay evidence exists",
            "status": "partial",
            "blocker": "Generic expiry is implemented, but the feature cannot promote while the complete sensory/runtime boundary remains partial.",
            "evidence": _evidence(
                "backend/src/dnd_dm_assistant/domain/entity_spatial.py",
                "backend/src/dnd_dm_assistant/domain/entity_lifecycle.py",
                "backend/tests/test_entity_spatial.py",
                "scripts/validate-tashas-feature-production-consumer-round-XXXV.py",
            ),
        },
        {
            "clause_id": "dispel-magic-expiry",
            "source_rule": "Manifestation stops when someone casts Dispel Magic on it.",
            "authored_ir": "missing",
            "producer": "missing",
            "consumer": "missing",
            "persistence": "missing",
            "cas_replay": "missing",
            "status": "missing",
            "blocker": "No typed dispel event, authorization/effect resolution, persistence, CAS, or replay evidence is present.",
            "evidence": _evidence(
                "data/sources/dnd5e_chm/塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html",
                "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",
            ),
        },
        {
            "clause_id": "spellbook-destruction-expiry",
            "source_rule": "Manifestation stops if the awakened spellbook is destroyed.",
            "authored_ir": "missing",
            "producer": "missing",
            "consumer": "missing",
            "persistence": "missing",
            "cas_replay": "missing",
            "status": "missing",
            "blocker": "No spellbook entity/effect destruction event or lifecycle consumer is authored.",
            "evidence": _evidence(
                "data/sources/dnd5e_chm/塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html",
                "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",
            ),
        },
        {
            "clause_id": "owner-death-expiry",
            "source_rule": "Manifestation stops when the owner dies.",
            "authored_ir": "spectral-object-lifecycle.expires_on_owner_death=true",
            "producer": "configure_entity_lifecycle",
            "consumer": "entity lifecycle expiry transition",
            "persistence": "entity lifecycle state",
            "cas_replay": "Lifecycle CAS/replay evidence",
            "status": "covered",
            "blocker": "",
            "evidence": _evidence(
                "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",
                "backend/src/dnd_dm_assistant/domain/entity_lifecycle.py",
                "backend/tests/test_content_ir_entity_lifecycle_runtime.py",
            ),
        },
        {
            "clause_id": "owner-dismissal-expiry",
            "source_rule": "The owner can dismiss it as a bonus action.",
            "authored_ir": "missing",
            "producer": "missing",
            "consumer": "missing",
            "persistence": "missing",
            "cas_replay": "missing",
            "status": "missing",
            "blocker": "No authored dismiss event/action or runtime receipt is present.",
            "evidence": _evidence(
                "data/sources/dnd5e_chm/塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html",
                "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json",
            ),
        },
        {
            "clause_id": "long-rest-reactivation",
            "source_rule": "After manifesting, another manifestation requires a long rest or one spell slot of any level.",
            "authored_ir": "spell-slot-reactivation",
            "producer": "configure_spell_slot_reactivation",
            "consumer": "spell.slot.reactivation.v1",
            "persistence": "Character feature runtime + Character.resources",
            "cas_replay": "OperationTransaction + character CAS + replay/rollback",
            "status": "partial",
            "blocker": "The real receipt seam exists, but the materializer/capability is explicitly production_partial and not in the production registry.",
            "evidence": _evidence(
                "backend/src/dnd_dm_assistant/domain/spell_slot_reactivation.py",
                "backend/src/dnd_dm_assistant/application/content_ir_runtime.py",
                "backend/tests/test_content_ir_spell_slot_reactivation_runtime.py",
                "scripts/validate-tashas-feature-production-consumer-round-XXXVI.py",
            ),
        },
    ]


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Manifest Mind source-boundary completion audit — 2026-08-13",
        "",
        "结论：未升 production。source-completeness 保持 `incomplete`，compile status 保持 `partial`，"
        "`unmodeled_source_terms` 不清空。原因是 source clauses 仍存在 missing/partial producer、consumer、"
        "persistence、CAS/replay 链路，尤其是 PB-per-day uses、Dispel Magic、spellbook destruction、"
        "owner dismissal，以及 `entity.senses`/reactivation 的 production-partial gate。",
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
        "Round XXXVI baseline/after remains Tasha `106 authored / 105 compile / 105 preview / 101 production / 2 compile-only`; "
        "project `201 production / 35 compile-only / 111 unique compiled`. This audit changes no production count.",
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
            "- The production gate therefore remains fail-closed: no `production_runtime_full_ids`, no whole-pack production migration delta.",
            "",
            "## Required next work",
            "",
            "1. Add a generic PB-per-day feature resource consumer with long-rest recovery, Character resource persistence, CAS, replay, rollback, and real API receipts.",
            "2. Add generic lifecycle termination events for Dispel Magic, bound source-object destruction, and owner bonus-action dismissal.",
            "3. Close `entity.senses` and `spell.slot.reactivation` from `production_partial` to a production registry consumer only after all negative boundaries pass.",
            "4. Split the authored IR into independently auditable typed clauses for placement/form, sensory sharing, owner-turn wizard-spell gating, and termination events; only then reassess `source_completeness`.",
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
    matrix = _matrix()
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
