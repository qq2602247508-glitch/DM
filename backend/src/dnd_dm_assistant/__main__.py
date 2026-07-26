from __future__ import annotations

import uvicorn

from dnd_dm_assistant.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "dnd_dm_assistant.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
