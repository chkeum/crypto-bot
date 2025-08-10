#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[deploy] repo: $ROOT"
if [[ "${SKIP_GIT_PULL:-0}" = "1" ]]; then
  echo "[deploy] skip git pull (SKIP_GIT_PULL=1)"
else
  echo "[deploy] git pull..."
  git pull --ff-only
fi

echo "[deploy] venv check..."
[[ -d .venv ]] || python3 -m venv .venv
source .venv/bin/activate

# >>> .env 로드: FastAPI 프로세스/tmux가 WEBHOOK_TOKEN 등 환경을 갖도록
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "[deploy] deps..."
pip install -r requirements.txt -q

LOGDIR="$ROOT/logs"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/bot-$(date +%Y%m%d).log"
echo "[deploy] prepare log dir: $LOGDIR"

echo "[deploy] kill old tmux session: bot"
tmux kill-session -t bot 2>/dev/null || true

echo "[deploy] start tmux session: bot"
tmux new-session -d -s bot "bash -lc 'export PYTHONUNBUFFERED=1; source .venv/bin/activate; if [[ -f .env ]]; then set -a; source .env; set +a; fi; stdbuf -oL -eL uvicorn bot.main:app --host 127.0.0.1 --port 8000 2>&1 | stdbuf -oL -eL tee -a \"$LOGFILE\"'"

echo "[deploy] health check..."
ok=0
for i in {1..30}; do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "[deploy] OK: http://127.0.0.1:8000/health"
    ok=1; break
  fi
  sleep 1
done
if [[ $ok -ne 1 ]]; then
  echo "[deploy] health check FAILED"
  echo "----- last 200 log lines -----"
  tail -n 200 "$LOGFILE" || true
  exit 1
fi

if [[ "${NO_TAIL:-0}" != "1" ]]; then
  echo "[deploy] log file: $LOGFILE"
  echo "[deploy] tail -f (Ctrl+C로 종료; 봇은 계속 동작)"
  tail -n 200 -f "$LOGFILE"
fi
