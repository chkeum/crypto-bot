#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" >/dev/null 2>&1 && set +a
BASE="${BASE_URL:-http://127.0.0.1:8000}"
SYM="${1:-XRP/USDT:USDT}"
HDR=()
if [ -n "${WEBHOOK_TOKEN:-}" ]; then HDR=(-H "X-Token: ${WEBHOOK_TOKEN}"); fi
URL="$BASE/orders?symbol=${SYM}"
curl -sS "${HDR[@]}" "$URL" | jq . 2>/dev/null || curl -sS "${HDR[@]}" "$URL"
