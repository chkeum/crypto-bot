#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" >/dev/null 2>&1 && set +a

BASE="${BASE_URL:-http://127.0.0.1:8000}"
SYM="${1:-XRP/USDT:USDT}"

URL="$BASE/orders?symbol=${SYM}"

# Local only: ALLOW_LOCAL_NOAUTH=1 로 인증 없이 접근
curl -sS "$URL" | jq . 2>/dev/null || curl -sS "$URL"

