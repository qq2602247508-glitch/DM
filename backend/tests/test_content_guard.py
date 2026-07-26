import pytest

from dnd_dm_assistant.application.agent import AgentOrchestrator, _strip_ungrounded_mechanics
from dnd_dm_assistant.application.content_guard import (
    ensure_dnd5e_content,
    find_non_dnd_markers,
)
from dnd_dm_assistant.domain.agent import GeneratedDMHint
from dnd_dm_assistant.domain.content import ContentType, Edition, Officiality
from dnd_dm_assistant.domain.rag import Citation


def test_accepts_dnd_2024_content() -> None:
    ensure_dnd5e_content(
        {"text": "一名夺心魔信徒守在祭坛前，要求进行感知豁免。"}
    )


@pytest.mark.parametrize(
    "text",
    [
        "奈亚拉托提普正在低语",
        "失败后进行 SAN 值检定",
        "旧日支配者从梦境中出现",
        "Call of Cthulhu scenario",
    ],
)
def test_rejects_unambiguous_non_dnd_markers(text: str) -> None:
    assert find_non_dnd_markers(text)
    with pytest.raises(ValueError, match="non-D&D"):
        ensure_dnd5e_content(text)


def test_strips_rule_numbers_when_no_verified_citation_exists() -> None:
    cleaned, changed = _strip_ungrounded_mechanics(
        "钟楼突然响起，引导玩家前往地窖。使用《怪物手册》的 CR 3 守卫，造成 2d6 伤害。"
    )
    assert changed is True
    assert cleaned == "钟楼突然响起，引导玩家前往地窖。"


def test_narrative_hint_strips_mechanics_even_when_a_citation_exists() -> None:
    citation = Citation(
        citation_id=1,
        chunk_id="chunk-1",
        record_id="record-1",
        rule_name="规则条目",
        source_title="规则资料",
        canonical_url="https://example.invalid/rule",
        section="规则",
        content_type=ContentType.RULES,
        edition=Edition.EDITION_2024,
        officiality=Officiality.OFFICIAL,
        score=0.9,
    )
    hint = AgentOrchestrator._build_hint(
        GeneratedDMHint(
            text="钟声响起，守卫封锁地窖。进行 DC 14 检定，失败受到 2d6 伤害。",
            assumptions=("守卫获得 +3 加值。",),
            citation_chunk_ids=("chunk-1",),
        ),
        (citation,),
        narrative_only=True,
    )
    assert hint.text == "钟声响起，守卫封锁地窖。"
    assert hint.assumptions == ()
    assert hint.citations == (citation,)
    assert "具体机械数值已移除" in hint.uncertainties[0]
