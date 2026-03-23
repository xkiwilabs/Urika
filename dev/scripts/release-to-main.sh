#!/bin/bash
# Release dev changes to main (public-facing branch).
# Merges dev into main, removes dev-only files, pushes to both remotes.
#
# Usage: ./dev/scripts/release-to-main.sh

set -e

echo "Releasing dev → main..."

git checkout main
git merge dev --no-edit

# Remove dev-only paths that should not be on the public branch
DEV_ONLY=(
    "dev"
    "CLAUDE.md"
    "tests"
)

for path in "${DEV_ONLY[@]}"; do
    if [ -e "$path" ]; then
        git rm -rq "$path" 2>/dev/null || true
    fi
done

# Only commit if there's something to clean
if ! git diff --cached --quiet 2>/dev/null; then
    git commit -m "chore: exclude dev-only files from main"
fi

git push origin main
git push public main
git checkout dev

echo "Done. Main pushed to origin + public. Back on dev."
