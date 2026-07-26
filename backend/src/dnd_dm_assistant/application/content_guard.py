from __future__ import annotations

import json
from typing import Any

# This application is deliberately D&D-only. These are unambiguous markers from
# other game systems/settings that the local model sometimes recalls from its
# general training data.
FORBIDDEN_NON_DND_MARKERS = (
    "克苏鲁",
    "奈亚拉托提普",
    "犹格·索托斯",
    "犹格索托斯",
    "阿撒托斯",
    "旧日支配者",
    "深潜者",
    "san值",
    "san 值",
    "理智检定",
    "call of cthulhu",
)


def find_non_dnd_markers(value: Any) -> tuple[str, ...]:
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, default=str)
    ).casefold()
    return tuple(marker for marker in FORBIDDEN_NON_DND_MARKERS if marker.casefold() in text)


def ensure_dnd5e_content(value: Any) -> None:
    markers = find_non_dnd_markers(value)
    if markers:
        raise ValueError(f"output contains non-D&D setting markers: {', '.join(markers)}")
