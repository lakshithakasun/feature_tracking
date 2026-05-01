#!/usr/bin/env bash
# =============================================================================
# Local developer setup
#
# What it does:
#   1. Creates a local virtual environment in .venv if it does not exist
#   2. Upgrades pip
#   3. Installs Python dependencies from requirements.txt
#   4. Prints the next commands needed to start the app and seed demo data
#
# Usage:
#   bash scripts/setup_local.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Creating virtual environment in .venv ..."
  "$PYTHON_BIN" -m venv .venv
else
  echo "Virtual environment already exists at .venv"
fi

echo "Upgrading pip ..."
.venv/bin/python -m pip install --upgrade pip

echo "Installing Python dependencies ..."
.venv/bin/pip install -r requirements.txt

echo ""
echo "Setup complete."
echo ""
echo "Next steps:"
echo "1. Create a PostgreSQL database and export DATABASE_URL"
echo "   Example:"
echo "   export DATABASE_URL=\"postgresql://postgres:postgres@localhost:5432/feature_tracking\""
echo ""
echo "2. Start the API:"
echo "   bash scripts/run_local.sh"
echo ""
echo "3. Seed demo data in another terminal:"
echo "   bash scripts/00_seed_test_data.sh"
echo ""
echo "4. Open the launcher:"
echo "   http://127.0.0.1:8001/views"
