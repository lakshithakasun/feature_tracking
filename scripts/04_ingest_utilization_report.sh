#!/usr/bin/env bash
# =============================================================================
# Step 4: Ingest a feature utilization report from a customer deployment
# The product sends this periodically (e.g. monthly) after step 2 and 3.
#
# Prerequisites:
#   - Catalog must be ingested (step 1)
#   - Customer must be registered (step 2)
#   - Deployment must be registered (step 3)
#
# Usage:
#   ./04_ingest_utilization_report.sh                          # uses sample file
#   ./04_ingest_utilization_report.sh /path/to/report.yaml    # custom file
# =============================================================================

set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8001}"
REPORT_FILE="${1:-$(dirname "$0")/sample_utilization_report.yaml}"

if [[ ! -f "$REPORT_FILE" ]]; then
  echo "Error: report file not found: $REPORT_FILE" >&2
  exit 1
fi

echo "Ingesting utilization report from: $REPORT_FILE"
echo "---"

curl -s -X POST "$API_BASE/utilization/reports" \
  -F "file=@$REPORT_FILE" | python3 -m json.tool
