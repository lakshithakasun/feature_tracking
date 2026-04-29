#!/usr/bin/env bash
# =============================================================================
# Step 3: Register a customer deployment
# Links a customer to a specific product version from the catalog.
# Run once per deployment (customer + product version + environment).
#
# Usage:
#   ./03_register_deployment.sh                       # uses defaults below
#   DEPLOYMENT_ID=globex-prod CUSTOMER_ID=globex ./03_register_deployment.sh
# =============================================================================

set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8001}"

DEPLOYMENT_ID="${DEPLOYMENT_ID:-acme-corp-prod-us-74-1}"
CUSTOMER_ID="${CUSTOMER_ID:-acme-corp-74}"
PRODUCT_ID="${PRODUCT_ID:-identity-server}"
VERSION="${VERSION:-7.3.0}"
ENVIRONMENT="${ENVIRONMENT:-prod}"

echo "Registering deployment: $DEPLOYMENT_ID"
echo "  customer : $CUSTOMER_ID"
echo "  product  : $PRODUCT_ID v$VERSION"
echo "  env      : $ENVIRONMENT"
echo "---"

curl -s -X POST "$API_BASE/deployments" \
  -H "Content-Type: application/json" \
  -d "{
    \"id\": \"$DEPLOYMENT_ID\",
    \"customer_id\": \"$CUSTOMER_ID\",
    \"product_id\": \"$PRODUCT_ID\",
    \"version\": \"$VERSION\",
    \"environment\": \"$ENVIRONMENT\"
  }" | python3 -m json.tool
