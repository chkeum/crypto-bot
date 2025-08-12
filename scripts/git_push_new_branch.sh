#!/usr/bin/env bash
# scripts/git_push_new_branch.sh
# Always create a new branch from current HEAD and push safely
# - No rebase/merge, so no conflicts
# - Records pushed branch to .git/auto-branches.log

set -Eeuo pipefail
IFS=$'\n\t'

log()  { echo "[push-new] $*"; }
die()  { echo "[push-new] ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- config (override by env/args) ---
PREFIX="${PREFIX:-wip}"                         # branch prefix (e.g. wip/ feat/ fix/)
MSG="${1:-${COMMIT_MSG:-"wip: auto commit"}}"   # commit message

# --- preflight ---
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Not a git repo."
git config user.name  >/dev/null 2>&1 || die "git user.name is not set"
git config user.email >/dev/null 2>&1 || die "git user.email is not set"
git remote get-url origin >/dev/null 2>&1 || die "remote 'origin' not found"

# sanitize prefix: allow [A-Za-z0-9._/-]
PREFIX_SAFE="$(printf '%s' "$PREFIX" | sed 's#[^A-Za-z0-9._/-]#-#g; s#^/*##; s#/*$##')"
[ -n "$PREFIX_SAFE" ] || PREFIX_SAFE="wip"

TS="$(date +%Y%m%d%H%M%S)"
HOST="$(hostname | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-')"

# FIX: no curly braces here
BR="${PREFIX_SAFE}/${HOST}-${TS}"

git fetch -q origin --prune
if git ls-remote --exit-code --heads origin "$BR" >/dev/null 2>&1; then
  SUFFIX="$(openssl rand -hex 3 2>/dev/null || echo rnd)"
  BR="${PREFIX_SAFE}/${HOST}-${TS}-${SUFFIX}"
fi

log "new branch: $BR"
git switch -c "$BR"

if [[ -n "$(git status --porcelain=v1)" ]]; then
  git add -A
  git commit -m "$MSG"
else
  if [[ "${ALLOW_EMPTY:-0}" = "1" ]]; then
    git commit --allow-empty -m "$MSG"
  else
    log "nothing to commit; pushing branch without new commit (ok)"
  fi
fi

git push -u origin "$BR"

printf "%s %s\n" "$TS" "$BR" >> .git/auto-branches.log

REMOTE_URL="$(git config --get remote.origin.url || true)"
SLUG=""
case "$REMOTE_URL" in
  git@github.com:*.git) SLUG="${REMOTE_URL#git@github.com:}"; SLUG="${SLUG%.git}";;
  https://github.com/*) SLUG="${REMOTE_URL#https://github.com/}"; SLUG="${SLUG%.git}";;
esac
[[ -n "$SLUG" ]] && echo "[push-new] create PR: https://github.com/${SLUG}/compare/${BR}?expand=1"

log "done."

