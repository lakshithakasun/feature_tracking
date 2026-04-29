# WSO2 Product Feature Catalog and Utilization Tracking

This project defines a solution for:

1. Capturing product catalog metadata during product version releases.
2. Persisting feature taxonomy and tracking definitions from YAML release artifacts.
3. Ingesting customer feature utilization events and validating them against the catalog.
4. Supporting multiple products (for example WSO2 Identity Server, APIM, etc.).

## Architecture

- `taxonomy-*.yaml` files represent product release catalogs.
- Each release is stored as a versioned product catalog snapshot.
- Categories, sub-categories, features, dimensions and aggregation rules are all stored.
- Customer utilization events are ingested through an API and linked to a catalog release.
- The system validates feature usage events against the release taxonomy.

## Technology Stack

- Python 3.11+
- FastAPI for API endpoints
- PostgreSQL for relational catalog storage
- SQLAlchemy for ORM
- PyYAML for taxonomy parsing

## Core Data Model

- `product_release`: product metadata and release version
- `catalog_category`: catalog categories and sub-categories
- `catalog_feature`: feature definitions and tracking contract
- `feature_tracking_dimension`: event dimension schemas
- `feature_tracking_aggregation`: aggregator definitions for reporting
- `feature_usage_event`: raw customer usage events

## Getting Started

1. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

2. Create a PostgreSQL database and set `DATABASE_URL`:

```bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/feature_tracking"
```

3. Start the service:

```bash
.venv/bin/uvicorn app.main:app --reload --port 8001
```

## Common Commands

### Start the API

```bash
.venv/bin/uvicorn app.main:app --reload --port 8001
```

### Clear and reseed demo data

Clear all seeded data:

```bash
bash scripts/clear_data.sh --yes
```

Reseed all sample data:

```bash
bash scripts/00_seed_test_data.sh
```

Recommended full reset flow:

```bash
bash scripts/clear_data.sh --yes
bash scripts/00_seed_test_data.sh
```

### Load catalog data manually

Using the Python loader:

```bash
python3 scripts/load_taxonomy.py taxanomy_schema.yaml
```

Using the helper script:

```bash
bash scripts/01_ingest_catalog.sh
```

### Register customer / deployment / utilization manually

Register a customer:

```bash
bash scripts/02_register_customer.sh
```

Register a deployment:

```bash
bash scripts/03_register_deployment.sh
```

Ingest a utilization report:

```bash
bash scripts/04_ingest_utilization_report.sh
```

### Utility scripts

Run the older helper bundle:

```bash
bash scripts/05_run_reports.sh
```

Generate the generic HTML report:

```bash
python3 scripts/06_generate_html_report.py
```

Generate the schema diagram:

```bash
python3 scripts/07_generate_schema_diagram.py
```

## Report Views

### Web Launcher

Open the browser-based launcher that links to all report views:

```text
http://127.0.0.1:8001/views
```

The launcher supports:

- Product Development all versions
- Product Development for a specific version
- Customer Success Management
- Regional Managers all regions
- Regional Managers for a specific region
- Technical Owner for a specific customer

Direct launcher-backed routes:

```text
http://127.0.0.1:8001/views/product-dev?product_id=identity-server
http://127.0.0.1:8001/views/product-dev?product_id=identity-server&version=7.3.0
http://127.0.0.1:8001/views/customer-success
http://127.0.0.1:8001/views/regional
http://127.0.0.1:8001/views/regional?region=eu-west
http://127.0.0.1:8001/views/technical-owner?customer_id=umbrella
```

### View 1: Technical Owner

List customers:

```bash
python3 scripts/08_report_account_manager.py --list-customers
```

Generate a per-customer technical owner report:

```bash
python3 scripts/08_report_account_manager.py --customer umbrella
```

Custom output:

```bash
python3 scripts/08_report_account_manager.py --customer zephyr --out reports/technical_owner_zephyr.html
```

### View 2: Regional Managers

Generate the all-regions report:

```bash
python3 scripts/09_report_regional_gm.py --out reports/regional_managers.html
```

Generate a region-specific report:

```bash
python3 scripts/09_report_regional_gm.py --region eu-west --out reports/regional_eu_west.html
```

### View 3: Customer Success Management

Generate the CSM report:

```bash
python3 scripts/11_report_customer_success.py --out reports/customer_success.html
```

### View 4: Product Development Team

Generate the all-versions product report:

```bash
python3 scripts/12_report_product_dev.py --product identity-server --out reports/product_dev.html
```

Generate a version-specific product report:

```bash
python3 scripts/12_report_product_dev.py --product identity-server --version 7.3.0 --out reports/product_dev_7_3_0.html
```

## Typical Daily Flows

### Fresh demo setup

```bash
.venv/bin/uvicorn app.main:app --reload --port 8001
bash scripts/clear_data.sh --yes
bash scripts/00_seed_test_data.sh
```

### Generate all main views

```bash
python3 scripts/08_report_account_manager.py --customer umbrella --out reports/technical_owner_umbrella.html
python3 scripts/09_report_regional_gm.py --out reports/regional_managers.html
python3 scripts/11_report_customer_success.py --out reports/customer_success.html
python3 scripts/12_report_product_dev.py --product identity-server --out reports/product_dev.html
```

### Manual API examples

Ingest a taxonomy file:

```bash
curl -X POST "http://127.0.0.1:8001/catalog/releases" -F "file=@taxonomy-7.2.yaml"
```

Ingest a usage event:

```bash
curl -X POST "http://127.0.0.1:8001/usage/events" \
  -H 'Content-Type: application/json' \
  -d '{
    "product_id": "identity-server",
    "version": "7.2.0",
    "event_name": "is.sso.oidc",
    "platform": "web",
    "dimensions": {"grant_type": "authorization-code", "pkce_enabled": false, "response_type": "code"},
    "user_id": "user-123",
    "tenant_id": "tenant-abc"
  }'
```

## Extending the Solution

- Add scheduled aggregation jobs for `feature_usage_event` into `feature_usage_aggregate`.
- Add product metadata history and release status fields.
- Add support for schema validation against `feature-taxonomy-schema.pdf`.
- Add dashboards / BI views for adoption, engagement, and usage trends.
