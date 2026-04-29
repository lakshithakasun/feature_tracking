#!/usr/bin/env bash
# =============================================================================
# Step 1: Ingest product catalog from taxonomy YAML
# Run this once per product version release.
# =============================================================================

set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8001}"
TAXONOMY_FILE="${1:-taxonomy-7.2.yaml}"

echo "Ingesting catalog from: $TAXONOMY_FILE"
echo "---"

curl -s -X POST "$API_BASE/catalog/releases" \
  -F "file=@$TAXONOMY_FILE" | python3 -m json.tool
