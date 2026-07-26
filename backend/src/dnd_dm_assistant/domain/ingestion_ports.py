from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class FetchedPage:
    requested_url: str
    canonical_url: str
    body: bytes
    content_type: str
    fetched_at: datetime
    status_code: int


class PageFetcher(Protocol):
    async def check_robots(self) -> str: ...

    async def fetch(self, url: str) -> FetchedPage: ...
