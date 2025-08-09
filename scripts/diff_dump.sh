#!/usr/bin/env bash
set -euo pipefail
BASE="${1:-origin/main}"
echo "=== git status ==="
git status
echo
echo "=== git diff $BASE...HEAD ==="
git diff "$BASE...HEAD"
