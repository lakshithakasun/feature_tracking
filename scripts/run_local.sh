#!/usr/bin/env bash
# =============================================================================
# Run the FastAPI application locally
#
# Usage:
#   bash scripts/run_local.sh
#   PORT=8002 bash scripts/run_local.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PORT="${PORT:-8001}"

cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/uvicorn" ]]; then
  echo "Virtual environment is missing or uvicorn is not installed."
  echo "Run: bash scripts/setup_local.sh"
  exit 1
fi

exec .venv/bin/uvicorn app.main:app --reload --port "$PORT"
