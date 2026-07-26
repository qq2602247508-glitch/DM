from __future__ import annotations

from pathlib import Path

import pytest

from dnd_dm_assistant.domain.content import ContentType, Edition, Officiality
from dnd_dm_assistant.integrations.content.classification import classify
from dnd_dm_assistant.integrations.content.navigation import (
    parse_navigation,
    parse_wcp_navigation,
)
from dnd_dm_assistant.integrations.content.parser import decode_html
from dnd_dm_assistant.integrations.content.url_policy import UrlPolicy, UrlRejected


@pytest.fixture
def policy() -> UrlPolicy:
    return UrlPolicy(
        base_url="https://5echm.kagangtuya.top/",
        allowed_hosts=frozenset({"5echm.kagangtuya.top"}),
    )


def test_url_policy_accepts_unicode_and_rejects_unsafe_urls(policy: UrlPolicy) -> None:
    canonical = policy.canonicalize("/topics/玩家手册2024/法术.htm#火球术")
    assert canonical.startswith("https://5echm.kagangtuya.top/topics/")
    assert canonical.endswith("#%E7%81%AB%E7%90%83%E6%9C%AF")

    rejected = (
        "file:///etc/passwd",
        "data:text/plain,bad",
        "javascript:alert(1)",
        "https://user:pass@5echm.kagangtuya.top/a",
        "https://5echm.kagangtuya.top:444/a",
        "https://example.invalid/a",
        "/topics/%2e%2e/secret",
    )
    for value in rejected:
        with pytest.raises(UrlRejected):
            policy.canonicalize(value)


def test_classification_is_explicit_and_preserves_unknown() -> None:
    spell = classify(
        "火球术",
        "https://5echm.kagangtuya.top/topics/玩家手册2024/法术详述/3环.htm",
    )
    assert spell.content_type is ContentType.SPELLS
    assert spell.edition is Edition.EDITION_2024
    assert spell.officiality is Officiality.OFFICIAL

    third_party = classify(
        "可选规则",
        "https://5echm.kagangtuya.top/topics/第三方/规则/foo.htm",
    )
    assert third_party.officiality is Officiality.THIRD_PARTY
    assert third_party.content_type is ContentType.RULES

    unknown = classify("神秘页", "https://5echm.kagangtuya.top/topics/misc/foo.htm")
    assert unknown.content_type is ContentType.UNKNOWN
    assert unknown.edition is Edition.UNKNOWN
    assert unknown.officiality is Officiality.UNKNOWN


def test_specific_title_and_immediate_category_beat_broad_path_markers() -> None:
    recipe = classify(
        "核心物品配方",
        "https://5echm.kagangtuya.top/第三方/德城怪物/附录E/核心物品配方.htm",
        ("第三方", "德城怪物", "附录E"),
    )
    assert recipe.content_type is ContentType.ITEMS

    true_monster = classify(
        "铁魔像",
        "https://5echm.kagangtuya.top/第三方/奇异物品集/怪物/铁魔像.htm",
        ("第三方", "奇异物品集", "怪物"),
    )
    assert true_monster.content_type is ContentType.MONSTERS

    ambiguous = classify(
        "职业动作",
        "https://5echm.kagangtuya.top/杂项/职业动作.htm",
    )
    assert ambiguous.content_type is ContentType.UNKNOWN

    resolved_ambiguity = classify(
        "职业法术列表",
        "https://5echm.kagangtuya.top/玩家手册2024/法术/职业法术列表.htm",
    )
    assert resolved_ambiguity.content_type is ContentType.SPELLS

    incidental_english = classify(
        "Iconic Franchise Features",
        "https://5echm.kagangtuya.top/怪物/Iconic_Franchise_Features.htm",
    )
    assert incidental_english.content_type is ContentType.MONSTERS


def test_navigation_is_ordered_deduplicated_and_alias_rich(policy: UrlPolicy) -> None:
    fixture = Path("backend/tests/fixtures/snapshot/webhelplefth.htm").read_text()
    discovery = parse_navigation(
        fixture,
        page_url=policy.canonicalize("/webhelplefth.htm"),
        policy=policy,
    )
    assert discovery.records[0].title == "核心规则"
    assert discovery.duplicate_count == 1
    fireball = next(record for record in discovery.records if record.title == "火球术")
    assert "Fireball alias" in fireball.aliases
    assert fireball.fragment == "Fireball"
    assert any(not record.fetchable for record in discovery.records)
    assert len(discovery.rejected_urls) == 2


def test_decode_html_handles_gb18030_and_malformed_utf8() -> None:
    text, warnings = decode_html("规则".encode("gb18030"), "text/html; charset=gb18030")
    assert text == "规则"
    assert "decoded_with_gb18030" in warnings

    replacement, replacement_warnings = decode_html(b"\xff\xfe\xfa")
    assert replacement
    assert replacement_warnings


def test_wcp_navigation_preserves_order_hierarchy_and_windows_paths(
    policy: UrlPolicy,
) -> None:
    manifest = """
[TOPICS]
TitleList.Title.0=玩家手册 2024
TitleList.Level.0=0
TitleList.Url.0=玩家手册2024\\第一章.htm
TitleList.Title.1=协助动作
TitleList.Level.1=1
TitleList.Url.1=玩家手册2024\\动作\\协助.htm
"""
    discovery = parse_wcp_navigation(manifest, policy=policy)
    assert [record.title for record in discovery.records] == [
        "玩家手册 2024",
        "协助动作",
    ]
    assert discovery.records[1].path_hierarchy == ("玩家手册 2024",)
    assert discovery.records[1].content_type is ContentType.ACTIONS
