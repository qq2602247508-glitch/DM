#!/usr/bin/env bash
set -euo pipefail

gateway_port="${1:-8787}"
echo "玩家访问地址："

addresses="$(ifconfig 2>/dev/null | awk '
  /^[[:alnum:]][[:alnum:]_.-]*:/ { iface=$1; sub(/:$/, "", iface) }
  /inet / && $2 !~ /^127\./ && $2 !~ /^169\.254\./ { print iface " " $2 }
')"
shown=0
while IFS=' ' read -r interface address; do
  [ -n "${address:-}" ] || continue
  case "$address" in
    10.*|192.168.*|172.16.*|172.17.*|172.18.*|172.19.*|172.2[0-9].*|172.30.*|172.31.*)
      echo "  http://$address:$gateway_port/#/player  ($interface)"
      shown=1
      ;;
  esac
done <<EOF
$addresses
EOF

local_name="$(scutil --get LocalHostName 2>/dev/null || hostname -s 2>/dev/null || true)"
if [ -n "$local_name" ]; then
  echo "  http://$local_name.local:$gateway_port/#/player  (mDNS，部分网络可能不可用)"
fi
if [ "$shown" -eq 0 ]; then
  echo "  未发现私有 IPv4；请确认 Wi-Fi/有线网络已连接，且未启用访客网络隔离。"
fi
