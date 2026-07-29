from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import create_engine

from dnd_dm_assistant.api.routes.realtime import sqlite_change_stream


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def test_sqlite_change_stream_emits_only_after_commit(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE facts (id INTEGER PRIMARY KEY)")

    async def exercise() -> tuple[str, str]:
        stream = sqlite_change_stream(
            ConnectedRequest(),  # type: ignore[arg-type]
            engine,
            scope="campaign:test",
            interval_seconds=0.001,
        )
        ready = await anext(stream)
        with engine.begin() as writer:
            writer.exec_driver_sql("INSERT INTO facts DEFAULT VALUES")
        changed = await anext(stream)
        await stream.aclose()
        return ready, changed

    ready, changed = asyncio.run(exercise())
    assert "event: ready" in ready
    assert '"scope":"campaign:test"' in ready
    assert "event: change" in changed
