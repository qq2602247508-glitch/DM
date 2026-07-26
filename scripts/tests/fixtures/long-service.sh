#!/bin/bash
set -u

state_dir="${DND_DM_TEST_STATE_DIR:?DND_DM_TEST_STATE_DIR is required}"
printf '%s\n' "$$" >"$state_dir/frontend.pid"
touch "$state_dir/frontend.started"

stop_service() {
  touch "$state_dir/frontend.stopped"
  exit 0
}
trap stop_service INT TERM

while :; do
  sleep 1
done
