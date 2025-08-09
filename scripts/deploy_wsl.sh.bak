#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$HOME/crypto-bot"
SESSION="bot"
HOST="127.0.0.1"
PORT="8000"
VENV="$APP_DIR/.venv"

echo "[deploy] repo: $APP_DIR"
cd "$APP_DIR"

echo "[deploy] git pull..."
git fetch --all --prune
git pull --ff-only origin main || {
  echo "[deploy] main이 없으면 develop에서 가져옵니다"
  git pull --ff-only origin develop || true
}

echo "[deploy] venv check..."
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1090
source "$VENV/bin/activate"

echo "[deploy] deps..."
pip install --upgrade pip >/dev/null
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi

echo "[deploy] restart tmux session: $SESSION"
tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new -s "$SESSION" -d "cd $APP_DIR && source $VENV/bin/activate && uvicorn bot.main:app --host $HOST --port $PORT"

echo "[deploy] health check..."
for i in {1..20}; do
  sleep 0.5
  if curl -sf "http://$HOST:$PORT/health" >/dev/null; then
    echo "[deploy] OK: http://$HOST:$PORT/health"
    break
  fi
  if [ "$i" -eq 20 ]; then
    echo "[deploy] WARN: /health 응답 없음(로그 확인 필요)"
  fi
done

echo "[deploy] tail logs (Ctrl+C로 종료)"
tmux attach -t "$SESSION"
