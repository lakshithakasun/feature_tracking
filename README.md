# WSO2 Feature Catalog and Utilization Tracking

This repository contains a FastAPI-based prototype for tracking product capability catalogs, ingesting customer utilization reports, and presenting the data through stakeholder-focused HTML views and a unified feature explorer.

The current demo data includes:
- `WSO2 Identity Server`
- `WSO2 API Manager`
- multiple versions per product
- multiple customers, regions, and tiers
- interactive feature exploration and stakeholder report views

## What This Project Does

The system supports four main responsibilities:

1. Store versioned product taxonomies from YAML release files
2. Register customers and deployments for different products and environments
3. Ingest customer utilization reports in YAML format
4. Generate explorer and stakeholder-facing views for product, customer success, regional, and technical audiences

## Repository Structure

```text
app/                    FastAPI app, database models, parsing, reporting logic
db/                     SQL schema and schema diagram artifacts
docs/                   Supporting design and stakeholder documents
reports/                Generated HTML report outputs
scripts/                Seed, setup, ingestion, and report generation helpers
scripts/seed/           Demo utilization report YAMLs
taxonomy-*.yaml         Product catalog taxonomy files
utilization_report_*.yaml  Utilization report schema references
```

## Core Views

The project exposes two ways to inspect the data:

### 1. Feature Utilization Explorer

Primary landing view:

```text
http://127.0.0.1:8001/views
```

The explorer supports:
- product, version, and customer filters
- all-products scope
- clickable feature summaries
- detailed feature drill-down pages
- links back to stakeholder-specific views

### 2. Stakeholder Views

- Product Development Team
- Customer Success Management
- Regional Managers
- Technical Owner

These remain available both from the launcher and via direct routes.

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL
- `psql` client installed locally

### Fastest Setup

1. Clone the repository
2. Create a local database
3. Run the setup script:

```bash
bash scripts/setup_local.sh
```

4. Export your database connection string:

```bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/feature_tracking"
```

5. Start the API:

```bash
bash scripts/run_local.sh
```

6. In another terminal, seed demo data:

```bash
bash scripts/00_seed_test_data.sh
```

7. Open the launcher:

```text
http://127.0.0.1:8001/views
```

## Manual Setup

If you prefer not to use the setup script:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/feature_tracking"
.venv/bin/uvicorn app.main:app --reload --port 8001
```

## Environment Variables

A sample environment file is included in [.env.example](/Users/lakshithas/Work/Feature_Tracking/.env.example:1).

Common variables:

- `DATABASE_URL`
- `API_BASE`
- `PORT`

## Common Commands

### Start the API

```bash
bash scripts/run_local.sh
```

### Clear and reseed demo data

```bash
bash scripts/clear_data.sh --yes
bash scripts/00_seed_test_data.sh
```

### Generate the main demo reports

```bash
bash scripts/generate_demo_reports.sh
```

### Generate individual reports

Technical Owner:

```bash
python3 scripts/08_report_account_manager.py --customer acme-corp --out reports/technical_owner_acme.html
```

Regional Managers:

```bash
python3 scripts/09_report_regional_gm.py --out reports/regional_managers.html
python3 scripts/09_report_regional_gm.py --region eu-west --out reports/regional_eu_west.html
```

Customer Success:

```bash
python3 scripts/11_report_customer_success.py --out reports/customer_success.html
```

Product Development:

```bash
python3 scripts/12_report_product_dev.py --product identity-server --out reports/product_dev.html
python3 scripts/12_report_product_dev.py --product identity-server --version 7.3.0 --out reports/product_dev_7_3_0.html
```

### Generate schema diagram

```bash
python3 scripts/07_generate_schema_diagram.py
```

## Web Routes

Launcher:

```text
http://127.0.0.1:8001/views
```

Explorer:

```text
http://127.0.0.1:8001/views/feature-utilization
http://127.0.0.1:8001/views/feature-utilization?product_id=identity-server
http://127.0.0.1:8001/views/feature-utilization?product_id=__all__
```

Direct stakeholder routes:

```text
http://127.0.0.1:8001/views/product-dev?product_id=identity-server
http://127.0.0.1:8001/views/product-dev?product_id=identity-server&version=7.3.0
http://127.0.0.1:8001/views/customer-success
http://127.0.0.1:8001/views/regional
http://127.0.0.1:8001/views/regional?region=eu-west
http://127.0.0.1:8001/views/technical-owner?customer_id=acme-corp&product_id=identity-server
```

## Demo Data Notes

The seeded data is intentionally shaped to show:

- multiple products
- multiple versions
- version-specific adoption differences
- enabled-but-unused features
- customer health variation
- region-level growth and decline patterns
- customers using more than one product

This is especially useful when demonstrating the all-products explorer mode.

## Documentation

Supporting project documents:

- [docs/stakeholder_views.md](/Users/lakshithas/Work/Feature_Tracking/docs/stakeholder_views.md:1)
- [docs/event_capture_taxonomy.md](/Users/lakshithas/Work/Feature_Tracking/docs/event_capture_taxonomy.md:1)
- [db/schema.sql](/Users/lakshithas/Work/Feature_Tracking/db/schema.sql:1)

## Troubleshooting

### `uvicorn: command not found`

Use the setup script first, or run:

```bash
.venv/bin/uvicorn app.main:app --reload --port 8001
```

### `Address already in use`

Find the process:

```bash
lsof -i :8001
```

Stop it:

```bash
kill <PID>
```

### Reports show empty data

Make sure:
- the API is running
- the database is reachable
- demo data has been seeded

Recommended reset:

```bash
bash scripts/clear_data.sh --yes
bash scripts/00_seed_test_data.sh
```

### Explorer scope looks unexpected

Remember:
- `All Products + customer` means all products that the selected customer actually has in the seeded data
- some customers have one product
- some customers have both `Identity Server` and `APIM`

## Notes

- Some legacy files intentionally retain the historical `taxanomy` spelling to avoid breaking existing references.
- Generated HTML outputs in `reports/` are demo artifacts, not the source of truth.
- The main source of truth for setup and usage should now be this README plus the helper scripts.
