#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
MSG="${1:-auto deploy}"

echo "[push+deploy] 현재 브랜치: $BRANCH"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[push+deploy] 변경사항 발견 → commit & push"
  git add -A
  git commit -m "$MSG"
  git push origin "$BRANCH"
else
  echo "[push+deploy] 변경사항 없음 → push 생략"
fi

echo "[push+deploy] deploy_wsl.sh 실행 (SKIP_GIT_PULL=1)"
SKIP_GIT_PULL=1 bash scripts/deploy_wsl.sh
