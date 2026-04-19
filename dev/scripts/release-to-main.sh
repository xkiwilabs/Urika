#!/bin/bash
# Release dev changes to main (public-facing branch).
#
# Strategy: instead of merging (which causes rename/delete conflicts),
# we checkout the public-facing files from dev into main. This avoids
# conflicts entirely because we never merge the dev-only paths.
#
# Usage: ./dev/scripts/release-to-main.sh

set -e

# Must be on dev to start
CURRENT=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT" != "dev" ]; then
    echo "ERROR: Must be on dev branch. Currently on: $CURRENT"
    exit 1
fi

# Must be clean
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: Working tree has uncommitted changes. Commit or stash first."
    exit 1
fi

echo "Releasing dev → main..."

# Save the dev commit hash for the message
DEV_SHA=$(git rev-parse --short HEAD)

git checkout main

# Clean public-facing directories on main before syncing from dev.
# This ensures renamed/deleted files don't linger on main.
git rm -rq src/ docs/ 2>/dev/null || true

# Checkout all public-facing files from dev
git checkout dev -- src/
git checkout dev -- docs/ 2>/dev/null || true
git checkout dev -- pyproject.toml
git checkout dev -- README.md
git checkout dev -- LICENSE
git checkout dev -- .gitignore
git checkout dev -- .github/ 2>/dev/null || true
git checkout dev -- CHANGELOG.md 2>/dev/null || true

# Remove dev-only files/dirs that should NEVER be on main/public.
# Everything dev-only lives under dev/ on the dev branch. These
# explicit removals are a safety net in case anything leaks through
# the checkout step above (e.g. old directories that were once
# tracked at the root level).
git rm -rq dev/ 2>/dev/null || true
git rm -rq docs/tutorials/ 2>/dev/null || true
git rm -rq docs/plans/ 2>/dev/null || true
git rm -rq packages/ 2>/dev/null || true
git rm -rq tui/ 2>/dev/null || true

# Stage everything
git add -A

# Only commit if there are changes
if ! git diff --cached --quiet 2>/dev/null; then
    git commit -m "release: sync from dev ($DEV_SHA)"
else
    echo "No changes to release."
    git checkout dev
    exit 0
fi

git push origin main
git push public main
git checkout dev

echo "Done. Main synced to dev ($DEV_SHA). Back on dev."
