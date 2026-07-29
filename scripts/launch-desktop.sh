#!/usr/bin/env bash
set -euo pipefail

# One-click local launcher for macOS. Existing healthy services are reused.
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_dir="${DND_DM_LOG_DIR:-$repo_dir/logs}"
diagnose_script="${DND_DM_DIAGNOSE_SCRIPT:-$repo_dir/scripts/diagnose.sh}"
player_gateway_script="${DND_DM_PLAYER_GATEWAY_SCRIPT:-$repo_dir/scripts/player-gateway.sh}"
backend_url="http://127.0.0.1:8000/api/v1/health"
frontend_url="http://127.0.0.1:5173/"
player_gateway_url="http://127.0.0.1:8787/api/v1/health"

mkdir -p "$log_dir"

"$diagnose_script"

backend_ready() {
  curl -fsS --max-time 2 "$backend_url" >/dev/null 2>&1
}

frontend_ready() {
  curl -fsS --max-time 2 "$frontend_url" >/dev/null 2>&1
}

player_gateway_ready() {
  curl -fsS --max-time 2 "$player_gateway_url" >/dev/null 2>&1
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

if ! player_gateway_ready; then
  if [ ! -x "$player_gateway_script" ]; then
    echo "玩家网关启动脚本不可执行：$player_gateway_script" >&2
    exit 2
  fi
  echo "启动局域网玩家网关..."
  nohup "$player_gateway_script" \
    >>"$log_dir/player-gateway.log" 2>&1 < /dev/null &
fi

echo "等待本地服务就绪..."
for attempt in $(seq 1 120); do
  backend_ok=0
  frontend_ok=0
  player_gateway_ok=0
  backend_ready && backend_ok=1 || true
  frontend_ready && frontend_ok=1 || true
  player_gateway_ready && player_gateway_ok=1 || true

  if [ "$backend_ok" -eq 1 ] && [ "$frontend_ok" -eq 1 ] &&
    [ "$player_gateway_ok" -eq 1 ]; then
    echo "本地 D&D 助手已就绪。"
    echo "局域网玩家网关已就绪；请在主控台创建房间后分享房间码。"
    "$repo_dir/scripts/print-player-gateway-urls.sh" 8787
    diagnostics="$(curl -fsS --max-time 10 http://127.0.0.1:8000/api/v1/system/diagnostics || true)"
    if [ -n "$diagnostics" ]; then
      echo "启动诊断已完成；详细状态可在“设置与备份”查看。"
    fi
    if curl -fsS --max-time 30 -X POST \
      http://127.0.0.1:8000/api/v1/system/recovery-points/ensure-automatic \
      >/dev/null 2>&1; then
      echo "每日自动恢复点已检查。"
    else
      echo "自动恢复点创建失败；服务仍可使用，请在“设置与备份”手动创建。" >&2
    fi
    open "$frontend_url"
    exit 0
  fi
  sleep 1
done

echo "服务启动超时，请查看日志：" >&2
echo "  $log_dir/backend.log" >&2
echo "  $log_dir/frontend.log" >&2
echo "  $log_dir/player-gateway.log" >&2
exit 1
