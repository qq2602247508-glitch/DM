# ruff: noqa: N999
"""Deterministic authoring tool for the Round XXVIII cleric Domain Spells batch.

Source text is read from the local generated-content corpus, while every
executable clause is written as authored data rather than inferred from prose
or field extraction.  The resulting JSON files are the reviewable production
assets; this script is only a deterministic rebuild tool for those assets.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORED_DIR = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"
)
REVIEWER = "codex-manual-review-2026-08-13-round-XXVIII"
COMPILER_FINGERPRINT = (
    "e6fb6a582b9f7bb302bcc26560ed68578a2155c019bde6d0009b5731c6b77e8e"
)

REVIEWED_FIELDS = [
    "feature_id",
    "source_record_id",
    "source_name",
    "source_path",
    "source_book",
    "source_fingerprint",
    "content_kind",
    "class_name",
    "subclass_name",
    "level",
    "source_completeness",
    "clauses",
    "required_inputs",
    "runtime_boundary",
]


CASES: list[dict] = [
    {
        "feature_id": "content.tashas-cauldron.round2.feature.order-cleric-domain-spells",
        "source_record_id": "38a389e4b25a6eeec6c7835f",
        "source_fingerprint": "e5689d09e7842968e4dbf8e0666d203e349ac3c2729d2e7cc0e430716e477bd8",
        "source_fragment": "20",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/牧师（TCE）/秩序领域.html",
        "subclass_name": "秩序领域",
        "source_excerpt": (
            "*第1级秩序领域特性*\n当你获得秩序领域法术表中所对应的牧师等级时，"
            "你将同时习得这些法术。查看玩家手册中的神圣领域职业特性来了解什么是领域法术。"
        ),
        "spells": [
            "command",
            "heroism",
            "hold_person",
            "zone_of_truth",
            "mass_healing_word",
            "slow",
            "compulsion",
            "locate_creature",
            "commune",
            "dominate_person",
        ],
    },
    {
        "feature_id": "content.tashas-cauldron.round2.feature.peace-cleric-domain-spells",
        "source_record_id": "790ce45021cc1901403353e1",
        "source_fingerprint": "879a912598b18c87873fcf247e3154ac8329511cc441217dd96f087fea95e0dc",
        "source_fragment": "22",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/牧师（TCE）/和平领域.html",
        "subclass_name": "和平领域",
        "source_excerpt": (
            "*第1级和平领域特性*\n当你获得和平领域法术表中所对应的牧师等级时，"
            "你将同时习得这些法术。查看玩家手册中的神圣领域职业特性来了解什么是领域法术。"
        ),
        "spells": [
            "heroism",
            "sanctuary",
            "aid",
            "warding_bond",
            "beacon_of_hope",
            "sending",
            "aura_of_purity",
            "otilukes_resilient_sphere",
            "greater_restoration",
            "rarys_telepathic_bond",
        ],
    },
    {
        "feature_id": "content.tashas-cauldron.round2.feature.twilight-cleric-domain-spells",
        "source_record_id": "63d0abe27f6ad161f0820593",
        "source_fingerprint": "89e760ab21dea53000f38c1ee48f1d8bebc4cfe943b3cde3ab3f0e2f22757b64",
        "source_fragment": "21",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/牧师（TCE）/暮光领域.html",
        "subclass_name": "暮光领域",
        "source_excerpt": (
            "*第1级暮光领域特性*\n当你获得暮光领域法术表中所对应的牧师等级时，"
            "你将同时习得这些法术。查看玩家手册中的神圣领域职业特性来了解什么是领域法术。"
        ),
        "spells": [
            "faerie_fire",
            "sleep",
            "moonbeam",
            "see_invisibility",
            "aura_of_vitality",
            "leomunds_tiny_hut",
            "aura_of_life",
            "greater_invisibility",
            "circle_of_power",
            "mislead",
        ],
    },
]


def _effects(spells: list[str]) -> list[dict]:
    return [
        {
            "operator": "grant_spell",
            "parameters": {
                "casting_ability": "wisdom",
                "grant_mode": "always_prepared",
                "source_class": "cleric",
                "spell_id": spell_id,
            },
        }
        for spell_id in spells
    ]


def _document(case: dict) -> dict:
    excerpt = case["source_excerpt"]
    clause = {
        "action_economy": "none",
        "activation": "automatic",
        "audit": {
            "reviewed_by": REVIEWER,
            "source": "authored_ir",
            "source_boundary": "always-prepared",
            "source_excerpt": excerpt,
        },
        "clause_id": "always-prepared",
        "conditions": [],
        "duration": "advancement_persistent",
        "effects": _effects(case["spells"]),
        "expiry": None,
        "frequency": None,
        "persistence": "character.feature_runtime",
        "required_inputs": [],
        "resource_costs": [],
        "resource_recovery": [],
        "stacking": None,
        "targeting": {"kind": "self", "parameters": {}},
        "trigger": "advancement_confirmed",
        "visibility": "owner",
    }
    return {
        "class_name": "牧师",
        "clause_boundaries": {
            "always-prepared": {
                "source_excerpt": excerpt,
                "source_fragment": case["source_fragment"],
            }
        },
        "clauses": [clause],
        "compatibility": {
            "runtime_source": "feature_ir",
            "source_fingerprint": case["source_fingerprint"],
        },
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "dependencies": [],
        "evidence": ["领域法术: " + excerpt],
        "feature_id": case["feature_id"],
        "kind": "feature",
        "level": 1,
        "localized_names": {"zh-CN": "领域法术"},
        "manual_decisions": {
            "isolated_runtime_only": True,
            "operator_mapping": "explicit_atom_mapping",
            "unmodeled_source_terms": [],
        },
        "namespace": "content.tashas-cauldron",
        "pack_id": "tashas-cauldron",
        "pack_version": "source-7011166c19bd",
        "review_status": "reviewed",
        "reviewed_by": REVIEWER,
        "reviewed_fields": REVIEWED_FIELDS,
        "ruleset_version": "2014",
        "schema_version": "feature-ir-1",
        "source_book": "塔莎的万事坩埚",
        "source_completeness": "complete",
        "source_evidence": {
            "source_excerpt": excerpt,
            "source_fragment": case["source_fragment"],
            "source_path": case["source_path"],
            "source_record_id": case["source_record_id"],
        },
        "source_fingerprint": case["source_fingerprint"],
        "source_name": "领域法术",
        "source_path": case["source_path"],
        "source_record_id": case["source_record_id"],
        "source_trust": "authored_ir",
        "subclass_name": case["subclass_name"],
    }


def main() -> int:
    AUTHORED_DIR.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        document = _document(case)
        slug = case["feature_id"].rsplit(".", 1)[-1]
        path = AUTHORED_DIR / f"{slug}.json"
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
