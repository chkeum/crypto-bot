#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE_URL:-http://127.0.0.1:8000}"
sym="${1:-ETH/USDT:USDT}"

HDR=()
[[ -n "${WEBHOOK_TOKEN:-}" ]] && HDR+=(-H "X-Token: ${WEBHOOK_TOKEN}")

resp="$(curl -sS "${HDR[@]}" "${BASE}/orders?symbol=${sym}")"

if command -v jq >/dev/null 2>&1 && jq -e . >/dev/null 2>&1 <<<"$resp"; then
  pretty="$(jq . <<<"$resp")"
else
  pretty="$resp"
fi

if [[ "${HTTP_LOG:-0}" = "1" ]]; then
  mkdir -p logs
  {
    printf '%s %s\n' "$(date '+%F %T')" "GET /orders?symbol=${sym}"
    echo "$pretty"
    echo
  } | tee -a "logs/http-$(date +%Y%m%d).log"
else
  echo "$pretty"
fi
