from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.database import Base, engine, get_session
from app.report_views import (
    render_customer_success,
    render_feature_detail,
    render_feature_utilization,
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
def report_launcher():
    return RedirectResponse(url="/views/feature-utilization", status_code=307)


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


@app.get("/views/feature-utilization", response_class=HTMLResponse)
def view_feature_utilization(
    request: Request,
    product_id: str = None,
    version: str = None,
    customer_id: str = None,
    region: str = None,
    customer_tier: str = None,
    db: Session = Depends(get_session),
):
    return render_feature_utilization(
        db,
        _api_base_from_request(request),
        product_id=product_id,
        version=version,
        customer_id=customer_id,
        region=region,
        customer_tier=customer_tier,
    )


@app.get("/views/feature-utilization/detail", response_class=HTMLResponse)
def view_feature_utilization_detail(
    request: Request,
    product_id: str,
    feature_code: str,
    version: str = None,
    customer_id: str = None,
    region: str = None,
    customer_tier: str = None,
    db: Session = Depends(get_session),
):
    return render_feature_detail(
        db,
        _api_base_from_request(request),
        product_id=product_id,
        feature_code=feature_code,
        version=version,
        customer_id=customer_id,
        region=region,
        customer_tier=customer_tier,
    )


@app.get("/views/customer-success", response_class=HTMLResponse)
def view_customer_success(
    request: Request,
    product_id: str = None,
    version: str = None,
    region: str = None,
    customer_tier: str = None,
):
    return render_customer_success(
        _api_base_from_request(request),
        product_id=product_id,
        version=version,
        region=region,
        customer_tier=customer_tier,
    )


@app.get("/views/regional", response_class=HTMLResponse)
def view_regional(request: Request, region: str = None):
    return render_regional(_api_base_from_request(request), region=region)


@app.get("/views/technical-owner", response_class=HTMLResponse)
def view_technical_owner(request: Request, customer_id: str, product_id: str | None = None):
    return render_technical_owner(_api_base_from_request(request), customer_id, product_id=product_id)


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
