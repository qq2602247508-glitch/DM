from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class HealthStatus:
    status: Literal["ok"]
    database: Literal["ok"]


class HealthService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def check(self) -> HealthStatus:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return HealthStatus(status="ok", database="ok")
