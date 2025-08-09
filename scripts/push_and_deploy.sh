#!/usr/bin/env bash
set -euo pipefail

# 배포할 브랜치 (기본 main, 환경변수로 변경 가능)
BRANCH="${BRANCH:-main}"

# 커밋 메시지 (인자로 받거나 기본값)
MSG="${1:-auto deploy}"

echo "[push+deploy] 현재 브랜치: $(git rev-parse --abbrev-ref HEAD)"

# 변경 사항 확인
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[push+deploy] 변경사항 발견 → commit & push"
  git add -A
  git commit -m "$MSG"
  git push origin "$BRANCH"
else
  echo "[push+deploy] 변경사항 없음 → push 생략"
fi

echo "[push+deploy] deploy_wsl.sh 실행..."
bash scripts/deploy_wsl.sh
