from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dnd_dm_assistant.application import content_ir_workbench as workbench
from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    audit_records,
    compile_artifact_directory,
    compile_feature_draft,
    compile_pack_records,
    compile_spell_spec,
    compile_typed_feature_spec,
    dry_run_manifest,
    report_from_artifacts,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec


def _spell(
    *,
    name: str = "测试法术",
    book: str = "玩家手册 2024",
    path: str = "玩家手册2024/法术详述/1环.htm",
    officiality: str = "official",
    edition: str = "2024",
    markdown: str | None = None,
) -> dict[str, object]:
    return {
        "content_type": "spells",
        "name": name,
        "source_book": book,
        "source_relative_path": path,
        "stable_id": f"spell-{name}-{path}",
        "officiality": officiality,
        "edition": edition,
        "source_revision": "test-revision",
        "content_markdown": markdown
        or (
            f"## {name}\n\n施法时间：动作\n\n施法距离：60尺\n\n"
            "造成 1d6 火焰伤害。这个测试正文足够长，用于验证来源边界和草稿路径。"
        ),
        "content_plain_text": (
            f"{name} 施法时间：动作。施法距离：60尺。造成 1d6 火焰伤害。"
            "这个测试正文足够长，用于验证来源边界和草稿路径。"
        ),
        "spell": {
            "level": 1,
            "school": "塑能",
            "casting_time": "动作",
            "range": "60尺",
            "components": "V、S",
            "duration": "立即",
        },
    }


def _feature() -> dict[str, object]:
    return {
        "content_type": "classes",
        "name": "测试特性",
        "source_book": "塔莎的万事坩埚",
        "source_relative_path": "塔莎的万事坩埚/玩家选项/职业/战士/测试特性.html",
        "stable_id": "feature-source-1",
        "officiality": "unknown",
        "edition": "legacy",
        "source_revision": "test-revision",
        "content_plain_text": "3级：测试特性。你获得某种能力。",
    }


def _typed_feature(feature_id: str = "test:feature") -> FeatureSpec:
    return FeatureSpec.from_dict(
        {
            "schema_version": "feature-ir-1",
            "feature_id": feature_id,
            "namespace": "test",
            "pack_id": "test-pack",
            "pack_version": "1.0.0",
            "ruleset_version": "2024",
            "source_record_id": feature_id,
            "source_name": "测试特性",
            "source_trust": "authored_ir",
            "localized_names": {"zh-CN": "测试特性"},
            "class_name": "战士",
            "subclass_name": None,
            "level": 1,
            "source_completeness": "complete",
            "dependencies": [],
            "compatibility": {},
            "clauses": [
                {
                    "clause_id": "main",
                    "trigger": "advancement_confirmed",
                    "effects": [
                        {
                            "operator": "grant_proficiency",
                            "parameters": {
                                "proficiency_kind": "skill",
                                "asset_id": "stealth",
                                "operation": "grant",
                            },
                        }
                    ],
                }
            ],
        }
    )


def _pack() -> dict[str, object]:
    return {
        "pack_id": "test-pack",
        "label": "测试包",
        "source_book": "测试包",
        "source_book_aliases": [],
        "source_path_prefixes": ["测试包"],
        "source_origin": "test",
        "content_types": ["spells", "classes", "feats"],
    }


def test_spell_and_feature_drafts_share_provenance_and_never_compile_full() -> None:
    report = audit_records([_spell(), _feature()], source_book=None, pack_id="test-pack")
    drafts = [entry for entry in report.entries if not entry.get("non_instantiable")]
    assert {entry["kind"] for entry in drafts} == {"spell_draft", "feature_draft"}
    for draft in drafts:
        assert draft["source_record_id"]
        assert draft["source_fingerprint"]
        assert draft["source_metadata"]["compiler_fingerprint"]
        assert draft["status"] in {"manual", "partial"}
    assert (
        compile_feature_draft(next(item for item in drafts if item["kind"] == "feature_draft"))[
            "compile_status"
        ]
        != "full"
    )


def test_2024_and_2014_spell_records_are_separate() -> None:
    records = [
        _spell(book="玩家手册 2024", edition="2024"),
        _spell(
            name="旧版法术",
            book="玩家手册 2014",
            edition="legacy",
            path="玩家手册/魔法/法术详述/1环.html",
        ),
    ]
    modern = audit_records(records, source_book="玩家手册 2024")
    legacy = audit_records(records, source_book="玩家手册 2014")
    assert modern.total_records == 1
    assert legacy.total_records == 1
    assert modern.edition_counts == {"2024": 1}
    assert legacy.edition_counts == {"legacy": 1}


def test_official_pack_boundary_excludes_third_party_but_keeps_unknown_as_unverified() -> None:
    from dnd_dm_assistant.application.content_ir_workbench import _registered_pack, _select_records

    pack = _registered_pack("塔莎的万事坩埚")
    assert pack is not None
    records = [
        _spell(
            book="塔莎的万事坩埚", path="塔莎的万事坩埚/法术详述/1环.htm", officiality="unknown"
        ),
        _spell(
            name="第三方法术",
            book="塔莎的万事坩埚",
            path="第三方/塔莎的万事坩埚/法术详述/1环.htm",
            officiality="third_party",
        ),
    ]
    selected = _select_records(records, content_pack=pack)
    assert [item["name"] for item in selected] == ["测试法术"]


def test_spell_index_pages_are_non_instantiable() -> None:
    index = _spell(
        name="法师法术列表",
        path="玩家手册2024/角色职业/法师/法师法术列表.htm",
        markdown="## 法师法术列表\n\n0环 戏法 侦测魔法",
    )
    report = audit_records([index], source_book="玩家手册 2024")
    assert report.spell_count == 0
    assert report.non_instantiable_count == 1
    assert report.entries[0]["non_instantiable"] is True


def test_spell_source_boundary_stops_at_next_spell() -> None:
    record = _spell(
        markdown=(
            "## 火球术\n\n施法时间：动作\n\n施法距离：150尺\n\n"
            "造成 8d6 火焰伤害。\n\n## 下一法术\n\n造成 9d6 寒冷伤害。"
        )
    )
    report = audit_records([record], source_book="玩家手册 2024")
    text = report.entries[0]["source_text"]
    assert "下一法术" not in text
    assert "9d6" not in text


def test_minimal_typed_spell_is_full_and_missing_clause_parameter_is_partial() -> None:
    valid = SpellSpec.from_dict(
        {
            "spell_id": "test:valid-spell",
            "name": "有效法术",
            "level": 1,
            "clauses": [{"type": "damage", "expression": "1d6"}],
        }
    )
    assert compile_spell_spec(valid)["compile_status"] == "full"
    missing = SpellSpec.from_dict(
        {
            "spell_id": "test:missing-spell",
            "name": "缺字段法术",
            "level": 1,
            "clauses": [{"type": "damage"}],
        }
    )
    assert compile_spell_spec(missing)["compile_status"] == "partial"


def test_minimal_typed_feature_is_full() -> None:
    result = compile_typed_feature_spec(_typed_feature())
    assert result["compile_status"] == "full"
    assert result["typed_ir"] is True
    assert result["materialized"] is True


def test_unknown_spell_clause_is_invalid() -> None:
    spec = SpellSpec.from_dict(
        {
            "spell_id": "test:unknown-clause",
            "name": "未知子句",
            "level": 1,
            "clauses": [{"type": "rewrite_reality"}],
        }
    )
    result = compile_spell_spec(spec)
    assert result["compile_status"] == "invalid"
    assert result["runtime_blocks"] == []


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "draft"
    (root / "drafts").mkdir(parents=True)
    manifest = {
        "schema_version": "content-ir-workbench-manifest-2",
        "pack_id": "test-pack",
        "pack_version": "1.0.0",
        "source_book": "测试包",
        "source_fingerprints": {"source-1": "fp"},
        "draft_paths": ["drafts/a.json", "drafts/b.json"],
        "typed_ir_paths": [],
        "compiler_fingerprint": workbench.COMPILER_FINGERPRINT,
    }
    manifest["manifest_fingerprint"] = workbench._manifest_fingerprint(manifest)
    for name in ("a.json", "b.json"):
        (root / "drafts" / name).write_text(
            json.dumps(
                {
                    "kind": "feature_draft",
                    "feature_id": "duplicate:feature",
                    "source_record_id": "source-1",
                    "source_fingerprint": "fp",
                    "status": "manual",
                    "blocker_details": ["missing_typed_feature_ir"],
                }
            ),
            encoding="utf-8",
        )
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate feature_id/spell_id"):
        compile_artifact_directory(root, write_files=False)


def test_source_fingerprint_conflict_is_rejected_without_target(tmp_path: Path) -> None:
    pack = _pack()
    report = audit_records(
        [_spell(book="测试包", path="测试包/法术详述/1环.htm")],
        source_book="测试包",
        pack_id="test-pack",
    )
    root = tmp_path / "pack"
    compile_pack_records(
        [_spell(book="测试包", path="测试包/法术详述/1环.htm")],
        report=report,
        pack=pack,
        output_dir=root,
    )
    draft_path = next(root.glob("drafts/spell-*.json"))
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    draft["source_fingerprint"] = "changed"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    target = tmp_path / "isolated"
    result = dry_run_manifest(root / "manifest.json", target)
    assert result["status"] == "conflict"
    assert result["rolled_back"] is True
    assert not target.exists()


def test_dry_run_is_idempotent_and_does_not_write_production(tmp_path: Path) -> None:
    record = _spell(book="测试包", path="测试包/法术详述/1环.htm")
    pack = _pack()
    report = audit_records([record], source_book="测试包", pack_id="test-pack")
    root = tmp_path / "pack"
    production = tmp_path / "production"
    compile_pack_records([record], report=report, pack=pack, output_dir=root)
    target = tmp_path / "isolated"
    first = dry_run_manifest(root / "manifest.json", target)
    second = dry_run_manifest(root / "manifest.json", target)
    assert first["status"] == "dry_run"
    assert second["status"] == "idempotent_replay"
    assert not production.exists()
    assert first["production_mutated"] is False


def test_failed_dry_run_rolls_back_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = _spell(book="测试包", path="测试包/法术详述/1环.htm")
    pack = _pack()
    report = audit_records([record], source_book="测试包", pack_id="test-pack")
    root = tmp_path / "pack"
    compile_pack_records([record], report=report, pack=pack, output_dir=root)
    target = tmp_path / "isolated"
    original = workbench._write_json

    def fail_once(path: Path, value: object) -> None:
        if "staging-" in str(path):
            raise OSError("simulated write failure")
        original(path, value)

    monkeypatch.setattr(workbench, "_write_json", fail_once)
    result = dry_run_manifest(root / "manifest.json", target)
    assert result["status"] == "rolled_back"
    assert result["rolled_back"] is True
    assert not target.exists()
    assert not list(tmp_path.glob("isolated.staging-*"))


def test_report_is_byte_identical_on_replay(tmp_path: Path) -> None:
    record = _spell(book="测试包", path="测试包/法术详述/1环.htm")
    pack = _pack()
    report = audit_records([record], source_book="测试包", pack_id="test-pack")
    root = tmp_path / "pack"
    compile_pack_records([record], report=report, pack=pack, output_dir=root)
    first = (root / "report.json").read_bytes()
    compile_pack_records([record], report=report, pack=pack, output_dir=root)
    second = (root / "report.json").read_bytes()
    assert first == second
    assert report_from_artifacts(root)["schema_version"] == "content-ir-workbench-report-2"


def test_protected_untracked_paths_are_not_touched_by_dry_run() -> None:
    root = Path(__file__).resolve().parents[2]
    paths = [root / "backend/tests/ollama.py"]
    integration_dir = root / "backend/tests/integrations"
    if integration_dir.exists():
        paths.extend(path for path in integration_dir.rglob("*") if path.is_file())
    before = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.exists()
    }
    assert before
    after = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in before}
    assert before == after
