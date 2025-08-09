#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE_URL:-http://127.0.0.1:8000}"
symbols="${1:-ETH/USDT:USDT}"

HDR=()
if [[ -n "${WEBHOOK_TOKEN:-}" ]]; then
  HDR=(-H "X-Token: ${WEBHOOK_TOKEN}")
fi

curl -sS "${HDR[@]}" "${BASE}/status?symbols=${symbols}" | jq . || \
curl -sS "${HDR[@]}" "${BASE}/status?symbols=${symbols}"
