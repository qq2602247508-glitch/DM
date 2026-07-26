from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dnd_dm_assistant.domain.content import ContentType, Edition, NavigationRecord, Officiality
from dnd_dm_assistant.integrations.content.parser import parse_entities
from dnd_dm_assistant.integrations.content.url_policy import UrlPolicy


def test_fireball_anchor_fields_and_section_boundary() -> None:
    policy = UrlPolicy(
        base_url="https://5echm.kagangtuya.top/",
        allowed_hosts=frozenset({"5echm.kagangtuya.top"}),
    )
    url = policy.canonicalize("/topics/玩家手册2024/法术详述/3环.htm")
    record = NavigationRecord(
        title="火球术",
        url=f"{url}#Fireball",
        canonical_url=f"{url}#Fireball",
        source_book="玩家手册 2024",
        edition=Edition.EDITION_2024,
        officiality=Officiality.OFFICIAL,
        content_type=ContentType.SPELLS,
        fragment="Fireball",
        fetchable=True,
    )
    html = Path("backend/tests/fixtures/snapshot/topics/玩家手册2024/法术详述/3环.htm").read_text()
    entities = parse_entities(
        html,
        record=record,
        page_url=url,
        policy=policy,
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        run_id="fixture-run",
    )
    assert len(entities) == 1
    entity = entities[0]
    assert entity.name == "火球术"
    assert entity.aliases == ("Fireball",)
    assert entity.fragment == "Fireball"
    assert entity.spell is not None
    assert entity.spell.level == 3
    assert entity.spell.school == "塑能"
    assert entity.spell.range == "150尺（150 feet）"
    assert entity.spell.damage_expression == "8d6"
    assert entity.spell.damage_type == "火焰"
    assert entity.spell.save == "敏捷豁免"
    assert entity.spell.upcast_text is not None
    assert "后续法术" not in entity.content_plain_text


def test_cleanup_preserves_tables_lists_and_removes_untrusted_noise() -> None:
    policy = UrlPolicy(
        base_url="https://5echm.kagangtuya.top/",
        allowed_hosts=frozenset({"5echm.kagangtuya.top"}),
    )
    url = policy.canonicalize("/topics/规则/核心规则.htm")
    record = NavigationRecord(
        title="核心规则",
        url=url,
        canonical_url=url,
        content_type=ContentType.RULES,
        fetchable=True,
    )
    html = Path("backend/tests/fixtures/snapshot/topics/规则/核心规则.htm").read_text()
    entity = parse_entities(
        html,
        record=record,
        page_url=url,
        policy=policy,
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        run_id="fixture-run",
    )[0]
    assert "| 结果 | 说明 |" in entity.content_markdown
    assert "- 第一项" in entity.content_markdown
    assert "ignore()" not in entity.content_markdown
    assert "UI navigation" not in entity.content_markdown
    assert "outside.invalid" not in entity.content_markdown
    assert any(warning.startswith("unsafe_link_removed") for warning in entity.warnings)


def test_structural_spell_fields_stop_at_nested_break_in_malformed_markup() -> None:
    policy = UrlPolicy(
        base_url="https://5echm.kagangtuya.top/",
        allowed_hosts=frozenset({"5echm.kagangtuya.top"}),
    )
    url = policy.canonicalize("/topics/玩家手册2024/法术详述/1环.htm")
    record = NavigationRecord(
        title="边界术",
        url=f"{url}#Boundary",
        canonical_url=f"{url}#Boundary",
        edition=Edition.EDITION_2024,
        officiality=Officiality.OFFICIAL,
        content_type=ContentType.SPELLS,
        fragment="Boundary",
        fetchable=True,
    )
    html = """
    <h4 id="Boundary">边界术｜Boundary</h4>
    <p><em>一环 防护（法师）</em><br>
    <strong>施法时间：</strong><span>一个动作</span><br>
    <strong>施法距离：</strong><span>自身</span><br>
    <strong>法术成分：</strong><span>V、<em>S</em></span><br>
    <strong>持续时间：</strong><span>专注，至多1分钟<br>
    后续描述不属于持续时间
    </p>
    """
    entity = parse_entities(
        html,
        record=record,
        page_url=url,
        policy=policy,
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        run_id="fixture-run",
    )[0]
    assert entity.spell is not None
    assert entity.spell.casting_time == "一个动作"
    assert entity.spell.range == "自身"
    assert entity.spell.components == "V、 S"
    assert entity.spell.duration == "专注，至多1分钟"
