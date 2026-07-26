#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/Users/inagi/codex/900-杂项/uv-cache}"

uv run --project backend alembic -c backend/alembic.ini upgrade head
exec uv run --project backend python -m dnd_dm_assistant
