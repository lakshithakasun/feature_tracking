#!/usr/bin/env bash
# =============================================================================
# Step 2: Register a customer
# Run once per customer before creating any deployments for them.
#
# Usage:
#   ./02_register_customer.sh                         # uses defaults below
#   CUSTOMER_ID=globex CUSTOMER_NAME="Globex Corp" ./02_register_customer.sh
# =============================================================================

set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8001}"

CUSTOMER_ID="${CUSTOMER_ID:-acme-corp-74}"
CUSTOMER_NAME="${CUSTOMER_NAME:-Acme Corporation 74}"
CUSTOMER_REGION="${CUSTOMER_REGION:-us-east}"
CUSTOMER_TIER="${CUSTOMER_TIER:-enterprise}"

echo "Registering customer: $CUSTOMER_ID"
echo "---"

curl -s -X POST "$API_BASE/customers" \
  -H "Content-Type: application/json" \
  -d "{
    \"id\": \"$CUSTOMER_ID\",
    \"name\": \"$CUSTOMER_NAME\",
    \"region\": \"$CUSTOMER_REGION\",
    \"tier\": \"$CUSTOMER_TIER\"
  }" | python3 -m json.tool
