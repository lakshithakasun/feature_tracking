#!/usr/bin/env bash
# =============================================================================
# Seed script — loads all test data in order
#
# Creates:
#   Catalogs  : identity-server v7.2.0, v7.3.0, apim v4.2.0, v4.3.0
#   Customers : acme-corp, globex, initech, umbrella, cyberdyne,
#               nova-finance, safesoft, pinnacle, meridian, zephyr,
#               luna-retail, northbridge-bank, orbit-health, vertex-logistics,
#               bluegrid-tech, summit-pay
#   Deployments (per customer + version):
#     acme-corp     → IS v7.2.0 prod, IS v7.3.0 prod, APIM v4.3.0 prod
#     globex        → IS v7.2.0 prod, APIM v4.2.0 prod
#     initech       → v7.2.0 prod + v7.2.0 staging
#     umbrella      → v7.3.0 prod
#     cyberdyne     → v7.3.0 prod
#     nova-finance  → v7.2.0 prod (eu-north) + v7.2.0 staging (eu-north)
#     safesoft      → v7.2.0 prod (us-east)  + v7.2.0 staging (us-east)
#     pinnacle      → v7.2.0 prod (ap-south)
#     meridian      → v7.2.0 prod (us-west)
#     zephyr        → v7.3.0 prod (eu-central) + v7.3.0 staging (eu-central)
#   Utilization reports: March 2026 baseline + a few April 2026 follow-up prod reports
#
# Usage:
#   cd /path/to/Feature_Tracking
#   bash scripts/00_seed_test_data.sh
# =============================================================================

set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8001}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Ignore 400 "already exists" errors; fail on anything unexpected
post_json() {
  local url="$1"; local body="$2"
  local resp code
  resp=$(curl -s -w "\n%{http_code}" -X POST "$API_BASE$url" \
    -H "Content-Type: application/json" -d "$body")
  code=$(printf '%s' "$resp" | tail -1)
  body_out=$(printf '%s' "$resp" | python3 -c "import sys; lines=sys.stdin.read().splitlines(); print('\n'.join(lines[:-1]))")
  if [[ "$code" == "201" || "$code" == "200" ]]; then
    echo "  OK  $url"
  elif [[ "$code" == "400" ]]; then
    echo "  SKIP $url — $(echo "$body_out" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail','already exists'))" 2>/dev/null || echo 'already exists')"
  else
    echo "  FAIL $url — HTTP $code: $body_out" >&2
    exit 1
  fi
}

post_file() {
  local url="$1"; local file="$2"
  local resp code
  resp=$(curl -s -w "\n%{http_code}" -X POST "$API_BASE$url" -F "file=@$file")
  code=$(printf '%s' "$resp" | tail -1)
  body_out=$(printf '%s' "$resp" | python3 -c "import sys; lines=sys.stdin.read().splitlines(); print('\n'.join(lines[:-1]))")
  if [[ "$code" == "201" || "$code" == "200" ]]; then
    echo "  OK  $url  ← $(basename "$file")"
  elif [[ "$code" == "400" ]]; then
    echo "  SKIP $url — $(echo "$body_out" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail','already exists'))" 2>/dev/null || echo 'already exists')"
  else
    echo "  FAIL $url — HTTP $code: $body_out" >&2
    exit 1
  fi
}

section() { echo ""; echo "── $1 ──────────────────────────────────────────────────"; }

# ── 1. PRODUCT CATALOGS ───────────────────────────────────────────────────────

section "Product Catalogs"
post_file "/catalog/releases" "$ROOT_DIR/taxonomy-7.2.yaml"
post_file "/catalog/releases" "$ROOT_DIR/taxonomy-7.3.0.yaml"
post_file "/catalog/releases" "$ROOT_DIR/taxonomy-apim-4.2.0.yaml"
post_file "/catalog/releases" "$ROOT_DIR/taxonomy-apim-4.3.0.yaml"

# ── 2. CUSTOMERS ──────────────────────────────────────────────────────────────

section "Customers"
post_json "/customers" '{"id":"acme-corp",     "name":"Acme Corporation",           "region":"us-east",     "tier":"enterprise"}'
post_json "/customers" '{"id":"globex",        "name":"Globex Corporation",         "region":"eu-west",     "tier":"premium"}'
post_json "/customers" '{"id":"initech",       "name":"Initech Systems",            "region":"ap-southeast","tier":"enterprise"}'
post_json "/customers" '{"id":"umbrella",      "name":"Umbrella Corp",              "region":"us-west",     "tier":"core"}'
post_json "/customers" '{"id":"cyberdyne",     "name":"Cyberdyne Systems",          "region":"eu-central",  "tier":"premium"}'
post_json "/customers" '{"id":"nova-finance",  "name":"Nova Financial Services",    "region":"eu-north",    "tier":"enterprise"}'
post_json "/customers" '{"id":"safesoft",      "name":"SafeSoft Technologies",      "region":"us-east",     "tier":"core"}'
post_json "/customers" '{"id":"pinnacle",      "name":"Pinnacle Healthcare",        "region":"ap-south",    "tier":"premium"}'
post_json "/customers" '{"id":"meridian",      "name":"Meridian Retail",            "region":"us-west",     "tier":"core"}'
post_json "/customers" '{"id":"zephyr",        "name":"Zephyr Logistics",           "region":"eu-central",  "tier":"premium"}'
post_json "/customers" '{"id":"luna-retail",       "name":"Luna Retail",               "region":"eu-west",     "tier":"mid-market"}'
post_json "/customers" '{"id":"northbridge-bank",  "name":"Northbridge Bank",         "region":"us-east",     "tier":"enterprise"}'
post_json "/customers" '{"id":"orbit-health",      "name":"Orbit Health",             "region":"ap-southeast","tier":"enterprise"}'
post_json "/customers" '{"id":"vertex-logistics",  "name":"Vertex Logistics",         "region":"eu-central",  "tier":"mid-market"}'
post_json "/customers" '{"id":"bluegrid-tech",     "name":"BlueGrid Tech",            "region":"us-west",     "tier":"enterprise"}'
post_json "/customers" '{"id":"summit-pay",        "name":"Summit Pay",               "region":"ap-south",    "tier":"premium"}'

# ── 3. DEPLOYMENTS ────────────────────────────────────────────────────────────

section "Deployments"
post_json "/deployments" '{"id":"acme-corp-prod-us",      "customer_id":"acme-corp",    "product_id":"identity-server","version":"7.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"acme-corp-prod-us-73",   "customer_id":"acme-corp",    "product_id":"identity-server","version":"7.3.0","environment":"prod"}'
post_json "/deployments" '{"id":"acme-corp-apim-prod-us", "customer_id":"acme-corp",    "product_id":"apim","version":"4.3.0","environment":"prod"}'
post_json "/deployments" '{"id":"globex-prod-eu",         "customer_id":"globex",       "product_id":"identity-server","version":"7.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"globex-apim-prod-eu",    "customer_id":"globex",       "product_id":"apim","version":"4.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"initech-prod-ap",        "customer_id":"initech",      "product_id":"identity-server","version":"7.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"initech-staging-ap",     "customer_id":"initech",      "product_id":"identity-server","version":"7.2.0","environment":"staging"}'
post_json "/deployments" '{"id":"umbrella-prod-us",       "customer_id":"umbrella",     "product_id":"identity-server","version":"7.3.0","environment":"prod"}'
post_json "/deployments" '{"id":"cyberdyne-prod-eu",      "customer_id":"cyberdyne",    "product_id":"identity-server","version":"7.3.0","environment":"prod"}'
post_json "/deployments" '{"id":"nova-finance-prod-eu",   "customer_id":"nova-finance", "product_id":"identity-server","version":"7.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"nova-finance-staging-eu","customer_id":"nova-finance", "product_id":"identity-server","version":"7.2.0","environment":"staging"}'
post_json "/deployments" '{"id":"safesoft-prod-us",       "customer_id":"safesoft",     "product_id":"identity-server","version":"7.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"safesoft-staging-us",    "customer_id":"safesoft",     "product_id":"identity-server","version":"7.2.0","environment":"staging"}'
post_json "/deployments" '{"id":"pinnacle-prod-ap",       "customer_id":"pinnacle",     "product_id":"identity-server","version":"7.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"meridian-prod-us",       "customer_id":"meridian",     "product_id":"identity-server","version":"7.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"zephyr-prod-eu",         "customer_id":"zephyr",       "product_id":"identity-server","version":"7.3.0","environment":"prod"}'
post_json "/deployments" '{"id":"zephyr-staging-eu",      "customer_id":"zephyr",       "product_id":"identity-server","version":"7.3.0","environment":"staging"}'
post_json "/deployments" '{"id":"luna-retail-apim-prod-eu",      "customer_id":"luna-retail",      "product_id":"apim","version":"4.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"northbridge-bank-apim-prod-us", "customer_id":"northbridge-bank", "product_id":"apim","version":"4.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"orbit-health-apim-prod-ap",     "customer_id":"orbit-health",     "product_id":"apim","version":"4.2.0","environment":"prod"}'
post_json "/deployments" '{"id":"vertex-logistics-apim-prod-eu", "customer_id":"vertex-logistics", "product_id":"apim","version":"4.3.0","environment":"prod"}'
post_json "/deployments" '{"id":"bluegrid-tech-apim-prod-us",    "customer_id":"bluegrid-tech",    "product_id":"apim","version":"4.3.0","environment":"prod"}'
post_json "/deployments" '{"id":"summit-pay-apim-prod-ap",       "customer_id":"summit-pay",       "product_id":"apim","version":"4.3.0","environment":"prod"}'

# ── 4. UTILIZATION REPORTS ────────────────────────────────────────────────────

section "Utilization Reports"
post_file "/utilization/reports" "$ROOT_DIR/scripts/sample_utilization_report.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_globex_720.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_globex_720_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_globex_apim_420.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_globex_apim_420_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_initech_720_prod.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_initech_720_prod_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_initech_720_staging.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_umbrella_730.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_cyberdyne_730.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_cyberdyne_730_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_acme_730.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_acme_730_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_acme_apim_430.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_acme_apim_430_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_nova_finance_720_prod.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_nova_finance_720_prod_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_nova_finance_720_staging.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_safesoft_720_prod.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_safesoft_720_prod_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_safesoft_720_staging.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_pinnacle_720_prod.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_pinnacle_720_prod_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_meridian_720_prod.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_meridian_720_prod_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_zephyr_730_prod.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_zephyr_730_prod_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_zephyr_730_staging.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_umbrella_730_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_luna_retail_apim_420.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_luna_retail_apim_420_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_northbridge_bank_apim_420.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_northbridge_bank_apim_420_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_orbit_health_apim_420.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_orbit_health_apim_420_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_vertex_logistics_apim_430.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_vertex_logistics_apim_430_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_bluegrid_tech_apim_430.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_bluegrid_tech_apim_430_apr.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_summit_pay_apim_430.yaml"
post_file "/utilization/reports" "$SCRIPT_DIR/seed/utilization_summit_pay_apim_430_apr.yaml"

# ── SUMMARY ───────────────────────────────────────────────────────────────────

section "Done — Database Summary"
curl -s "$API_BASE/reports/dashboard" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'  Customers        : {d[\"total_customers\"]}')
print(f'  Deployments      : {d[\"total_deployments\"]}')
print(f'  Reports ingested : {d[\"total_reports\"]}')
print(f'  Total events     : {d[\"total_events\"]:,}')
print(f'  Catalog features : {d[\"total_catalog_features\"]}')
print(f'  Features utilized: {d[\"utilized_features\"]} ({d[\"utilization_rate_pct\"]}%)')
print(f'  Top feature      : {d[\"top_feature\"][\"name\"]} ({d[\"top_feature\"][\"total\"]:,} events)')
print(f'  Top category     : {d[\"top_category\"][\"name\"]} ({d[\"top_category\"][\"total\"]:,} events)')
print()
print('  By version:')
for v in d['by_version']:
    print(f'    {v[\"product_id\"]} v{v[\"version\"]}  — {v[\"customers\"]} customers, {v[\"total_events\"]:,} events, {v[\"features_used\"]} features used')
"
echo ""
