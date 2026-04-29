from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.database import Base, engine, get_session
from app.report_views import (
    render_customer_success,
    render_product_dev,
    render_regional,
    render_technical_owner,
)
from app.parsers import (
    create_customer,
    create_deployment,
    create_release_from_taxonomy,
    create_utilization_report,
    load_taxonomy_yaml,
    load_utilization_yaml,
    record_feature_usage,
)
from app.reports import (
    catalog_coverage,
    catalog_taxonomy,
    customer_feature_usage,
    customer_list,
    customer_portfolio,
    dashboard_summary,
    dimension_breakdown_all,
    feature_customer_breakdown,
    feature_heatmap,
    feature_utilization_summary,
    regional_summary,
    utilization_by_category,
)
from app.schemas import (
    CatalogReleaseResponse,
    CustomerCreate,
    CustomerResponse,
    DeploymentCreate,
    DeploymentResponse,
    FeatureUsageEventCreate,
    UtilizationReportResponse,
)

app = FastAPI(
    title="WSO2 Feature Catalog & Usage Tracking",
    version="0.2.0",
)


def _api_base_from_request(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        # Keep existing local databases compatible with the latest report logic.
        conn.execute(text(
            "ALTER TABLE feature_utilization "
            "ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN NOT NULL DEFAULT true"
        ))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/views", response_class=HTMLResponse)
def report_launcher(request: Request, db: Session = Depends(get_session)):
    customers = customer_list(db)
    regions_payload = regional_summary(db)
    regions = sorted(region["region"] for region in regions_payload.get("regions", []))
    dashboard = dashboard_summary(db, product_id="identity-server")
    versions = sorted({
        row["version"]
        for row in dashboard.get("by_version", [])
        if row.get("product_id") == "identity-server"
    })

    customer_options = "\n".join(
        f'<option value="{c.id}"{" selected" if i == 0 else ""}>{c.name} ({c.id})</option>'
        for i, c in enumerate(customers)
    )
    region_options = "\n".join(
        f'<option value="{region}">{region}</option>'
        for region in regions
    )
    version_options = "\n".join(
        f'<option value="{version}">v{version}</option>'
        for version in versions
    )
    default_product_dev = f"{_api_base_from_request(request)}/views/product-dev?product_id=identity-server"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Report Launcher</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --surface: #ffffff;
      --ink: #162033;
      --muted: #66758a;
      --line: #dde5ee;
      --brand: #214d74;
      --brand-2: #2d6a73;
    }}
    body {{ margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--ink); }}
    .hero {{ background: linear-gradient(135deg, var(--brand), var(--brand-2)); color: white; padding: 1.6rem 1.8rem; }}
    .hero h1 {{ margin: 0 0 .4rem; font-size: 1.7rem; }}
    .hero p {{ margin: 0; opacity: .82; }}
    .layout {{ display: grid; grid-template-columns: 360px 1fr; min-height: calc(100vh - 104px); }}
    .panel {{ background: var(--surface); border-right: 1px solid var(--line); padding: 1.2rem; overflow: auto; }}
    .viewer {{ padding: 1rem; }}
    .card {{ background: #fbfdff; border: 1px solid var(--line); border-radius: 14px; padding: 1rem; margin-bottom: 1rem; }}
    .card h2 {{ font-size: 1rem; margin: 0 0 .8rem; }}
    .hint {{ color: var(--muted); font-size: .84rem; line-height: 1.5; margin-bottom: .8rem; }}
    label {{ display: block; font-size: .8rem; color: var(--muted); margin: .6rem 0 .35rem; }}
    select, button {{
      width: 100%; box-sizing: border-box; border-radius: 10px; border: 1px solid var(--line);
      padding: .7rem .8rem; font-size: .92rem; background: white;
    }}
    button {{
      background: var(--brand); color: white; border: none; font-weight: 600; cursor: pointer; margin-top: .85rem;
    }}
    button.secondary {{ background: #eef4fa; color: var(--brand); border: 1px solid #c9d7e6; }}
    iframe {{
      width: 100%; min-height: calc(100vh - 140px); border: 1px solid var(--line); border-radius: 16px;
      background: white; box-shadow: 0 10px 30px rgba(15, 23, 42, .06);
    }}
    .top-actions {{ display: grid; gap: .7rem; }}
    @media (max-width: 1100px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .panel {{ border-right: none; border-bottom: 1px solid var(--line); }}
      iframe {{ min-height: 70vh; }}
    }}
  </style>
</head>
<body>
  <div class="hero">
    <h1>Feature Tracking Report Launcher</h1>
    <p>Open any stakeholder view from one place, including version-specific, region-specific, and customer-specific reports.</p>
  </div>
  <div class="layout">
    <div class="panel">
      <div class="card">
        <h2>Product Development</h2>
        <div class="hint">Use the all-versions report for roadmap comparison, or pick a specific release for a focused product version view.</div>
        <div class="top-actions">
          <button type="button" onclick="openReport('/views/product-dev?product_id=identity-server')">Open All Versions</button>
        </div>
        <label for="pd-version">Version-specific view</label>
        <select id="pd-version">
          <option value="">Select version</option>
          {version_options}
        </select>
        <button type="button" class="secondary" onclick="openProductVersion()">Open Version View</button>
      </div>

      <div class="card">
        <h2>Customer Success</h2>
        <div class="hint">Business-facing health, underutilization, churn signals, and adoption growth opportunities.</div>
        <button type="button" onclick="openReport('/views/customer-success')">Open Customer Success Report</button>
      </div>

      <div class="card">
        <h2>Regional Managers</h2>
        <div class="hint">Open the comparative all-regions dashboard, or pick a single region for a focused regional operating view.</div>
        <div class="top-actions">
          <button type="button" onclick="openReport('/views/regional')">Open All Regions</button>
        </div>
        <label for="region">Region-specific view</label>
        <select id="region">
          <option value="">Select region</option>
          {region_options}
        </select>
        <button type="button" class="secondary" onclick="openRegion()">Open Region View</button>
      </div>

      <div class="card">
        <h2>Technical Owner</h2>
        <div class="hint">Open the account-specific deployment optimization view for a technical owner or solutions architect.</div>
        <label for="customer">Customer</label>
        <select id="customer">
          {customer_options}
        </select>
        <button type="button" onclick="openCustomer()">Open Technical Owner View</button>
      </div>
    </div>

    <div class="viewer">
      <iframe id="reportFrame" src="{default_product_dev}" title="Report Viewer"></iframe>
    </div>
  </div>

  <script>
    function openReport(path) {{
      document.getElementById('reportFrame').src = path;
    }}
    function openProductVersion() {{
      const version = document.getElementById('pd-version').value;
      if (!version) return;
      openReport('/views/product-dev?product_id=identity-server&version=' + encodeURIComponent(version));
    }}
    function openRegion() {{
      const region = document.getElementById('region').value;
      if (!region) return;
      openReport('/views/regional?region=' + encodeURIComponent(region));
    }}
    function openCustomer() {{
      const customer = document.getElementById('customer').value;
      if (!customer) {{
        alert('Select a customer first to open the Technical Owner view.');
        return;
      }}
      openReport('/views/technical-owner?customer_id=' + encodeURIComponent(customer));
    }}
  </script>
</body>
</html>"""


# ── PRODUCT CATALOG ───────────────────────────────────────────────────────────

@app.post("/catalog/releases", response_model=CatalogReleaseResponse, status_code=201)
def ingest_catalog_release(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    """
    Ingest a product taxonomy YAML to register a new product release in the catalog.
    Called once per product version release by the product team.
    """
    try:
        content = file.file.read().decode("utf-8")
        taxonomy = load_taxonomy_yaml(content)
        release = create_release_from_taxonomy(db, taxonomy, source_file=file.filename)
        return CatalogReleaseResponse(
            product_id=release.product_id,
            version=release.version,
            name=release.name,
            description=release.description,
            team_owner=release.team_owner,
            category=release.category,
            is_active=release.is_active,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── CUSTOMER MANAGEMENT ───────────────────────────────────────────────────────

@app.post("/customers", response_model=CustomerResponse, status_code=201)
def register_customer(payload: CustomerCreate, db: Session = Depends(get_session)):
    """Register a new customer. Must exist before deployments can be created."""
    try:
        customer = create_customer(db, payload)
        return CustomerResponse(
            id=customer.id,
            name=customer.name,
            region=customer.region,
            tier=customer.tier,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/customers")
def list_customers(db: Session = Depends(get_session)):
    """List all registered customers."""
    rows = customer_list(db)
    return [{"id": r.id, "name": r.name, "region": r.region, "tier": r.tier} for r in rows]


@app.get("/customers/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: str, db: Session = Depends(get_session)):
    customer = db.query(models.Customer).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found")
    return CustomerResponse(id=customer.id, name=customer.name, region=customer.region, tier=customer.tier)


# ── DEPLOYMENT MANAGEMENT ─────────────────────────────────────────────────────

@app.post("/deployments", response_model=DeploymentResponse, status_code=201)
def register_deployment(payload: DeploymentCreate, db: Session = Depends(get_session)):
    """
    Register a customer deployment of a specific product version.
    Links a customer to a product release from the catalog.
    Must exist before utilization reports can be submitted.
    """
    try:
        deployment = create_deployment(db, payload)
        return DeploymentResponse(
            id=deployment.id,
            customer_id=deployment.customer_id,
            product_release_id=deployment.product_release_id,
            environment=deployment.environment,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/deployments/{deployment_id}", response_model=DeploymentResponse)
def get_deployment(deployment_id: str, db: Session = Depends(get_session)):
    d = db.query(models.Deployment).filter_by(id=deployment_id).first()
    if not d:
        raise HTTPException(status_code=404, detail=f"Deployment '{deployment_id}' not found")
    return DeploymentResponse(id=d.id, customer_id=d.customer_id, product_release_id=d.product_release_id, environment=d.environment)


# ── UTILIZATION REPORTING ─────────────────────────────────────────────────────

@app.post("/utilization/reports", response_model=UtilizationReportResponse, status_code=201)
def ingest_utilization_report(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    """
    Ingest a feature utilization report from a customer deployment.

    The product sends a YAML that extends the taxonomy format with:
      - deployment: { id, customer_id }
      - report:     { from, to }
      - Per-feature utilization: { total_count, dimension_breakdown }

    Each feature_utilization row is linked to catalog_feature for
    catalog ↔ utilization mapping queries.
    """
    try:
        content = file.file.read().decode("utf-8")
        data = load_utilization_yaml(content)
        report, features_recorded = create_utilization_report(db, data, source_file=file.filename)
        return UtilizationReportResponse(
            id=report.id,
            deployment_id=report.deployment_id,
            customer_id=report.deployment.customer_id,
            product_id=report.deployment.release.product_id,
            version=report.deployment.release.version,
            report_from=report.report_from,
            report_to=report.report_to,
            features_recorded=features_recorded,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── REPORTS ───────────────────────────────────────────────────────────────────

@app.get("/reports/dashboard")
def report_dashboard(
    product_id: str = None,
    version: str = None,
    db: Session = Depends(get_session),
):
    """Executive summary scoped to a product+version, or global if no filters given."""
    return dashboard_summary(db, product_id=product_id, version=version)


@app.get("/reports/catalog/taxonomy")
def report_catalog_taxonomy(product_id: str, version: str, db: Session = Depends(get_session)):
    """Full taxonomy tree — categories → sub-categories → features with utilization data."""
    result = catalog_taxonomy(db, product_id=product_id, version=version)
    if not result:
        raise HTTPException(status_code=404, detail=f"No catalog found for {product_id} v{version}")
    return result


@app.get("/reports/features/summary")
def report_feature_summary(
    product_id: str = None,
    version: str = None,
    db: Session = Depends(get_session),
):
    """
    All features ranked by total usage across all customers and reports.
    Each row includes category, tier, customer count, and total event count.
    """
    rows = feature_utilization_summary(db, product_id=product_id, version=version)
    return [
        {
            "feature_code": r.feature_code,
            "feature_name": r.feature_name,
            "category": r.category,
            "tier": r.tier,
            "status": r.status,
            "product_id": r.product_id,
            "version": r.version,
            "total_usage": r.total_usage,
            "customer_count": r.customer_count,
            "report_count": r.report_count,
        }
        for r in rows
    ]


@app.get("/reports/features/by-category")
def report_by_category(
    product_id: str = None,
    version: str = None,
    db: Session = Depends(get_session),
):
    """Usage rolled up by feature category."""
    rows = utilization_by_category(db, product_id=product_id, version=version)
    return [
        {
            "category_code": r.category_code,
            "category_name": r.category_name,
            "product_id": r.product_id,
            "version": r.version,
            "active_features": r.active_features,
            "total_usage": r.total_usage,
            "customer_count": r.customer_count,
        }
        for r in rows
    ]


@app.get("/reports/customers/{customer_id}/features")
def report_customer_features(customer_id: str, db: Session = Depends(get_session)):
    """All feature utilization for a specific customer across all deployments and periods."""
    customer = db.query(models.Customer).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found")
    rows = customer_feature_usage(db, customer_id)
    return [
        {
            "customer_name": r.customer_name,
            "deployment_id": r.deployment_id,
            "environment": r.environment,
            "product_id": r.product_id,
            "version": r.version,
            "report_from": r.report_from,
            "report_to": r.report_to,
            "feature_code": r.feature_code,
            "feature_name": r.feature_name,
            "category": r.category,
            "total_count": r.total_count,
            "dimension_breakdown": r.dimension_breakdown,
        }
        for r in rows
    ]


@app.get("/reports/catalog/coverage")
def report_catalog_coverage(
    product_id: str,
    version: str,
    db: Session = Depends(get_session),
):
    """
    Every feature in the catalog with its utilization status.
    Shows which features are unused across all customer deployments.
    """
    rows = catalog_coverage(db, product_id=product_id, version=version)
    return [
        {
            "feature_code": r.feature_code,
            "feature_name": r.feature_name,
            "category": r.category,
            "tier": r.tier,
            "status": r.status,
            "introduced_in": r.introduced_in,
            "total_usage": r.total_usage,
            "report_count": r.report_count,
            "utilized": r.total_usage > 0,
        }
        for r in rows
    ]


@app.get("/reports/customers/portfolio")
def report_customer_portfolio(db: Session = Depends(get_session)):
    """
    All customers with deployment, version, utilization, and report-recency data.
    Used by the Customer Success management view (View 4).
    """
    return customer_portfolio(db)


@app.get("/reports/regional")
def report_regional_summary(db: Session = Depends(get_session)):
    """
    Customers grouped by region with aggregate stats and cross-region comparison.
    Used by the Regional GM view (View 2).
    """
    return regional_summary(db)


@app.get("/reports/features/heatmap")
def report_feature_heatmap(
    product_id: str,
    version: str,
    db: Session = Depends(get_session),
):
    """
    Feature × customer usage matrix for heatmap visualization.
    Used by the Product Development Team view (View 3).
    """
    return feature_heatmap(db, product_id=product_id, version=version)


@app.get("/reports/features/dimensions")
def report_dimension_breakdown(
    product_id: str,
    version: str,
    db: Session = Depends(get_session),
):
    """
    Aggregated dimension breakdown per feature across all customers.
    Used by the Product Development Team view (View 3).
    """
    return dimension_breakdown_all(db, product_id=product_id, version=version)


@app.get("/reports/features/{feature_code}/customers")
def report_feature_by_customer(feature_code: str, db: Session = Depends(get_session)):
    """For a specific feature, show usage breakdown per customer."""
    rows = feature_customer_breakdown(db, feature_code)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No utilization data for feature '{feature_code}'")
    return [
        {
            "customer_id": r.customer_id,
            "customer_name": r.customer_name,
            "customer_tier": r.customer_tier,
            "deployment_id": r.deployment_id,
            "environment": r.environment,
            "version": r.version,
            "report_from": r.report_from,
            "report_to": r.report_to,
            "total_count": r.total_count,
            "dimension_breakdown": r.dimension_breakdown,
        }
        for r in rows
    ]


@app.get("/views/product-dev", response_class=HTMLResponse)
def view_product_dev(request: Request, product_id: str = "identity-server", version: str = None):
    return render_product_dev(_api_base_from_request(request), product_id=product_id, version=version)


@app.get("/views/customer-success", response_class=HTMLResponse)
def view_customer_success(request: Request):
    return render_customer_success(_api_base_from_request(request))


@app.get("/views/regional", response_class=HTMLResponse)
def view_regional(request: Request, region: str = None):
    return render_regional(_api_base_from_request(request), region=region)


@app.get("/views/technical-owner", response_class=HTMLResponse)
def view_technical_owner(request: Request, customer_id: str):
    return render_technical_owner(_api_base_from_request(request), customer_id)


# ── REAL-TIME EVENTS ──────────────────────────────────────────────────────────

@app.post("/usage/events")
def ingest_usage_event(payload: FeatureUsageEventCreate, db: Session = Depends(get_session)):
    try:
        event = record_feature_usage(db, payload)
        return {
            "id": event.id,
            "product_release_id": event.product_release_id,
            "feature_id": event.feature_id,
            "event_name": event.event_name,
            "event_timestamp": event.event_timestamp,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
