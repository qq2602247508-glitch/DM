#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

uv run --project backend ruff check backend
uv run --project backend mypy backend/src
uv run --project backend pytest backend/tests
/bin/bash scripts/tests/test-dev-supervisor.sh
/bin/bash scripts/tests/test-dev-backend-cache.sh

smoke_dir="$(mktemp -d "${TMPDIR:-/tmp}/dnd-dm-alembic.XXXXXX")"
trap 'rm -rf "$smoke_dir"' EXIT
DND_DM_DATABASE_URL="sqlite:///$smoke_dir/smoke.db" \
  uv run --project backend alembic -c backend/alembic.ini upgrade head

npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend test -- --run
npm --prefix frontend run build
