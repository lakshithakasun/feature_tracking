#!/usr/bin/env bash
# =============================================================================
# Bootstrap a local developer environment with fewer manual steps
#
# What it does:
#   1. Runs scripts/setup_local.sh to create .venv and install Python deps
#   2. Creates the PostgreSQL database if local tools are available
#   3. Prints the exact DATABASE_URL export command to use
#
# Usage:
#   bash scripts/bootstrap_local.sh
#   DB_NAME=my_db DB_USER=postgres bash scripts/bootstrap_local.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DB_NAME="${DB_NAME:-feature_tracking}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-postgres}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

cd "$ROOT_DIR"

bash scripts/setup_local.sh

echo ""
echo "Checking local PostgreSQL tooling ..."

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is not installed or not on PATH."
  echo "Install PostgreSQL client tools, create database '$DB_NAME', then export:"
  echo "export DATABASE_URL=\"postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME\""
  exit 0
fi

if ! command -v createdb >/dev/null 2>&1; then
  echo "createdb is not installed or not on PATH."
  echo "Create database '$DB_NAME' manually, then export:"
  echo "export DATABASE_URL=\"postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME\""
  exit 0
fi

if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  echo "Database '$DB_NAME' already exists."
else
  echo "Creating database '$DB_NAME' ..."
  createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME"
fi

echo ""
echo "Bootstrap complete."
echo ""
echo "Next commands:"
echo "export DATABASE_URL=\"postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME\""
echo "bash scripts/run_local.sh"
echo "bash scripts/00_seed_test_data.sh"
echo ""
echo "Then open:"
echo "  Primary explorer:     http://127.0.0.1:8001/views/feature-utilization"
