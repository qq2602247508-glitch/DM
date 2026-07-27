#!/usr/bin/env bash
set -euo pipefail

# Fast acceptance entry point.  The API runner creates a disposable campaign,
# then Playwright verifies the same room through DM + two real browser
# contexts.  Set DND_DM_ACCEPTANCE_KEEP=1 when a developer wants to inspect
# the generated campaign after the run.
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

run_root="${DND_DM_ACCEPTANCE_RUN_ROOT:-/Users/inagi/codex/900-杂项/local-dnd-dm-assistant/e2e-runs}"
run_id="$(date +%Y%m%d-%H%M%S)"
report_dir="$run_root/$run_id"
mkdir -p "$report_dir"

api_base="${DND_DM_ACCEPTANCE_BASE:-http://127.0.0.1:8000/api/v1}"
dm_url="${E2E_DM_URL:-http://127.0.0.1:5173}"
player_url="${E2E_PLAYER_URL:-http://127.0.0.1:8787}"
keep="${DND_DM_ACCEPTANCE_KEEP:-0}"

cleanup() {
  if [ "$keep" = "1" ]; then
    return
  fi
  if [ -f "$report_dir/fixture.json" ]; then
    campaign_id="$("$repo_dir/backend/.venv/bin/python" - "$report_dir/fixture.json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(data.get("campaign", {}).get("id", ""))
PY
)"
    if [ -n "$campaign_id" ]; then
      campaign_version="$(
        curl -fsS "$api_base/campaigns/$campaign_id" |
          "$repo_dir/backend/.venv/bin/python" -c \
            'import json,sys; print(json.load(sys.stdin).get("version", ""))' ||
          true
      )"
      if [ -n "$campaign_version" ]; then
        curl -fsS -X DELETE "$api_base/campaigns/$campaign_id" \
          -H "If-Match: \"$campaign_version\"" >/dev/null || true
      fi
    fi
  fi
}
trap cleanup EXIT

curl -fsS "$api_base/health" >/dev/null
curl -fsS "$player_url/api/v1/health" >/dev/null
curl -fsS "$dm_url/" >/dev/null

backend/.venv/bin/python scripts/acceptance/run_session.py \
  --base-url "$api_base" \
  --report-dir "$report_dir" \
  --keep

export E2E_API_URL="$api_base"
export E2E_DM_URL="$dm_url"
export E2E_PLAYER_URL="$player_url"
npm --prefix frontend run e2e

echo "浏览器综合验收完成：$report_dir"
