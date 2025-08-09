#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE_URL:-http://127.0.0.1:8000}"
symbols="${1:-ETH/USDT:USDT}"

HDR=()
[[ -n "${WEBHOOK_TOKEN:-}" ]] && HDR+=(-H "X-Token: ${WEBHOOK_TOKEN}")

resp="$(curl -sS "${HDR[@]}" "${BASE}/status?symbols=${symbols}")"

# 보기 좋게 출력 (jq 있으면 pretty, 없으면 원문)
if command -v jq >/dev/null 2>&1 && jq -e . >/dev/null 2>&1 <<<"$resp"; then
  pretty="$(jq . <<<"$resp")"
else
  pretty="$resp"
fi

# 응답을 화면 + 파일(logs/http-YYYYMMDD.log)에 같이 남기고 싶으면 HTTP_LOG=1 지정
if [[ "${HTTP_LOG:-0}" = "1" ]]; then
  mkdir -p logs
  {
    printf '%s %s\n' "$(date '+%F %T')" "GET /status?symbols=${symbols}"
    echo "$pretty"
    echo
  } | tee -a "logs/http-$(date +%Y%m%d).log"
else
  echo "$pretty"
fi
