#!/usr/bin/env bash
set -euo pipefail

# === 설정값(필요시 환경변수로 오버라이드) ===
REPO="${REPO:-$HOME/crypto-bot}"
SESSION="${SESSION:-bot}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
LOG_DIR="${LOG_DIR:-$REPO/logs}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/bot-$(date +%Y%m%d).log}"
TAIL_LINES="${TAIL_LINES:-200}"     # tail 시작 시 보여줄 라인 수
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-20}"  # 초

echo "[deploy] repo: $REPO"
cd "$REPO"

echo "[deploy] git pull..."
git pull --ff-only

echo "[deploy] venv check..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[deploy] deps..."
pip install -r requirements.txt

echo "[deploy] prepare log dir: $LOG_DIR"
mkdir -p "$LOG_DIR"
touch "$LOG_FILE"

# 이미 떠 있는 세션 정리
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "[deploy] kill old tmux session: $SESSION"
  tmux kill-session -t "$SESSION"
fi

# uvicorn + tee 로 로그 파일 기록
# stdbuf로 줄단위 즉시 flush
RUN_CMD="bash -lc 'cd $REPO && source .venv/bin/activate && stdbuf -oL -eL uvicorn bot.main:app --host $HOST --port $PORT 2>&1 | tee -a \"$LOG_FILE\"'"

echo "[deploy] start tmux session: $SESSION"
tmux new-session -d -s "$SESSION" "$RUN_CMD"

# 헬스 체크
echo "[deploy] health check..."
ok=false
for i in $(seq 1 "$HEALTH_TIMEOUT"); do
  if curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    ok=true
    break
  fi
  sleep 1
done

if [ "$ok" = true ]; then
  echo "[deploy] OK: http://$HOST:$PORT/health"
else
  echo "[deploy] WARN: health check failed (timeout ${HEALTH_TIMEOUT}s). 로그를 확인하세요."
fi

echo "[deploy] log file: $LOG_FILE"
echo "[deploy] tail -f (Ctrl+C로 종료; 봇은 계속 동작)"
echo "============================================================"
tail -n "$TAIL_LINES" -f "$LOG_FILE"
