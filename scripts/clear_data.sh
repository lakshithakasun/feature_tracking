#!/usr/bin/env bash
# =============================================================================
# Clear all data from the database, resetting all sequences.
# Schema (tables, indexes, columns) is preserved.
#
# Usage:
#   bash scripts/clear_data.sh              # prompts for confirmation
#   bash scripts/clear_data.sh --yes        # skip confirmation
# =============================================================================

set -euo pipefail

DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/feature_tracking}"

if [[ "${1:-}" != "--yes" ]]; then
  echo "⚠️  This will delete ALL rows from every table in: $DB_URL"
  read -r -p "   Type 'yes' to continue: " confirm
  [[ "$confirm" == "yes" ]] || { echo "Aborted."; exit 0; }
fi

echo "Clearing data..."

psql "$DB_URL" <<'SQL'
TRUNCATE TABLE
  feature_usage_event,
  feature_utilization,
  utilization_report,
  deployment,
  customer,
  feature_tracking_aggregation,
  feature_tracking_dimension,
  catalog_feature,
  catalog_category,
  product_release
RESTART IDENTITY CASCADE;
SQL

echo ""
echo "Verifying..."
psql "$DB_URL" -c "
SELECT
  'product_release'            AS \"table\", COUNT(*) FROM product_release UNION ALL
SELECT 'catalog_category',                  COUNT(*) FROM catalog_category UNION ALL
SELECT 'catalog_feature',                   COUNT(*) FROM catalog_feature  UNION ALL
SELECT 'customer',                          COUNT(*) FROM customer          UNION ALL
SELECT 'deployment',                        COUNT(*) FROM deployment        UNION ALL
SELECT 'utilization_report',               COUNT(*) FROM utilization_report UNION ALL
SELECT 'feature_utilization',              COUNT(*) FROM feature_utilization UNION ALL
SELECT 'feature_usage_event',              COUNT(*) FROM feature_usage_event;
"
echo "Done — all data cleared, sequences reset."
