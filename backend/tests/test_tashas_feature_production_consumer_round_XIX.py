from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[2]
FEATURE_PATH = (
    ROOT
    / "data/content-ir/authored/official-packs/tashas-cauldron/features/features/"
    "content-tashas-cauldron-feature-way-of-mercy-implements-of-mercy.json"
)
SHARED_PATH = ROOT / "scripts/validate-tashas-feature-production-consumer-round-VII.py"
FEATURE_ID = "content.tashas-cauldron.feature.way-of-mercy.implements-of-mercy"


def _load_shared():
    loader = importlib.util.spec_from_file_location("round_vii_shared_for_round_xix", SHARED_PATH)
    assert loader is not None and loader.loader is not None
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def test_implements_of_mercy_runs_three_typed_proficiencies_through_character_growth(
    campaign_client,
) -> None:
    value = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE_PATH),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    assert compiled.compile_status == "full", compiled.blockers
    contract = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
    proficiencies = contract["proficiencies"]
    assert isinstance(proficiencies, list)
    assert len(proficiencies) == 3

    shared = _load_shared()
    evidence = shared._run_case(
        campaign_client,
        FEATURE_ID,
        spec,
        contract,
        {},
        1,
    )
    assert evidence["production_runtime_full"] is True
    assert evidence["preview"] is True
    assert evidence["confirm"] is True
    assert evidence["replay"] is True
    assert evidence["typed_consumer"] == "advancement_service.character_growth.v1"
    assert evidence["character_cas"] is True
    assert evidence["transaction"] is True
    assert evidence["feature_persisted"] is True
    assert evidence["proficiency_grant_count"] == 3
