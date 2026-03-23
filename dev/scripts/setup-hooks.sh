#!/bin/bash
# Install git hooks for the Urika development workflow.
# Run this after cloning urika-dev on a new machine.
#
# Usage: ./dev/scripts/setup-hooks.sh

set -e

HOOK_DIR="$(git rev-parse --show-toplevel)/.git/hooks"

cat > "$HOOK_DIR/pre-push" << 'HOOK'
#!/bin/bash
# Pre-push hook: block pushing main if dev-only files are present.
# These files should be stripped by dev/scripts/release-to-main.sh before pushing.

branch=$(git rev-parse --abbrev-ref HEAD)

if [ "$branch" != "main" ]; then
    exit 0
fi

DEV_ONLY_FILES=(
    "CLAUDE.md"
)
DEV_ONLY_DIRS=(
    "dev"
    "tests"
)

leaked=""

for f in "${DEV_ONLY_FILES[@]}"; do
    if git ls-files --error-unmatch "$f" &>/dev/null; then
        leaked="$leaked  $f\n"
    fi
done

for d in "${DEV_ONLY_DIRS[@]}"; do
    if git ls-files "$d/" 2>/dev/null | grep -q .; then
        leaked="$leaked  $d/\n"
    fi
done

if [ -n "$leaked" ]; then
    echo "BLOCKED: Dev-only files detected on main branch:"
    echo -e "$leaked"
    echo "Run ./scripts/release-to-main.sh instead of pushing directly."
    exit 1
fi

exit 0
HOOK

chmod +x "$HOOK_DIR/pre-push"
echo "Installed pre-push hook."
echo "Done. Hooks installed at $HOOK_DIR"
