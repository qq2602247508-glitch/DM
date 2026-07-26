#!/bin/bash
set -u

state_dir="${DND_DM_TEST_STATE_DIR:?DND_DM_TEST_STATE_DIR is required}"
printf '%s\n' "$$" >"$state_dir/backend.pid"

attempt=0
while [ ! -f "$state_dir/frontend.started" ] && [ "$attempt" -lt 100 ]; do
  attempt=$((attempt + 1))
  sleep 0.02
done

exit 23
