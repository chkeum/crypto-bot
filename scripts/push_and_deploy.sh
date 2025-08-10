#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" >/dev/null 2>&1 || true && set +a

BASE_BRANCH="${BASE_BRANCH:-main}"
PR_BRANCH_PREFIX="${PR_BRANCH_PREFIX:-auto/deploy}"
PR_TITLE_PREFIX="${PR_TITLE_PREFIX:-Auto Deploy}"
PR_LABELS="${PR_LABELS:-auto,deploy}"          # auto-create labels if missing
PR_BODY="${PR_BODY:-Automated deploy via script}"
PR_AUTO_MERGE="${PR_AUTO_MERGE:-1}"            # 1=auto-merge scheduling
PR_MERGE_METHOD="${PR_MERGE_METHOD:-squash}"   # merge|squash|rebase
DEPLOY_AFTER="${DEPLOY_AFTER:-merged}"         # merged|always|never
DEPLOY_SCRIPT="${DEPLOY_SCRIPT:-scripts/deploy_wsl.sh}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-1}"

# extras
FORCE_IMMEDIATE_MERGE_AFTER_AUTO="${FORCE_IMMEDIATE_MERGE_AFTER_AUTO:-1}"  # try immediate merge after --auto
REBASE_BEFORE_PR="${REBASE_BEFORE_PR:-1}"                                   # rebase onto base before PR
AMEND_LAST_AUTO_DEPLOY="${AMEND_LAST_AUTO_DEPLOY:-1}"                       # squash repeated "auto deploy" commits

echo "[push+deploy] repo: $ROOT"
echo "[push+deploy] base branch: $BASE_BRANCH"

# --- prechecks ---
if ! command -v gh >/dev/null 2>&1; then
  echo "[push+deploy] ERROR: GitHub CLI 'gh' not found. Install https://cli.github.com/ and run 'gh auth login'"; exit 1; fi
if ! gh auth status >/dev/null 2>&1; then
  echo "[push+deploy] ERROR: GitHub CLI not authenticated. Run: gh auth login"; exit 1; fi
git remote -v | grep -q '^origin' || { echo "[push+deploy] ERROR: no 'origin' remote"; exit 1; }

CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD || echo HEAD)"
echo "[push+deploy] current branch: $CUR_BRANCH"

# --- commit local changes (optionally amend last "auto deploy") ---
if ! git diff --quiet || ! git diff --cached --quiet; then
  last_msg="$(git log -1 --pretty=%s 2>/dev/null || true)"
  if [ "${AMEND_LAST_AUTO_DEPLOY}" = "1" ] && [ "$last_msg" = "auto deploy" ]; then
    echo "[push+deploy] changes detected → amend last 'auto deploy'"
    git add -A
    git commit --amend -m "auto deploy"
  else
    echo "[push+deploy] changes detected → commit"
    git add -A
    git commit -m "auto deploy"
  fi
else
  echo "[push+deploy] no local changes"
fi

# --- rebase onto base (reduce conflicts) ---
if [ "${REBASE_BEFORE_PR}" = "1" ]; then
  git fetch origin "$BASE_BRANCH" --quiet
  echo "[push+deploy] rebase onto origin/$BASE_BRANCH"
  set +e; git rebase "origin/$BASE_BRANCH"; REB=$?; set -e
  if [ $REB -ne 0 ]; then
    echo "[push+deploy] Rebase conflict. Resolve and re-run:"
    echo "  git status"
    echo "  git add <files> && git rebase --continue"
    echo "  # or: git rebase --abort"; exit 2; fi
fi

# no diff vs base? exit
git fetch origin "$BASE_BRANCH" --quiet
if git diff --quiet "origin/$BASE_BRANCH"...HEAD ; then
  echo "[push+deploy] no diff against $BASE_BRANCH → nothing to PR. exit."; exit 0; fi

# --- create PR branch ---
TS="$(date +%Y%m%d%H%M%S)"; PR_BRANCH="${PR_BRANCH_PREFIX}-${TS}"
echo "[push+deploy] create/push PR branch: $PR_BRANCH"
git push origin "HEAD:refs/heads/${PR_BRANCH}"

SHORT_SHA="$(git rev-parse --short HEAD)"
TITLE="${PR_TITLE_PREFIX} ${TS} (${SHORT_SHA})"
BODY="${PR_BODY}\n\nBase: ${BASE_BRANCH}\nHead: ${PR_BRANCH}\nSHA: ${SHORT_SHA}"

# labels (auto-create if missing)
LABEL_ARGS=()
REPO_NWO="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
IFS=',' read -ra _LBL <<<"$PR_LABELS"
for l in "${_LBL[@]}"; do
  l_trim="$(echo "$l" | xargs)"; [ -z "$l_trim" ] && continue
  if [ -n "$REPO_NWO" ]; then gh label create "$l_trim" --repo "$REPO_NWO" --color BFD4F2 --description "auto-created" >/dev/null 2>&1 || true; fi
  LABEL_ARGS+=(--label "$l_trim")
done

# create PR (compat; no --json)
echo "[push+deploy] creating PR → ${BASE_BRANCH} <= ${PR_BRANCH}"
set +e; PR_OUT="$(gh pr create --base "$BASE_BRANCH" --head "$PR_BRANCH" --title "$TITLE" --body "$BODY" "${LABEL_ARGS[@]}")"; PR_EXIT=$?; set -e
if [ $PR_EXIT -ne 0 ]; then
  echo "$PR_OUT" | sed 's/.*/[push+deploy] PR OUT: &/' || true
  echo "[push+deploy] WARN: PR with labels failed → retry without labels"
  set +e; PR_OUT="$(gh pr create --base "$BASE_BRANCH" --head "$PR_BRANCH" --title "$TITLE" --body "$BODY")"; PR_EXIT=$?; set -e; fi
[ $PR_EXIT -eq 0 ] || { echo "$PR_OUT"; echo "[push+deploy] ERROR: failed to create PR"; exit 1; }
echo "$PR_OUT" | sed 's/.*/[push+deploy] PR OUT: &/' || true

# get PR number/url
PR_URL="$(gh pr list --head "$PR_BRANCH" --state all --limit 1 --json url --jq '.[0].url' 2>/dev/null || true)"
PR_NUMBER="$(gh pr list --head "$PR_BRANCH" --state all --limit 1 --json number --jq '.[0].number' 2>/dev/null || true)"
if [ -z "${PR_NUMBER:-}" ] || [ "$PR_NUMBER" = "null" ]; then
  PR_URL="$(echo "$PR_OUT" | grep -Eo 'https://github\.com/[^ ]+/pull/[0-9]+' | head -n1 || true)"
  if [ -n "$PR_URL" ]; then PR_NUMBER="$(gh pr view "$PR_URL" --json number --jq '.number' 2>/dev/null || true)"; fi
fi
[ -n "${PR_NUMBER:-}" ] && [ "$PR_NUMBER" != "null" ] || { echo "[push+deploy] ERROR: cannot determine PR number"; exit 1; }
echo "[push+deploy] created PR #$PR_NUMBER → ${PR_URL:-"(use gh pr view $PR_NUMBER)"}"

# try merge
MERGED=0
if [ "${PR_AUTO_MERGE}" = "1" ]; then
  echo "[push+deploy] try auto-merge (method=$PR_MERGE_METHOD)"; MERGE_FLAG="--${PR_MERGE_METHOD}"
  if gh pr merge "$PR_NUMBER" "$MERGE_FLAG" --auto --delete-branch >/dev/null 2>&1; then
    echo "[push+deploy] auto-merge scheduled (will merge when checks pass)"
    if [ "${FORCE_IMMEDIATE_MERGE_AFTER_AUTO}" = "1" ]; then
      echo "[push+deploy] try immediate merge right now..."
      if gh pr merge "$PR_NUMBER" "$MERGE_FLAG" --delete-branch >/dev/null 2>&1; then MERGED=1; echo "[push+deploy] merged PR #$PR_NUMBER (immediate)"
      else echo "[push+deploy] immediate merge not allowed (waiting on checks or branch protection)"; fi
    fi
  else
    echo "[push+deploy] auto-merge not set/failed → try immediate merge..."
    if gh pr merge "$PR_NUMBER" "$MERGE_FLAG" --delete-branch; then MERGED=1; echo "[push+deploy] merged PR #$PR_NUMBER"
    else echo "[push+deploy] merge failed (branch protection or required checks)"; fi
  fi
fi

# deploy policy
do_deploy=0
case "$DEPLOY_AFTER" in merged) [ "$MERGED" = "1" ] && do_deploy=1 ;; always) do_deploy=1 ;; never) do_deploy=0 ;; esac
if [ "$do_deploy" = "1" ]; then
  echo "[push+deploy] checkout/pull $BASE_BRANCH and deploy"
  git fetch origin "$BASE_BRANCH" --quiet; git checkout "$BASE_BRANCH"; git pull --ff-only origin "$BASE_BRANCH"
  if [ -x "$DEPLOY_SCRIPT" ]; then echo "[push+deploy] run: $DEPLOY_SCRIPT"; SKIP_GIT_PULL="${SKIP_GIT_PULL}" bash "$DEPLOY_SCRIPT"
  else echo "[push+deploy] WARN: deploy script not found: $DEPLOY_SCRIPT"; fi
else
  echo "[push+deploy] skip deploy (DEPLOY_AFTER=$DEPLOY_AFTER, MERGED=$MERGED)"; [ -n "${PR_URL:-}" ] && echo "[push+deploy] PR URL: $PR_URL"
fi
