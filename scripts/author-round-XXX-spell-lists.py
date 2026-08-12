# ruff: noqa: N999
"""Deterministic authoring tool for the Round XXX artificer spell lists."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORED_DIR = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"
)
REVIEWER = "codex-manual-review-2026-08-13-round-XXX"
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
        "feature_id": "content.tashas-cauldron.round2.feature.battle-smith-spell-list",
        "source_record_id": "606d89f6e0ea3b2e0194f24c",
        "source_fingerprint": "11e6ee92ae2a0796271caaefa82befb2e7513731873cbc97c2fdd2128b42364b",
        "source_fragment": "13",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/奇械师/战地匠师.html",
        "subclass_name": "战地匠师",
        "source_name": "战地匠师法术",
        "source_excerpt": (
            "*第3级战地匠师特性*\n只要你达到相应的职业等级，战地匠师法术表格中的法术总是被视为已准备。"
            "这些法术对你来说是奇械师法术，且不会计入你可以准备法术的总数。"
        ),
        "spells": [
            "heroism",
            "shield",
            "branding_smite",
            "warding_bond",
            "aura_of_vitality",
            "conjure_barrage",
            "aura_of_purity",
            "fire_shield",
            "banishing_smite",
            "mass_cure_wounds",
        ],
    },
    {
        "feature_id": "content.tashas-cauldron.round2.feature.armorer-spell-list",
        "source_record_id": "cf864e58ba0d62c93110f5c6",
        "source_fingerprint": "1b57b10d47a01c1782ed672fc58392d14ea400d983cb2f2d0f029c4b2de905ab",
        "source_fragment": "12",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/奇械师/装甲师.html",
        "subclass_name": "装甲师",
        "source_name": "装甲师法术",
        "source_excerpt": (
            "*第3级装甲师特性*\n只要你达到相应的职业等级，装甲师法术表格中的法术总是被视为已准备。"
            "这些法术对你来说是奇械师法术，且不会计入你可以准备法术的总数。"
        ),
        "spells": [
            "magic_missile",
            "thunderwave",
            "mirror_image",
            "shatter",
            "hypnotic_pattern",
            "lightning_bolt",
            "fire_shield",
            "greater_invisibility",
            "passwall",
            "wall_of_force",
        ],
    },
    {
        "feature_id": "content.tashas-cauldron.round2.feature.artillerist-spell-list",
        "source_record_id": "fbf8451f879a169fb17a01e9",
        "source_fingerprint": "ad6e67b1ee27604cc2ffb41d3ac68ccbcc4a74362e25255c8f5b797f4916988a",
        "source_fragment": "12",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/奇械师/魔炮师.html",
        "subclass_name": "魔炮师",
        "source_name": "魔炮师法术",
        "source_excerpt": (
            "*第3级魔炮师特性*\n只要你达到相应的职业等级，魔炮师法术表格中的法术总是被视为已准备。"
            "这些法术对你来说是奇械师法术，且不会计入你可以准备法术的总数。"
        ),
        "spells": [
            "shield",
            "thunderwave",
            "scorching_ray",
            "shatter",
            "fireball",
            "wind_wall",
            "ice_storm",
            "wall_of_fire",
            "cone_of_cold",
            "wall_of_force",
        ],
    },
]


def _effects(case: dict) -> list[dict]:
    return [
        {
            "operator": "grant_spell",
            "parameters": {
                "casting_ability": "intelligence",
                "grant_mode": "always_prepared",
                "source_class": "artificer",
                "spell_id": spell_id,
            },
        }
        for spell_id in case["spells"]
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
        "effects": _effects(case),
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
        "class_name": "奇械师",
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
        "evidence": [f"{case['source_name']}: " + excerpt],
        "feature_id": case["feature_id"],
        "kind": "feature",
        "level": 3,
        "localized_names": {"zh-CN": case["source_name"]},
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
        "source_name": case["source_name"],
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
