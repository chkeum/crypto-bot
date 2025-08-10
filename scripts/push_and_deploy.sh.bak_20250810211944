#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# .env 로드 (있으면)
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" >/dev/null 2>&1 || true && set +a

# ---------- 설정(환경변수로 덮어쓰기 가능) ----------
BASE_BRANCH="${BASE_BRANCH:-main}"              # PR의 대상 브랜치
PR_BRANCH_PREFIX="${PR_BRANCH_PREFIX:-auto/deploy}"
PR_TITLE_PREFIX="${PR_TITLE_PREFIX:-Auto Deploy}"
PR_LABELS="${PR_LABELS:-auto,deploy}"
PR_BODY="${PR_BODY:-Automated deploy via script}"
PR_AUTO_MERGE="${PR_AUTO_MERGE:-1}"            # 1=가능하면 자동 머지
PR_MERGE_METHOD="${PR_MERGE_METHOD:-squash}"   # merge|squash|rebase
DEPLOY_AFTER="${DEPLOY_AFTER:-merged}"         # merged|always|never
DEPLOY_SCRIPT="${DEPLOY_SCRIPT:-scripts/deploy_wsl.sh}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-1}"

echo "[push+deploy] repo: $ROOT"
echo "[push+deploy] base branch: $BASE_BRANCH"

# ---------- 사전 체크 ----------
if ! command -v gh >/dev/null 2>&1; then
  echo "[push+deploy] ERROR: GitHub CLI 'gh' not found. Install https://cli.github.com/ and run 'gh auth login'"
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "[push+deploy] ERROR: GitHub CLI not authenticated. Run: gh auth login"
  exit 1
fi
git remote -v | grep -q '^origin' || { echo "[push+deploy] ERROR: no 'origin' remote"; exit 1; }

CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "[push+deploy] current branch: $CUR_BRANCH"

# 변경사항 커밋
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[push+deploy] changes detected → commit"
  git add -A
  git commit -m "auto deploy"
else
  echo "[push+deploy] no local changes"
fi

# base와 diff 없는지 확인(없으면 PR 불가)
git fetch origin "$BASE_BRANCH" --quiet
if git diff --quiet "origin/$BASE_BRANCH"...HEAD ; then
  echo "[push+deploy] no diff against $BASE_BRANCH → nothing to PR. exit."
  exit 0
fi

# PR용 브랜치 생성/푸시
TS="$(date +%Y%m%d%H%M%S)"
PR_BRANCH="${PR_BRANCH_PREFIX}-${TS}"
echo "[push+deploy] create/push PR branch: $PR_BRANCH"
git push origin "HEAD:refs/heads/${PR_BRANCH}"

# PR 생성
SHORT_SHA="$(git rev-parse --short HEAD)"
TITLE="${PR_TITLE_PREFIX} ${TS} (${SHORT_SHA})"
BODY="${PR_BODY}\n\nBase: ${BASE_BRANCH}\nHead: ${PR_BRANCH}\nSHA: ${SHORT_SHA}"

LABEL_ARGS=()
IFS=',' read -ra _LBL <<<"$PR_LABELS"
for l in "${_LBL[@]}"; do
  l_trim="$(echo "$l" | xargs)"
  [ -n "$l_trim" ] && LABEL_ARGS+=(--label "$l_trim")
done

echo "[push+deploy] creating PR → ${BASE_BRANCH} <= ${PR_BRANCH}"
PR_JSON="$(gh pr create --base "$BASE_BRANCH" --head "$PR_BRANCH" --title "$TITLE" --body "$BODY" "${LABEL_ARGS[@]}" --json number,url,state,mergeStateStatus)"
echo "$PR_JSON" | sed 's/.*/[push+deploy] PR JSON: &/'

# PR 번호/URL 추출
if command -v jq >/dev/null 2>&1; then
  PR_NUMBER="$(echo "$PR_JSON" | jq -r '.number')"
  PR_URL="$(echo "$PR_JSON" | jq -r '.url')"
else
  PR_NUMBER="$(echo "$PR_JSON" | sed -n 's/.*"number":\s*\([0-9]\+\).*/\1/p')"
  PR_URL="$(echo "$PR_JSON" | sed -n 's/.*"url":\s*"\(https[^"]*\)".*/\1/p')"
fi
[ -n "${PR_NUMBER:-}" ] || { echo "[push+deploy] ERROR: failed to get PR number"; exit 1; }
echo "[push+deploy] created PR #$PR_NUMBER → $PR_URL"

# 자동 머지 시도
MERGED=0
if [ "${PR_AUTO_MERGE}" = "1" ]; then
  echo "[push+deploy] try auto-merge (method=$PR_MERGE_METHOD)"
  MERGE_FLAG="--${PR_MERGE_METHOD}"
  if gh pr merge "$PR_NUMBER" "$MERGE_FLAG" --auto --delete-branch >/dev/null 2>&1; then
    echo "[push+deploy] auto-merge scheduled (will merge when checks pass)"
  else
    echo "[push+deploy] auto-merge not set/failed → try immediate merge..."
    if gh pr merge "$PR_NUMBER" "$MERGE_FLAG" --delete-branch; then
      MERGED=1
      echo "[push+deploy] merged PR #$PR_NUMBER"
    else
      echo "[push+deploy] merge failed (branch protection or required checks)"
    fi
  fi
fi

# 배포 정책
do_deploy=0
case "$DEPLOY_AFTER" in
  merged) [ "$MERGED" = "1" ] && do_deploy=1 ;;
  always) do_deploy=1 ;;
  never)  do_deploy=0 ;;
esac

if [ "$do_deploy" = "1" ]; then
  echo "[push+deploy] checkout/pull $BASE_BRANCH and deploy"
  git fetch origin "$BASE_BRANCH" --quiet
  git checkout "$BASE_BRANCH"
  git pull --ff-only origin "$BASE_BRANCH"

  if [ -x "$DEPLOY_SCRIPT" ]; then
    echo "[push+deploy] run: $DEPLOY_SCRIPT"
    SKIP_GIT_PULL="${SKIP_GIT_PULL}" bash "$DEPLOY_SCRIPT"
  else
    echo "[push+deploy] WARN: deploy script not found: $DEPLOY_SCRIPT"
  fi
else
  echo "[push+deploy] skip deploy (DEPLOY_AFTER=$DEPLOY_AFTER, MERGED=$MERGED)"
  echo "[push+deploy] PR URL: $PR_URL"
fi
