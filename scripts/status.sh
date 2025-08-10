#!/usr/bin/env bash
set -euo pipefail

# 스크립트의 루트 경로를 찾고 .env 파일을 로드합니다.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" >/dev/null 2>&1 && set +a

# 기본 URL을 설정합니다. .env 파일에 BASE_URL이 없으면 로컬 주소를 사용합니다.
BASE="${BASE_URL:-http://127.0.0.1:8000}"

# 스크립트 실행 시 전달된 첫 번째 인자를 SYMS 변수에 저장합니다.
SYMS="${1:-}"

# 요청할 URL을 구성합니다.
URL="$BASE/status"
if [ -n "$SYMS" ]; then
  URL="$URL?symbols=$SYMS"
fi

# --- 수정된 부분 ---
# X-Token 헤더 없이 바로 curl로 로컬 봇 서버에 요청을 보냅니다.
# ALLOW_LOCAL_NOAUTH=1 설정에 따라 인증 없이 통신합니다.
curl -sS "$URL" | jq . 2>/dev/null || curl -sS "$URL"

