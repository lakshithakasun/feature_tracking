#!/usr/bin/env bash
# =============================================================================
# Generate the main demo HTML reports
#
# Usage:
#   bash scripts/generate_demo_reports.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

echo "Generating Technical Owner report ..."
python3 scripts/08_report_account_manager.py --customer acme-corp --out reports/technical_owner_acme.html

echo "Generating Regional Managers report ..."
python3 scripts/09_report_regional_gm.py --out reports/regional_managers.html

echo "Generating Customer Success report ..."
python3 scripts/11_report_customer_success.py --out reports/customer_success.html

echo "Generating Product Development report ..."
python3 scripts/12_report_product_dev.py --product identity-server --out reports/product_dev.html

echo ""
echo "Done. Reports were written to the reports/ directory."
