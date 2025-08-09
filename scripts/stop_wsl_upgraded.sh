#!/usr/bin/env bash
set -euo pipefail

SESSION="bot"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
APP_DIR="$HOME/crypto-bot"
ENV_FILE="$APP_DIR/.env"

# URL 인코딩 함수
urlencode() {
  local str="$1"
  local i c
  for (( i=0; i<${#str}; i++ )); do
    c=${str:$i:1}
    case "$c" in
      [a-zA-Z0-9.~_-]) printf "%s" "$c" ;;
      *) printf "%%%02X" "'$c" ;;
    esac
  done
}

# jq가 있으면 예쁘게, 없으면 원문 출력
pretty() {
  if command -v jq >/dev/null 2>&1; then
    jq .
  else
    cat
  fi
}

# .env에서 STRAT_SYMBOLS 읽기 (없으면 기본값)
read_symbols_from_env() {
  if [ -f "$ENV_FILE" ]; then
    local line
    line=$(grep -E '^STRAT_SYMBOLS=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2-)
    # 공백 제거
    line="${line//[[:space:]]/}"
    if [ -n "$line" ]; then
      echo "$line"
      return 0
    fi
  fi
  echo "BTC/USDT:USDT"
}

# 인자로 심볼 목록 받기(쉼표구분), 없으면 .env에서 읽기
SYMBOLS="${1:-$(read_symbols_from_env)}"

echo "[stop] Pre-stop snapshot from http://$HOST:$PORT"

# /health
echo "---- /health ----"
if curl -sf "http://$HOST:$PORT/health" | pretty; then
  :
else
  echo "(WARN) /health 요청 실패"
fi

# /status (여러 심볼 콤마로 전달 가능)
echo "---- /status ----"
if curl -sf "http://$HOST:$PORT/status?symbols=$(urlencode "$SYMBOLS")" | pretty; then
  :
else
  echo "(WARN) /status 요청 실패"
fi

# /orders 각 심볼별
IFS=',' read -r -a ARR <<< "$SYMBOLS"
for sym in "${ARR[@]}"; do
  enc=$(urlencode "$sym")
  echo "---- /orders?symbol=$sym ----"
  if curl -sf "http://$HOST:$PORT/orders?symbol=$enc" | pretty; then
    :
  else
    echo "(WARN) /orders 요청 실패: $sym"
  fi
done

# tmux 세션 종료
echo "[stop] stopping tmux session: $SESSION"
if tmux kill-session -t "$SESSION" 2>/dev/null; then
  echo "[stop] session '$SESSION' stopped."
else
  echo "[stop] no session named '$SESSION' found."
fi
