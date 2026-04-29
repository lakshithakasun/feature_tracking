from datetime import datetime
from typing import Dict, Optional

import yaml
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import models
from app.schemas import (
    FeatureUsageEventCreate,
    TaxonomySchema,
    UtilizationReportYAML,
)


# ── CATALOG INGESTION ─────────────────────────────────────────────────────────

def load_taxonomy_yaml(text: str) -> TaxonomySchema:
    payload = yaml.safe_load(text)
    try:
        taxonomy = TaxonomySchema(**payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid taxonomy payload: {exc}") from exc
    return taxonomy


def create_release_from_taxonomy(db: Session, taxonomy: TaxonomySchema, source_file: str) -> models.ProductRelease:
    existing = (
        db.query(models.ProductRelease)
        .filter_by(product_id=taxonomy.product.id, version=taxonomy.product.version)
        .first()
    )
    if existing:
        raise ValueError(
            f"Release already exists for product {taxonomy.product.id} version {taxonomy.product.version}"
        )

    release = models.ProductRelease(
        product_id=taxonomy.product.id,
        name=taxonomy.product.name,
        version=taxonomy.product.version,
        description=taxonomy.product.description,
        team_owner=taxonomy.product.team_owner,
        category=taxonomy.product.category,
        is_active=taxonomy.product.is_active if taxonomy.product.is_active is not None else True,
        metadata_json=taxonomy.schema,
        source_file=source_file,
        created_at=datetime.utcnow(),
    )
    db.add(release)
    db.flush()

    category_map: Dict[str, int] = {}
    for category in taxonomy.categories:
        _create_category(db, release.id, category, None, category_map)

    for feature in taxonomy.features:
        tracking = feature.tracking or {}
        availability = feature.availability or {}
        if hasattr(availability, "introduced_in"):
            introduced_in = availability.introduced_in
            deprecated_in = availability.deprecated_in
        else:
            introduced_in = None
            deprecated_in = None

        feature_record = models.CatalogFeature(
            product_release_id=release.id,
            code=feature.code,
            name=feature.name,
            description=feature.description,
            category_code=feature.category,
            tier=feature.tier,
            status=feature.status,
            introduced_in=introduced_in,
            deprecated_in=deprecated_in,
            event_name=tracking.get("event_name") or feature.code,
            event_category=tracking.get("event_category"),
            platforms=tracking.get("platforms"),
            created_at=datetime.utcnow(),
        )
        db.add(feature_record)
        db.flush()

        for dimension in tracking.get("dimensions", []):
            db.add(models.FeatureTrackingDimension(
                feature_id=feature_record.id,
                name=dimension.get("name"),
                type=dimension.get("type"),
                required=dimension.get("required", False),
                description=dimension.get("description"),
                enum_values=dimension.get("values"),
            ))

        for aggregation in tracking.get("aggregations", []):
            db.add(models.FeatureTrackingAggregation(
                feature_id=feature_record.id,
                type=aggregation.get("type"),
                label=aggregation.get("label"),
                dimension=aggregation.get("dimension"),
            ))

    db.commit()
    db.refresh(release)
    return release


def _create_category(
    db: Session,
    release_id: int,
    category: object,
    parent_id: Optional[int],
    category_map: Dict[str, int],
):
    category_record = models.CatalogCategory(
        product_release_id=release_id,
        code=category.id,
        name=category.name,
        description=category.description,
        parent_category_id=parent_id,
    )
    db.add(category_record)
    db.flush()
    category_map[category.id] = category_record.id

    for child in category.sub_categories or []:
        _create_category(db, release_id, child, category_record.id, category_map)


# ── CUSTOMER & DEPLOYMENT ─────────────────────────────────────────────────────

def create_customer(db: Session, payload) -> models.Customer:
    if db.query(models.Customer).filter_by(id=payload.id).first():
        raise ValueError(f"Customer '{payload.id}' already exists")
    customer = models.Customer(
        id=payload.id,
        name=payload.name,
        region=payload.region,
        tier=payload.tier,
        created_at=datetime.utcnow(),
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def create_deployment(db: Session, payload) -> models.Deployment:
    if not db.query(models.Customer).filter_by(id=payload.customer_id).first():
        raise ValueError(f"Customer '{payload.customer_id}' not found")

    release = (
        db.query(models.ProductRelease)
        .filter_by(product_id=payload.product_id, version=payload.version)
        .first()
    )
    if not release:
        raise ValueError(f"No catalog release found for {payload.product_id} v{payload.version}")

    if db.query(models.Deployment).filter_by(id=payload.id).first():
        raise ValueError(f"Deployment '{payload.id}' already exists")

    deployment = models.Deployment(
        id=payload.id,
        customer_id=payload.customer_id,
        product_release_id=release.id,
        environment=payload.environment,
        created_at=datetime.utcnow(),
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)
    return deployment


# ── UTILIZATION REPORT INGESTION ──────────────────────────────────────────────

def load_utilization_yaml(text: str) -> UtilizationReportYAML:
    payload = yaml.safe_load(text)
    try:
        return UtilizationReportYAML(**payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid utilization report payload: {exc}") from exc


def create_utilization_report(
    db: Session,
    data: UtilizationReportYAML,
    source_file: str,
) -> models.UtilizationReport:
    # Resolve deployment — must be pre-registered
    deployment = db.query(models.Deployment).filter_by(id=data.deployment.id).first()
    if not deployment:
        raise ValueError(
            f"Deployment '{data.deployment.id}' not found. Register it via POST /deployments first."
        )

    # Validate deployment belongs to the stated customer
    if deployment.customer_id != data.deployment.customer_id:
        raise ValueError(
            f"Deployment '{data.deployment.id}' belongs to customer "
            f"'{deployment.customer_id}', not '{data.deployment.customer_id}'"
        )

    # Resolve product release via the deployment (single source of truth)
    release = deployment.release
    if release.product_id != data.product.id or release.version != data.product.version:
        raise ValueError(
            f"Deployment '{data.deployment.id}' is registered against "
            f"{release.product_id} v{release.version}, "
            f"but report says {data.product.id} v{data.product.version}"
        )

    # Build a code→catalog_feature lookup for this release
    catalog_index: Dict[str, models.CatalogFeature] = {
        f.code: f for f in release.features
    }

    report = models.UtilizationReport(
        deployment_id=deployment.id,
        report_from=data.report.period_from,
        report_to=data.report.period_to,
        source_file=source_file,
        created_at=datetime.utcnow(),
    )
    db.add(report)
    db.flush()

    features_recorded = 0
    for entry in data.features:
        catalog_feature = catalog_index.get(entry.code)
        if catalog_feature is None:
            # Feature code not in catalog for this release — skip rather than fail
            continue

        utilization = entry.utilization
        db.add(models.FeatureUtilization(
            report_id=report.id,
            catalog_feature_id=catalog_feature.id,
            feature_code=entry.code,
            is_enabled=True,
            total_count=utilization.total_count if utilization else 0,
            dimension_breakdown=utilization.dimension_breakdown if utilization else {},
            created_at=datetime.utcnow(),
        ))
        features_recorded += 1

    db.commit()
    db.refresh(report)
    return report, features_recorded


# ── REAL-TIME EVENT INGESTION (existing) ─────────────────────────────────────

def _find_feature_by_event_name(
    db: Session, product_id: str, version: str, event_name: str
) -> Optional[models.CatalogFeature]:
    release = (
        db.query(models.ProductRelease)
        .filter_by(product_id=product_id, version=version)
        .first()
    )
    if not release:
        return None
    return (
        db.query(models.CatalogFeature)
        .filter_by(product_release_id=release.id, event_name=event_name)
        .first()
    )


def _validate_usage_event(feature: models.CatalogFeature, payload: FeatureUsageEventCreate) -> None:
    expected_dimensions = {dim.name: dim for dim in feature.dimensions}
    for name, dim in expected_dimensions.items():
        if dim.required and name not in payload.dimensions:
            raise ValueError(f"Missing required dimension: {name}")
    for name, value in payload.dimensions.items():
        dim = expected_dimensions.get(name)
        if dim and dim.type == "enum" and dim.enum_values:
            if value not in dim.enum_values:
                raise ValueError(
                    f"Invalid value for dimension {name}: {value}. Allowed: {dim.enum_values}"
                )


def record_feature_usage(db: Session, payload: FeatureUsageEventCreate) -> models.FeatureUsageEvent:
    release = (
        db.query(models.ProductRelease)
        .filter_by(product_id=payload.product_id, version=payload.version)
        .first()
    )
    if not release:
        raise ValueError(f"Release not found for {payload.product_id} version {payload.version}")

    feature = _find_feature_by_event_name(db, payload.product_id, payload.version, payload.event_name)
    if not feature:
        raise ValueError(f"Feature not found for event_name {payload.event_name}")

    _validate_usage_event(feature, payload)

    event = models.FeatureUsageEvent(
        product_release_id=release.id,
        feature_id=feature.id,
        event_name=payload.event_name,
        platform=payload.platform,
        event_timestamp=payload.event_timestamp or datetime.utcnow(),
        dimensions=payload.dimensions,
        user_id=payload.user_id,
        tenant_id=payload.tenant_id,
        raw_payload=payload.dict(exclude_none=True),
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
