from __future__ import annotations

import os

import uvicorn

from dnd_dm_assistant.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "dnd_dm_assistant.api.app:app",
        host=settings.host,
        port=settings.port,
        # The desktop launcher is a durable local service. Reload mode uses a
        # child process and can leave the embedded Qdrant lock behind after a
        # forced stop, so it is opt-in for interactive development only.
        reload=os.getenv("DND_DM_RELOAD", "").lower() in {"1", "true", "yes"},
    )


if __name__ == "__main__":
    main()
