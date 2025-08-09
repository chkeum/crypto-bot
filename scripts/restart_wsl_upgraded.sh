#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

SYMBOLS="${1:-}"  # 선택 인자: 심볼 목록(쉼표구분). 비우면 .env에서 읽도록 stop 스크립트가 처리.

# 1) 스냅샷 찍고 중지
if [ -n "$SYMBOLS" ]; then
  "$SCRIPT_DIR/stop_wsl_upgraded.sh" "$SYMBOLS"
else
  "$SCRIPT_DIR/stop_wsl_upgraded.sh"
fi

# 2) 배포/재기동(기존 deploy 스크립트 사용)
"$SCRIPT_DIR/deploy_wsl.sh" || {
  echo "[restart] deploy_wsl.sh 실패"; exit 1;
}

# 3) 시작 후 헬스 & 상태 확인
echo "[restart] Post-start health/status check"
echo "---- /health ----"
curl -sf "http://$HOST:$PORT/health" || echo "(WARN) /health 실패"

# 상태는 심볼 지정 시 해당 심볼 우선
if [ -n "$SYMBOLS" ]; then
  enc="$(python3 - <<'PY'
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=''))
PY
"$SYMBOLS")"
  echo "---- /status (symbols=$SYMBOLS) ----"
  curl -sf "http://$HOST:$PORT/status?symbols=$enc" || echo "(WARN) /status 실패"
else
  echo "---- /status (default STRAT_SYMBOLS) ----"
  curl -sf "http://$HOST:$PORT/status" || echo "(WARN) /status 실패"
fi

echo
echo "[restart] done."
