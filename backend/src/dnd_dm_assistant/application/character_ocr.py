from __future__ import annotations

import base64
import binascii
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _field(text: str, labels: tuple[str, ...], *, numeric: bool = False) -> str | int | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    value_pattern = r"(\d{1,3})" if numeric else r"([^\n\r：:]{1,50})"
    match = re.search(
        rf"(?:{label_pattern})\s*[：:]?\s*{value_pattern}",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(1).strip()
    return int(value) if numeric else value


def character_draft_from_text(text: str) -> dict[str, Any]:
    scores = {
        key: value
        for key, labels in {
            "strength": ("力量", "STR"),
            "dexterity": ("敏捷", "DEX"),
            "constitution": ("体质", "CON"),
            "intelligence": ("智力", "INT"),
            "wisdom": ("感知", "WIS"),
            "charisma": ("魅力", "CHA"),
        }.items()
        if (value := _field(text, labels, numeric=True)) is not None
        and 1 <= int(value) <= 30
    }
    hp = _field(text, ("当前生命值", "生命值", "HP"), numeric=True)
    max_hp = _field(text, ("最大生命值", "生命值上限", "MAX HP"), numeric=True)
    return {
        "name": _field(text, ("角色姓名", "角色名", "姓名", "NAME")) or "OCR 待确认角色",
        "race": _field(text, ("种族", "物种", "RACE", "SPECIES")),
        "background": _field(text, ("背景", "BACKGROUND")),
        "class_name": _field(text, ("职业", "CLASS")),
        "level": _field(text, ("等级", "LEVEL", "LV"), numeric=True) or 1,
        "armor_class": _field(text, ("护甲等级", "护甲级别", "AC"), numeric=True) or 10,
        "speed": _field(text, ("速度", "SPEED"), numeric=True) or 30,
        "hp": int(hp or max_hp or 0),
        "max_hp": max(int(max_hp or hp or 0), int(hp or 0)),
        "ability_scores": scores,
        "notes": "由本机 Vision OCR 生成的待审核草稿",
    }


def recognize_character_sheet(
    image_base64: str,
    *,
    filename: str,
    script_path: Path,
) -> dict[str, Any]:
    try:
        payload = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 image") from exc
    if not payload or len(payload) > 12 * 1024 * 1024:
        raise ValueError("image must be between 1 byte and 12 MB")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".heic", ".tiff", ".webp"}:
        suffix = ".png"
    source_path = script_path.with_suffix(".m")
    if not source_path.is_file():
        raise ValueError("local OCR script is unavailable")
    binary = Path(tempfile.gettempdir()) / "local-dnd-character-sheet-ocr"
    if not binary.is_file() or binary.stat().st_mtime < source_path.stat().st_mtime:
        try:
            subprocess.run(
                [
                    "/usr/bin/clang",
                    "-fobjc-arc",
                    "-framework",
                    "Foundation",
                    "-framework",
                    "AppKit",
                    "-framework",
                    "Vision",
                    str(source_path),
                    "-o",
                    str(binary),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or "local OCR compiler failed"
            raise ValueError(str(detail).strip()[:500]) from exc
    with tempfile.NamedTemporaryFile(suffix=suffix) as image:
        image.write(payload)
        image.flush()
        try:
            completed = subprocess.run(
                [str(binary), image.name],
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or "local OCR failed"
            raise ValueError(str(detail).strip()[:500]) from exc
    text = completed.stdout.strip()
    if not text:
        raise ValueError("no text was recognized")
    return {
        "engine": "macOS Vision",
        "local_only": True,
        "recognized_text": text,
        "draft": character_draft_from_text(text),
        "requires_dm_confirmation": True,
    }
