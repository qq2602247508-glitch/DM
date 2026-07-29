from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.models import Campaign

router = APIRouter(
    prefix="/campaigns/{campaign_id}/events",
    tags=["realtime"],
)


def _event(name: str, payload: dict[str, object]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def sqlite_change_stream(
    request: Request,
    engine: Engine,
    *,
    scope: str,
    interval_seconds: float = 0.75,
) -> AsyncIterator[str]:
    """Emit one event whenever another SQLite connection commits.

    ``PRAGMA data_version`` is connection-local and advances when a different
    connection commits, making it a cheap invalidation signal without reading
    every campaign table or continuously returning full snapshots.
    """
    database = engine.url.database
    if not database or database == ":memory:":
        raise RuntimeError("realtime invalidation requires a file-backed SQLite database")
    # A stream can stay open for hours. Use a dedicated read-only sqlite
    # connection instead of occupying SQLAlchemy's finite request pool.
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=2) as connection:
        revision = int(connection.execute("PRAGMA data_version").fetchone()[0])
        yield _event("ready", {"scope": scope, "revision": revision})
        heartbeat = 0
        while not await request.is_disconnected():
            await asyncio.sleep(interval_seconds)
            current = int(connection.execute("PRAGMA data_version").fetchone()[0])
            if current != revision:
                revision = current
                yield _event("change", {"scope": scope, "revision": revision})
            heartbeat += 1
            if heartbeat >= 20:
                heartbeat = 0
                yield ": heartbeat\n\n"


@router.get("/stream")
def campaign_event_stream(
    campaign_id: str,
    request: Request,
) -> StreamingResponse:
    engine = cast(Engine, request.app.state.database_engine)
    with Session(engine) as session:
        if session.scalar(select(Campaign.id).where(Campaign.id == campaign_id)) is None:
            raise HTTPException(status_code=404, detail="campaign not found")
    return StreamingResponse(
        sqlite_change_stream(request, engine, scope=f"campaign:{campaign_id}"),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
