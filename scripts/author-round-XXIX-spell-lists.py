# ruff: noqa: N999
"""Deterministic authoring tool for the Round XXIX always-prepared spell lists."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORED_DIR = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"
)
REVIEWER = "codex-manual-review-2026-08-13-round-XXIX"
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
        "feature_id": "content.tashas-cauldron.round2.feature.wildfire-druid-circle-spells",
        "source_record_id": "92c8bd3c6a3cd622e2ec4559",
        "source_fingerprint": "a737798ee474bdac2bae8eb7c468605ada7261871bc05c3fe44090219a954ec1",
        "source_fragment": "8",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/德鲁伊（TCE）/野火结社.html",
        "subclass_name": "野火结社",
        "class_name": "德鲁伊",
        "source_name": "结社法术",
        "level": 2,
        "casting_ability": "wisdom",
        "source_class": "druid",
        "source_excerpt": (
            "*第2级野火结社特性*\n你与野火灵魄——一位兼具创生和毁灭的原初存在——之间的神秘连接业已形成。"
            "当你在此职业到达特定等级时，你与灵魄的连接将使你习得一些特定法术，就如野火结社法术列表所示。\n"
            "一旦你习得这些法术中任意一个，你就会一直准备着它，且不计入你的每日准备法术上限。"
        ),
        "spells": [
            "burning_hands",
            "cure_wounds",
            "flaming_sphere",
            "scorching_ray",
            "plant_growth",
            "revivify",
            "aura_of_life",
            "fire_shield",
            "flame_strike",
            "mass_cure_wounds",
        ],
    },
    {
        "feature_id": "content.tashas-cauldron.round2.feature.watchers-paladin-oath-spells",
        "source_record_id": "7f538e86d6af4475b48a524d",
        "source_fingerprint": "ffec72791bbcb84f31c5b7b4a73a29fa9489ef7acfd32f1d2bf94013f3b48416",
        "source_fragment": "17",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/圣武士（TCE）/守望之誓.html",
        "subclass_name": "守望之誓",
        "class_name": "圣武士",
        "source_name": "圣誓法术",
        "level": 3,
        "casting_ability": "charisma",
        "source_class": "paladin",
        "source_excerpt": (
            "*第3级守望之誓特性*\n当你的圣武士达到特定等级时，你将获得以下的圣誓法术，如守望之誓法术表所示。"
            "有关圣誓法术的规则请查阅圣武士 神圣誓言Sacred Oath 特性中记载的文本。"
        ),
        "spells": [
            "alarm",
            "detect_magic",
            "moonbeam",
            "see_invisibility",
            "counterspell",
            "nondetection",
            "aura_of_purity",
            "banishment",
            "hold_monster",
            "scrying",
        ],
    },
    {
        "feature_id": "content.tashas-cauldron.round2.feature.glory-paladin-oath-spells",
        "source_record_id": "867896faa26eb295d846a574",
        "source_fingerprint": "45fd86e477af10b4b8e6c862362d7f933b66cb490f0645941c56a15c342e9965",
        "source_fragment": "17",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/圣武士（TCE）/荣耀之誓.html",
        "subclass_name": "荣耀之誓",
        "class_name": "圣武士",
        "source_name": "圣誓法术",
        "level": 3,
        "casting_ability": "charisma",
        "source_class": "paladin",
        "source_excerpt": (
            "*第3级荣耀之誓特性*\n当你的圣武士达到特定等级时，你将获得以下的圣誓法术，如荣耀之誓法术表所示。"
            "有关圣誓法术的规则请查阅圣武士 神圣誓言Sacred Oath 特性中记载的文本。"
        ),
        "spells": [
            "guiding_bolt",
            "heroism",
            "enhance_ability",
            "magic_weapon",
            "haste",
            "protection_from_energy",
            "compulsion",
            "freedom_of_movement",
            "commune",
            "flame_strike",
        ],
    },
]


def _effects(case: dict) -> list[dict]:
    return [
        {
            "operator": "grant_spell",
            "parameters": {
                "casting_ability": case["casting_ability"],
                "grant_mode": "always_prepared",
                "source_class": case["source_class"],
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
        "class_name": case["class_name"],
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
        "level": case["level"],
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
