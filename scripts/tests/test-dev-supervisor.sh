#!/bin/bash
set -eu

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
state_dir="$(mktemp -d "${TMPDIR:-/tmp}/dnd-dm-supervisor.XXXXXX")"
supervisor_pid=""

cleanup_test() {
  if [ -n "$supervisor_pid" ] && kill -0 "$supervisor_pid" 2>/dev/null; then
    kill -TERM "$supervisor_pid" 2>/dev/null || true
    wait "$supervisor_pid" 2>/dev/null || true
  fi
  rm -rf "$state_dir"
}
trap cleanup_test EXIT INT TERM

DND_DM_TEST_STATE_DIR="$state_dir" \
DND_DM_BACKEND_SCRIPT="$repo_dir/scripts/tests/fixtures/fail-service.sh" \
DND_DM_FRONTEND_SCRIPT="$repo_dir/scripts/tests/fixtures/long-service.sh" \
  /bin/bash "$repo_dir/scripts/dev.sh" >"$state_dir/supervisor.log" 2>&1 &
supervisor_pid=$!

attempt=0
while kill -0 "$supervisor_pid" 2>/dev/null && [ "$attempt" -lt 100 ]; do
  attempt=$((attempt + 1))
  sleep 0.05
done

if kill -0 "$supervisor_pid" 2>/dev/null; then
  kill -TERM "$supervisor_pid" 2>/dev/null || true
  wait "$supervisor_pid" 2>/dev/null || true
  echo "Supervisor regression timed out after 5 seconds" >&2
  exit 1
fi

set -e
supervisor_status=0
wait "$supervisor_pid" || supervisor_status=$?
supervisor_pid=""

if [ "$supervisor_status" -ne 23 ]; then
  echo "Expected supervisor exit 23, got $supervisor_status" >&2
  exit 1
fi

if [ ! -f "$state_dir/frontend.stopped" ]; then
  echo "Supervisor did not terminate the surviving frontend service" >&2
  exit 1
fi

frontend_pid="$(sed -n '1p' "$state_dir/frontend.pid")"
if kill -0 "$frontend_pid" 2>/dev/null; then
  echo "Frontend service is still running after supervisor exit" >&2
  exit 1
fi

echo "Supervisor regression passed (failure status 23; sibling terminated)."
