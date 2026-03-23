#!/bin/bash
# Full development environment setup for Urika.
# Run after cloning urika-dev on a new machine.
#
# Usage: ./dev/scripts/setup-dev.sh
#
# What it does:
#   1. Adds the public remote (xkiwilabs/Urika)
#   2. Installs git hooks (pre-push safety)
#   3. Creates a Python venv and installs all dependencies
#   4. Verifies the install works
#   5. Shows next steps

set -e

echo "Setting up Urika development environment..."
echo ""

# 1. Add public remote if not already configured
if git remote get-url public &>/dev/null; then
    echo "✓ Public remote already configured"
else
    git remote add public https://github.com/xkiwilabs/Urika.git
    echo "✓ Added public remote (xkiwilabs/Urika)"
fi

# Fetch all remotes
git fetch --all --quiet
echo "✓ Fetched all remotes"

# 2. Install git hooks
./dev/scripts/setup-hooks.sh

# 3. Create venv and install
if [ ! -d ".venv" ]; then
    echo ""
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
    echo "✓ Created .venv"
fi

echo ""
echo "Installing Urika with all dependencies..."
source .venv/bin/activate
pip install -e ".[dev,agents,viz,knowledge]" --quiet
echo "✓ Installed urika + all extras"

# 4. Verify
echo ""
echo "Running verification..."
python -c "import urika; print('✓ urika imports OK')"
python -m pytest --tb=short -q 2>&1 | tail -3

# 5. Next steps
echo ""
echo "════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Activate venv:    source .venv/bin/activate"
echo "  Run tests:        pytest -v"
echo "  Launch Urika:     urika"
echo "  Release to main:  ./dev/scripts/release-to-main.sh"
echo ""
echo "  Remotes:"
echo "    origin  → urika-dev (private, daily work)"
echo "    public  → Urika (public, releases only)"
echo ""
echo "  Branches:"
echo "    dev     → development (push here)"
echo "    main    → public releases (use release script)"
echo "════════════════════════════════════════════"
