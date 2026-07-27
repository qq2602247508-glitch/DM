from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PlayerRulesSearch:
    """Deterministic public rule lookup that never calls an embedding or text model."""

    def __init__(self, corpus_root: Path) -> None:
        self.corpus_root = corpus_root

    @staticmethod
    def _excerpt(text: str, query: str, *, size: int = 320) -> str:
        compact = " ".join(text.split())
        index = compact.casefold().find(query.casefold())
        if index < 0:
            return compact[:size]
        start = max(0, index - size // 3)
        return compact[start : start + size]

    def search(self, text: str, *, limit: int = 8) -> list[dict[str, Any]]:
        query = text.strip()
        if not query:
            raise ValueError("rule search text must not be blank")
        if not self.corpus_root.exists():
            return []
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for path in self.corpus_root.glob("*/*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("officiality") != "official" or record.get("edition") not in {
                "2024",
                "2025",
            }:
                continue
            name = str(record.get("name") or "")
            aliases = " ".join(str(value) for value in record.get("aliases") or [])
            content = str(record.get("content_markdown") or record.get("content_text") or "")
            query_folded = query.casefold()
            name_folded = name.casefold()
            aliases_folded = aliases.casefold()
            content_folded = content.casefold()
            if query_folded not in f"{name_folded} {aliases_folded} {content_folded}":
                continue
            score = (
                100 if name_folded == query_folded else 70 if query_folded in name_folded else 45
            )
            if query_folded in aliases_folded:
                score += 20
            item = {
                "name": name,
                "excerpt": self._excerpt(content, query),
                "content_type": str(record.get("content_type") or "unknown"),
                "canonical_url": str(record.get("canonical_url") or record.get("source_url") or ""),
                "edition": str(record.get("edition") or ""),
                "officiality": "official",
            }
            scored.append((score, name, item))
        scored.sort(key=lambda row: (-row[0], row[1]))
        return [item for _, _, item in scored[:limit]]
