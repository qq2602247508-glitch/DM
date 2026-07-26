#!/bin/bash
set -u

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_script="${DND_DM_BACKEND_SCRIPT:-$repo_dir/scripts/dev-backend.sh}"
frontend_script="${DND_DM_FRONTEND_SCRIPT:-$repo_dir/scripts/dev-frontend.sh}"

if [ ! -x "$backend_script" ]; then
  echo "Backend launcher is not executable: $backend_script" >&2
  exit 2
fi
if [ ! -x "$frontend_script" ]; then
  echo "Frontend launcher is not executable: $frontend_script" >&2
  exit 2
fi

backend_pid=""
frontend_pid=""
cleanup_started=0

cleanup() {
  if [ "$cleanup_started" -eq 1 ]; then
    return
  fi
  cleanup_started=1
  trap - EXIT INT TERM

  if [ -n "$backend_pid" ] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi
  if [ -n "$frontend_pid" ] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
  fi

  if [ -n "$backend_pid" ]; then
    wait "$backend_pid" 2>/dev/null || true
  fi
  if [ -n "$frontend_pid" ]; then
    wait "$frontend_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"$backend_script" &
backend_pid=$!
"$frontend_script" &
frontend_pid=$!

while kill -0 "$backend_pid" 2>/dev/null &&
  kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 0.1
done

child_status=0
if ! kill -0 "$backend_pid" 2>/dev/null; then
  wait "$backend_pid" || child_status=$?
else
  wait "$frontend_pid" || child_status=$?
fi

exit "$child_status"
