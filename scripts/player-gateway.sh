#!/usr/bin/env bash
set -euo pipefail

# Explicit LAN-only player surface. The full DM backend remains on loopback.
export PATH="${PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

gateway_port=8787
export UV_CACHE_DIR="${UV_CACHE_DIR:-/Users/inagi/codex/900-杂项/uv-cache}"
python_bin="${DND_DM_GATEWAY_PYTHON:-$repo_dir/backend/.venv/bin/python}"
alembic_bin="${DND_DM_GATEWAY_ALEMBIC:-$repo_dir/backend/.venv/bin/alembic}"
if [ -n "${DND_DM_GATEWAY_NPM:-}" ]; then
  npm_bin="$DND_DM_GATEWAY_NPM"
elif [ -x /opt/homebrew/bin/npm ]; then
  npm_bin=/opt/homebrew/bin/npm
elif [ -x /usr/local/bin/npm ]; then
  npm_bin=/usr/local/bin/npm
else
  npm_bin="$(command -v npm || true)"
fi

if [ ! -x "$python_bin" ] || [ ! -x "$alembic_bin" ]; then
  echo "缺少 backend/.venv；请在联网时运行一次 ./scripts/setup.sh。" >&2
  exit 1
fi
if [ -z "$npm_bin" ] || [ ! -x "$npm_bin" ]; then
  echo "找不到 npm；请确认 Node.js 已安装在 /opt/homebrew、/usr/local 或 PATH 中。" >&2
  exit 1
fi
if [ ! -d "$repo_dir/frontend/node_modules" ]; then
  echo "缺少 frontend/node_modules；请在联网时运行一次 ./scripts/setup.sh。" >&2
  exit 1
fi

echo "等待本机 DM 后端完成启动和数据库迁移..."
backend_ready=0
for attempt in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    backend_ready=1
    break
  fi
  sleep 1
done
if [ "$backend_ready" -ne 1 ]; then
  echo "本机 DM 后端在 60 秒内没有就绪；玩家网关未启动。" >&2
  echo "请先检查 $repo_dir/scripts/dev-backend.sh 和后端日志。" >&2
  exit 1
fi

echo "构建玩家前端..."
VITE_API_BASE_URL=/api/v1 "$npm_bin" --prefix frontend run build

echo "确认数据库迁移版本..."
export PYTHONPATH="$repo_dir/backend/src${PYTHONPATH:+:$PYTHONPATH}"
"$alembic_bin" -c backend/alembic.ini upgrade head

echo ""
echo "局域网玩家网关即将启动。只应在可信任的家庭/桌面局域网中使用。"
echo "DM 主控仍为 http://127.0.0.1:5173，完整后端仍为 http://127.0.0.1:8000。"
"$repo_dir/scripts/print-player-gateway-urls.sh" "$gateway_port"
echo ""
echo "不要配置路由器端口转发或公网隧道。按 Ctrl-C 即可停止玩家网关。"

exec "$python_bin" -m uvicorn \
  dnd_dm_assistant.api.player_gateway:app \
  --host 0.0.0.0 \
  --port "$gateway_port" \
  --no-access-log
