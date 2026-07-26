#!/usr/bin/env bash
set -euo pipefail

# One-click local launcher for macOS. Existing healthy services are reused.
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_dir="/Users/inagi/codex/900-杂项/local-dnd-dm-assistant/logs"
backend_url="http://127.0.0.1:8000/api/v1/health"
frontend_url="http://127.0.0.1:5173/"

mkdir -p "$log_dir"

backend_ready() {
  curl -fsS --max-time 2 "$backend_url" >/dev/null 2>&1
}

frontend_ready() {
  curl -fsS --max-time 2 "$frontend_url" >/dev/null 2>&1
}

if ! backend_ready; then
  echo "启动本地后端..."
  nohup "$repo_dir/scripts/dev-backend.sh" \
    >>"$log_dir/backend.log" 2>&1 < /dev/null &
fi

if ! frontend_ready; then
  echo "启动本地前端..."
  nohup "$repo_dir/scripts/dev-frontend.sh" \
    >>"$log_dir/frontend.log" 2>&1 < /dev/null &
fi

echo "等待本地服务就绪..."
for attempt in $(seq 1 60); do
  backend_ok=0
  frontend_ok=0
  backend_ready && backend_ok=1 || true
  frontend_ready && frontend_ok=1 || true

  if [ "$backend_ok" -eq 1 ] && [ "$frontend_ok" -eq 1 ]; then
    echo "本地 D&D 助手已就绪。"
    open "$frontend_url"
    exit 0
  fi
  sleep 1
done

echo "服务启动超时，请查看日志：" >&2
echo "  $log_dir/backend.log" >&2
echo "  $log_dir/frontend.log" >&2
exit 1
