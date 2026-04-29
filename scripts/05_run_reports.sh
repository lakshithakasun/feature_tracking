#!/usr/bin/env bash
# =============================================================================
# Step 5: Query and display utilization reports
#
# Usage:
#   ./05_run_reports.sh                      # runs all reports with defaults
#   ./05_run_reports.sh summary              # feature utilization summary
#   ./05_run_reports.sh category             # usage by category
#   ./05_run_reports.sh customer acme-corp   # usage for a specific customer
#   ./05_run_reports.sh coverage             # catalog coverage (used vs unused)
#   ./05_run_reports.sh feature is.sso.oidc  # specific feature across customers
# =============================================================================

set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8001}"
PRODUCT_ID="${PRODUCT_ID:-identity-server}"
VERSION="${VERSION:-7.3.0}"

REPORT="${1:-all}"

# ── helpers ───────────────────────────────────────────────────────────────────

header() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  $1"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Print a JSON array as a plain text table. Args: columns space-separated
# Data is read from stdin.
json_table() {
  local cols="$1"
  python3 -c "
import sys, json
cols = '$cols'.split()
raw = sys.stdin.read().strip()
rows = json.loads(raw) if raw else []
if not rows:
    print('  (no data)')
    sys.exit(0)
widths = {c: max(len(c), max(len(str(r.get(c,''))) for r in rows)) for c in cols}
widths = {c: min(v, 50) for c, v in widths.items()}
fmt = '  ' + '  '.join('{:<'+str(widths[c])+'}' for c in cols)
sep = '  ' + '  '.join('-'*widths[c] for c in cols)
print(fmt.format(*cols))
print(sep)
for r in rows:
    print(fmt.format(*[str(r.get(c,''))[:widths[c]] for c in cols]))
"
}

# ── individual reports ────────────────────────────────────────────────────────

run_summary() {
  header "Feature Utilization Summary  ($PRODUCT_ID v$VERSION)"
  curl -s "$API_BASE/reports/features/summary?product_id=$PRODUCT_ID&version=$VERSION" \
    | json_table "feature_code category total_usage customer_count report_count tier status"
}

run_category() {
  header "Usage by Category  ($PRODUCT_ID v$VERSION)"
  curl -s "$API_BASE/reports/features/by-category?product_id=$PRODUCT_ID&version=$VERSION" \
    | json_table "category_name total_usage active_features customer_count version"
}

run_customer() {
  local CUSTOMER_ID="${2:-acme-corp}"
  header "Customer Feature Usage  —  $CUSTOMER_ID"
  curl -s "$API_BASE/reports/customers/$CUSTOMER_ID/features" \
    | json_table "deployment_id environment version feature_code category total_count"
}

run_coverage() {
  header "Catalog Coverage  ($PRODUCT_ID v$VERSION)"
  local json
  json=$(curl -s "$API_BASE/reports/catalog/coverage?product_id=$PRODUCT_ID&version=$VERSION")

  echo ""
  echo "  UTILIZED FEATURES:"
  echo "$json" | python3 -c "
import sys, json
rows = [r for r in json.loads(sys.stdin.read()) if r['utilized']]
cols = ['feature_code','category','total_usage','report_count','tier','status']
if not rows: print('  (none)'); sys.exit(0)
widths = {c: max(len(c), max(len(str(r.get(c,''))) for r in rows)) for c in cols}
widths = {c: min(v,48) for c,v in widths.items()}
fmt = '    ' + '  '.join('{:<'+str(widths[c])+'}' for c in cols)
sep = '    ' + '  '.join('-'*widths[c] for c in cols)
print(fmt.format(*cols)); print(sep)
[print(fmt.format(*[str(r.get(c,''))[:widths[c]] for c in cols])) for r in rows]
"

  echo ""
  echo "  UNUSED CATALOG FEATURES:"
  echo "$json" | python3 -c "
import sys, json
rows = [r for r in json.loads(sys.stdin.read()) if not r['utilized']]
cols = ['feature_code','category','tier','status']
if not rows: print('  (all features have utilization data)'); sys.exit(0)
widths = {c: max(len(c), max(len(str(r.get(c,''))) for r in rows)) for c in cols}
widths = {c: min(v,48) for c,v in widths.items()}
fmt = '    ' + '  '.join('{:<'+str(widths[c])+'}' for c in cols)
sep = '    ' + '  '.join('-'*widths[c] for c in cols)
print(fmt.format(*cols)); print(sep)
[print(fmt.format(*[str(r.get(c,''))[:widths[c]] for c in cols])) for r in rows]
"
}

run_feature() {
  local FEATURE_CODE="${2:-is.sso.oidc}"
  header "Customer Breakdown  —  $FEATURE_CODE"
  curl -s "$API_BASE/reports/features/$FEATURE_CODE/customers" \
    | json_table "customer_id customer_name customer_tier deployment_id environment version total_count"
}

# ── dispatch ──────────────────────────────────────────────────────────────────

case "$REPORT" in
  summary)  run_summary ;;
  category) run_category ;;
  customer) run_customer "$@" ;;
  coverage) run_coverage ;;
  feature)  run_feature "$@" ;;
  all)
    run_summary
    run_category
    run_customer "customer" "acme-corp"
    run_coverage
    ;;
  *)
    echo "Unknown report: $REPORT"
    echo "Usage: $0 [summary|category|customer <id>|coverage|feature <code>|all]"
    exit 1 ;;
esac

echo ""
