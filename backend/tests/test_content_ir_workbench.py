from __future__ import annotations

from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    audit_records,
    compile_spell_spec,
)


def _spell(book: str, path: str, *, name: str = "测试法术") -> dict[str, object]:
    return {
        "content_type": "spells",
        "name": name,
        "source_book": book,
        "source_relative_path": path,
        "stable_id": f"id-{book}-{name}",
        "content_plain_text": "施法时间：一个动作。对目标造成 1d6 火焰伤害。" * 4,
        "spell": {"level": 1},
    }


def test_workbench_keeps_2024_and_2014_spell_baselines_separate() -> None:
    records = [
        _spell("玩家手册 2024", "玩家手册2024/法术/法术详述/火球.html"),
        _spell("玩家手册 2014", "玩家手册/魔法/法术详述/1环.html"),
    ]
    modern = audit_records(records, source_book="玩家手册 2024")
    legacy = audit_records(records, source_book="玩家手册 2014")
    assert modern.spell_count == 1
    assert legacy.spell_count == 1


def test_unstructured_spell_draft_is_manual_not_full() -> None:
    report = audit_records(
        [_spell("塔莎的万事坩埚", "塔莎的万事坩埚/法术/法术详述/测试.html")]
    )
    assert report.spell_count == 1
    assert report.counts == {"full": 0, "partial": 0, "manual": 1, "invalid": 0}
    assert report.typed_ir_count == 0


def test_typed_spell_spec_requires_typed_clauses() -> None:
    spec = SpellSpec.from_dict(
        {
            "spell_id": "demo:spell",
            "name": "Demo",
            "level": 1,
            "clauses": [{"type": "damage", "expression": "1d6"}],
        }
    )
    assert spec.to_dict()["kind"] == "spell"
    assert compile_spell_spec(spec)["compile_status"] == "full"


def test_unknown_typed_spell_clause_fails_closed() -> None:
    spec = SpellSpec.from_dict(
        {
            "spell_id": "demo:unknown",
            "name": "Unknown",
            "level": 1,
            "clauses": [{"type": "rewrite_reality"}],
        }
    )
    result = compile_spell_spec(spec)
    assert result["compile_status"] == "invalid"
    assert result["runtime_blocks"] == []
