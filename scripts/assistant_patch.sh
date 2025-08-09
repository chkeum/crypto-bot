#!/usr/bin/env bash
set -euo pipefail

# 사용법:
#  - 파일로 패치 적용: scripts/assistant_patch.sh -f /tmp/patch.diff
#  - 붙여넣기(에디터)로 패치 적용: scripts/assistant_patch.sh
#  - 브랜치 이름 지정: scripts/assistant_patch.sh -b feat-my-change
#  - 자동 PR 생성(gh CLI 설치시): scripts/assistant_patch.sh -p

BASE_BRANCH="main"
BRANCH="feat-assistant-$(date +%Y%m%d-%H%M)"
PATCH_FILE=""
AUTO_PR=false

while getopts ":b:f:p" opt; do
  case $opt in
    b) BRANCH="$OPTARG" ;;
    f) PATCH_FILE="$OPTARG" ;;
    p) AUTO_PR=true ;;
    *) echo "Usage: $0 [-b branch] [-f patch_file] [-p]" && exit 1 ;;
  esac
done

# 0) 안전 확인
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[ERR] not a git repo"; exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "[WARN] working tree not clean. commit/stash first."; exit 1
fi

# 1) 최신 베이스 가져오기
git fetch --all --prune >/dev/null 2>&1 || true

# 2) 새 브랜치 생성
git checkout -b "$BRANCH"

# 3) 패치 준비
TMP="/tmp/assistant.patch"
if [ -z "$PATCH_FILE" ]; then
  echo "====================================================="
  echo "[INFO] 에디터가 열리면, '내가 보낸 패치(diff) 전문'을 붙여넣고 저장 후 종료하세요."
  echo "파일: $TMP"
  echo "====================================================="
  : > "$TMP"
  EDITOR_CMD=${EDITOR:-vim}
  if command -v "$EDITOR_CMD" >/dev/null 2>&1; then
    "$EDITOR_CMD" "$TMP"
  elif command -v vim >/dev/null 2>&1; then
    vim "$TMP"
  elif command -v nano >/dev/null 2>&1; then
    nano "$TMP"
  else
    vi "$TMP"
  fi
  if command -v nano >/dev/null 2>&1; then
    nano "$TMP"
  else
    vi "$TMP"
  fi
  PATCH_FILE="$TMP"
fi

if [ ! -s "$PATCH_FILE" ]; then
  echo "[ERR] patch file empty: $PATCH_FILE"; exit 1
fi

# 4) 패치 적용 시도
echo "[apply] git apply --index $PATCH_FILE"
if git apply --index "$PATCH_FILE"; then
  echo "[apply] OK"
else
  echo "[apply] failed. try --reject (수동 머지 필요)"
  git apply --reject "$PATCH_FILE" || { echo "[ERR] apply failed"; exit 1; }
  echo "[hint] *.rej 파일을 참고해 수동 수정 후, 'git add -A && git commit' 하세요."
  exit 0
fi

# 5) 커밋
git commit -m "apply: assistant patch"

# 6) 푸시
git push -u origin "$BRANCH"

# 7) PR 자동 생성(선택)
if $AUTO_PR; then
  if command -v gh >/dev/null 2>&1; then
    gh pr create --title "Apply assistant patch" --body "auto patch" --base "$BASE_BRANCH" --head "$BRANCH"
    gh pr view --web || true
  else
    echo "[info] gh CLI 미설치. 수동으로 PR 생성하세요:"
    echo "https://github.com/$(git remote get-url origin | sed -E 's#.*github.com[:/](.*)\.git#\1#')/compare/$BASE_BRANCH...$BRANCH"
  fi
else
  echo "[next] 웹에서 PR 생성:"
  echo "https://github.com/$(git remote get-url origin | sed -E 's#.*github.com[:/](.*)\.git#\1#')/compare/$BASE_BRANCH...$BRANCH"
fi
