#!/usr/bin/env bash
# scripts/git_pull_last_branch.sh
# Checkout & pull the last pushed branch (recorded by git_push_new_branch.sh)
# Fallback: find latest 'PREFIX/*' branch from remote by commit date

set -Eeuo pipefail
IFS=$'\n\t'

log()  { echo "[pull-last] $*"; }
die()  { echo "[pull-last] ERROR: $*" >&2; exit 1; }

PREFIX="${PREFIX:-wip}"    # must match the push script
NTH="${NTH:-1}"            # 1=most recent, 2=the one before, ...

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Not a git repo."
git remote get-url origin >/dev/null 2>&1 || die "remote 'origin' not found"

git fetch -q origin --prune

pick_from_log() {
  local logf=".git/auto-branches.log"
  [[ -f "$logf" ]] || return 1
  # NTH-th from the end
  tac "$logf" | awk 'NF>=2{print $2}' | sed -n "${NTH}p"
}

pick_from_remote() {
  # find latest origin/$PREFIX/* by committerdate
  git for-each-ref --format='%(refname:short) %(committerdate:unix)' "refs/remotes/origin/${PREFIX}/*" \
  | sort -k2 -nr \
  | awk 'NR==1{print $1}' \
  | sed 's#^origin/##'
}

BR="$(pick_from_log || true)"
if [[ -z "${BR:-}" ]]; then
  log "no local log; try remote discovery"
  BR="$(pick_from_remote || true)"
fi
[[ -n "${BR:-}" ]] || die "No candidate branch found (prefix=${PREFIX})."

log "branch: $BR"

# create local if missing, track origin
if git show-ref --verify --quiet "refs/heads/${BR}"; then
  git switch "$BR"
else
  if git show-ref --verify --quiet "refs/remotes/origin/${BR}"; then
    git switch --track -c "$BR" "origin/${BR}"
  else
    die "Remote branch not found: origin/${BR}"
  fi
fi

git pull --ff-only
log "done."

