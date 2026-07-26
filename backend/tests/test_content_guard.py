import pytest

from dnd_dm_assistant.application.agent import _strip_ungrounded_mechanics
from dnd_dm_assistant.application.content_guard import (
    ensure_dnd5e_content,
    find_non_dnd_markers,
)


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
