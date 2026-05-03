#!/bin/bash
# Release dev changes to main (public-facing branch).
#
# Strategy: instead of merging (which causes rename/delete conflicts),
# we checkout the public-facing files from dev into main. This avoids
# conflicts entirely because we never merge the dev-only paths.
#
# Two safety nets keep dev-only content off main / public:
#   1. Allowlist of public-facing paths to copy from dev (src/, docs/,
#      pyproject.toml, README.md, LICENSE, .gitignore, .github/,
#      CHANGELOG.md). Anything else is never touched.
#   2. Explicit `git rm` denylist for paths that are gitignored on dev
#      but might leak into main if a contributor ever stages them by
#      hand, plus dev-only paths like CLAUDE.md and tests/ that have
#      historically been kept off main and must STAY off.
#
# Pre-step: regenerates docs/assets/header.{svg,png} via
# dev/scripts/update-header.py so the README header always matches
# the version in pyproject.toml at release time. Auto-commits the
# regen to dev before syncing to main.
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

# === Pre-step: regenerate the release header asset ====================
# Run on dev so the regenerated PNG/SVG flow into main via the
# docs/ checkout. If the header changed, commit it on dev so the
# main-side checkout sees the new version. Auto-pushes dev when a
# regen lands so origin/dev tracks reality before main is updated.
echo "Regenerating release header..."
RELEASE_VERSION="$(python -c "import tomllib; \
print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])" 2>/dev/null \
    || echo unknown)"
if [ -x dev/scripts/update-header.py ]; then
    if ! python dev/scripts/update-header.py; then
        echo "ERROR: header regeneration failed. Fix update-header.py first."
        exit 1
    fi
    # Bump the README's cache-buster query string to match the new
    # version. README uses ``header.png?v=X.Y.Z`` so browsers and
    # GitHub's image proxy treat each release's image as a fresh
    # URL — without this, viewers see the previous release's PNG
    # cached in their browser even after the new commit lands.
    if [ "$RELEASE_VERSION" != "unknown" ] && [ -f README.md ]; then
        sed -i \
            "s|header\.png?v=[0-9.]*|header.png?v=${RELEASE_VERSION}|g; \
             s|header\.png\"|header.png?v=${RELEASE_VERSION}\"|g" \
            README.md
    fi
    # Commit any header artifact OR README cache-buster change.
    if ! git diff --quiet docs/assets/header.svg docs/assets/header.png README.md 2>/dev/null; then
        git add docs/assets/header.svg docs/assets/header.png README.md
        git commit -m "release: regenerate header + bump README cache-buster for v${RELEASE_VERSION}"
        git push origin dev
        echo "  header + README cache-buster updated + pushed to origin/dev"
    else
        echo "  header + cache-buster already current — no commit needed"
    fi
else
    echo "  skipped (dev/scripts/update-header.py not executable)"
fi

echo ""
echo "Releasing dev → main..."

# Save the dev commit hash for the message
DEV_SHA=$(git rev-parse --short HEAD)

git checkout main

# Clean public-facing directories on main before syncing from dev.
# This ensures renamed/deleted files don't linger on main.
git rm -rq src/ docs/ 2>/dev/null || true

# Checkout all public-facing files from dev. Tests are intentionally
# NOT synced — the pre-push hook in dev/scripts/setup-hooks.sh treats
# tests/ as dev-only, so the public repo ships source + docs only.
git checkout dev -- src/
git checkout dev -- docs/ 2>/dev/null || true
git checkout dev -- pyproject.toml
git checkout dev -- README.md
git checkout dev -- LICENSE
git checkout dev -- .gitignore
git checkout dev -- .github/ 2>/dev/null || true
git checkout dev -- CHANGELOG.md 2>/dev/null || true

# Belt-and-braces: explicitly remove every path that is dev-only or
# is local IDE / scratch / build state. The allowlist above already
# means we don't *check out* these paths — but if any past commit
# left them on main, or a future contributor adds a checkout line by
# mistake, this denylist scrubs them on every release.
#
# Categories:
#   - Dev tree:           dev/, packages/, tui/
#   - Stale docs subdirs: docs/tutorials/, docs/plans/
#   - Internal-only docs: CLAUDE.md (project guide for Claude Code,
#                         not for public consumption)
#   - Test tree:          tests/ (kept dev-only by convention)
#   - IDE / scratch:      .claude/, .vscode/, .idea/, .worktrees/,
#                         .pytest_cache/, .ruff_cache/, .mypy_cache/
#   - Build artefacts:    dist/, build/, *.egg-info
git rm -rq dev/ 2>/dev/null || true
git rm -rq docs/tutorials/ 2>/dev/null || true
git rm -rq docs/plans/ 2>/dev/null || true
git rm -rq packages/ 2>/dev/null || true
git rm -rq tui/ 2>/dev/null || true
git rm -q CLAUDE.md 2>/dev/null || true
git rm -rq tests/ 2>/dev/null || true
git rm -rq .claude/ 2>/dev/null || true
git rm -rq .vscode/ 2>/dev/null || true
git rm -rq .idea/ 2>/dev/null || true
git rm -rq .worktrees/ 2>/dev/null || true
git rm -rq .pytest_cache/ 2>/dev/null || true
git rm -rq .ruff_cache/ 2>/dev/null || true
git rm -rq .mypy_cache/ 2>/dev/null || true
git rm -rq dist/ 2>/dev/null || true
git rm -rq build/ 2>/dev/null || true
# *.egg-info is a glob — git rm -r doesn't expand it, list explicitly
# below if any specific egg-info ever lands on main (none today).

# Stage everything
git add -A

# Final safety check: warn if any dev-marker path slipped through
# anyway. This is a tripwire, not a hard error — if it fires, the
# allowlist or denylist needs another entry.
LEAKED=$(git diff --cached --name-only | grep -E '^(dev/|tests/|CLAUDE\.md$|\.claude/|\.vscode/|\.idea/|\.worktrees/|packages/|tui/|dist/|build/)' || true)
if [ -n "$LEAKED" ]; then
    echo "ERROR: dev-only paths leaked into the main staging area:"
    echo "$LEAKED" | sed 's/^/  /'
    echo "Aborting before commit. Update release-to-main.sh's denylist."
    git reset --hard HEAD
    git checkout dev
    exit 1
fi

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
