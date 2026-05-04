"""
Reporting queries for feature utilization data.
All queries join utilization data back to the product catalog so that
category, tier, and status information is always included in reports.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models


def feature_utilization_summary(db: Session, product_id: str = None, version: str = None):
    """
    All features ranked by total usage across all customers and reports.
    Optionally filter by product_id and/or version.
    """
    q = (
        db.query(
            models.CatalogFeature.code.label("feature_code"),
            models.CatalogFeature.name.label("feature_name"),
            models.CatalogCategory.name.label("category"),
            models.CatalogFeature.tier,
            models.CatalogFeature.status,
            models.ProductRelease.product_id,
            models.ProductRelease.version,
            func.sum(models.FeatureUtilization.total_count).label("total_usage"),
            func.count(func.distinct(models.Deployment.customer_id)).label("customer_count"),
            func.count(func.distinct(models.UtilizationReport.id)).label("report_count"),
        )
        .join(models.FeatureUtilization, models.FeatureUtilization.catalog_feature_id == models.CatalogFeature.id)
        .join(models.UtilizationReport, models.UtilizationReport.id == models.FeatureUtilization.report_id)
        .join(models.Deployment, models.Deployment.id == models.UtilizationReport.deployment_id)
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
        .join(
            models.CatalogCategory,
            (models.CatalogCategory.code == models.CatalogFeature.category_code) &
            (models.CatalogCategory.product_release_id == models.CatalogFeature.product_release_id),
        )
        .group_by(
            models.CatalogFeature.id,
            models.CatalogCategory.name,
            models.ProductRelease.product_id,
            models.ProductRelease.version,
        )
        .filter(models.FeatureUtilization.total_count > 0)
    )
    if product_id:
        q = q.filter(models.ProductRelease.product_id == product_id)
    if version:
        q = q.filter(models.ProductRelease.version == version)

    return q.order_by(func.sum(models.FeatureUtilization.total_count).desc()).all()


def utilization_by_category(db: Session, product_id: str = None, version: str = None):
    """
    Feature usage rolled up by category — total events and number of
    active features per category.
    """
    q = (
        db.query(
            models.CatalogCategory.code.label("category_code"),
            models.CatalogCategory.name.label("category_name"),
            models.ProductRelease.product_id,
            models.ProductRelease.version,
            func.count(func.distinct(models.CatalogFeature.id)).label("active_features"),
            func.sum(models.FeatureUtilization.total_count).label("total_usage"),
            func.count(func.distinct(models.Deployment.customer_id)).label("customer_count"),
        )
        .join(
            models.CatalogFeature,
            (models.CatalogFeature.category_code == models.CatalogCategory.code) &
            (models.CatalogFeature.product_release_id == models.CatalogCategory.product_release_id),
        )
        .join(models.FeatureUtilization, models.FeatureUtilization.catalog_feature_id == models.CatalogFeature.id)
        .join(models.UtilizationReport, models.UtilizationReport.id == models.FeatureUtilization.report_id)
        .join(models.Deployment, models.Deployment.id == models.UtilizationReport.deployment_id)
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogCategory.product_release_id)
        .group_by(
            models.CatalogCategory.id,
            models.ProductRelease.product_id,
            models.ProductRelease.version,
        )
        .filter(models.FeatureUtilization.total_count > 0)
    )
    if product_id:
        q = q.filter(models.ProductRelease.product_id == product_id)
    if version:
        q = q.filter(models.ProductRelease.version == version)

    return q.order_by(func.sum(models.FeatureUtilization.total_count).desc()).all()


def customer_feature_usage(db: Session, customer_id: str):
    """
    All feature utilization for a specific customer across all their deployments
    and reporting periods.
    """
    return (
        db.query(
            models.Customer.name.label("customer_name"),
            models.Deployment.id.label("deployment_id"),
            models.Deployment.environment,
            models.ProductRelease.product_id,
            models.ProductRelease.version,
            models.UtilizationReport.report_from,
            models.UtilizationReport.report_to,
            models.CatalogFeature.code.label("feature_code"),
            models.CatalogFeature.name.label("feature_name"),
            models.CatalogCategory.name.label("category"),
            models.FeatureUtilization.total_count,
            models.FeatureUtilization.dimension_breakdown,
        )
        .join(models.Deployment, models.Deployment.customer_id == models.Customer.id)
        .join(models.UtilizationReport, models.UtilizationReport.deployment_id == models.Deployment.id)
        .join(models.FeatureUtilization, models.FeatureUtilization.report_id == models.UtilizationReport.id)
        .join(models.CatalogFeature, models.CatalogFeature.id == models.FeatureUtilization.catalog_feature_id)
        .join(
            models.CatalogCategory,
            (models.CatalogCategory.code == models.CatalogFeature.category_code) &
            (models.CatalogCategory.product_release_id == models.CatalogFeature.product_release_id),
        )
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
        .filter(models.Customer.id == customer_id)
        .order_by(
            models.Deployment.id,
            models.UtilizationReport.report_from,
            models.FeatureUtilization.total_count.desc(),
        )
        .all()
    )


def catalog_coverage(db: Session, product_id: str, version: str):
    """
    For every feature in the catalog, show whether it has any utilization data.
    Useful for identifying unused/untested features.
    """
    return (
        db.query(
            models.CatalogFeature.code.label("feature_code"),
            models.CatalogFeature.name.label("feature_name"),
            models.CatalogCategory.name.label("category"),
            models.CatalogFeature.tier,
            models.CatalogFeature.status,
            models.CatalogFeature.introduced_in,
            func.coalesce(func.sum(models.FeatureUtilization.total_count), 0).label("total_usage"),
            func.count(models.FeatureUtilization.id).label("report_count"),
        )
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
        .join(
            models.CatalogCategory,
            (models.CatalogCategory.code == models.CatalogFeature.category_code) &
            (models.CatalogCategory.product_release_id == models.CatalogFeature.product_release_id),
        )
        .outerjoin(models.FeatureUtilization, models.FeatureUtilization.catalog_feature_id == models.CatalogFeature.id)
        .filter(
            models.ProductRelease.product_id == product_id,
            models.ProductRelease.version == version,
        )
        .group_by(models.CatalogFeature.id, models.CatalogCategory.name)
        .order_by(models.CatalogCategory.name, models.CatalogFeature.name)
        .all()
    )


def dashboard_summary(db: Session, product_id: str = None, version: str = None):
    """
    Executive summary stats. When product_id + version are supplied the stats
    are scoped to that release only; otherwise returns cross-version totals.
    """
    # Base release filter used across all scoped queries
    def release_filter(q):
        if product_id:
            q = q.filter(models.ProductRelease.product_id == product_id)
        if version:
            q = q.filter(models.ProductRelease.version == version)
        return q

    # Customers that have at least one deployment for this release
    cust_q = (
        db.query(func.count(func.distinct(models.Customer.id)))
        .join(models.Deployment, models.Deployment.customer_id == models.Customer.id)
        .join(models.ProductRelease, models.ProductRelease.id == models.Deployment.product_release_id)
    )
    total_customers = release_filter(cust_q).scalar()

    dep_q = (
        db.query(func.count(models.Deployment.id))
        .join(models.ProductRelease, models.ProductRelease.id == models.Deployment.product_release_id)
    )
    total_deployments = release_filter(dep_q).scalar()

    rep_q = (
        db.query(func.count(models.UtilizationReport.id))
        .join(models.Deployment, models.Deployment.id == models.UtilizationReport.deployment_id)
        .join(models.ProductRelease, models.ProductRelease.id == models.Deployment.product_release_id)
    )
    total_reports = release_filter(rep_q).scalar()

    events_q = (
        db.query(func.coalesce(func.sum(models.FeatureUtilization.total_count), 0))
        .join(models.UtilizationReport, models.UtilizationReport.id == models.FeatureUtilization.report_id)
        .join(models.Deployment, models.Deployment.id == models.UtilizationReport.deployment_id)
        .join(models.ProductRelease, models.ProductRelease.id == models.Deployment.product_release_id)
    )
    total_events = release_filter(events_q).scalar()

    cat_feat_q = (
        db.query(func.count(models.CatalogFeature.id))
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
    )
    total_catalog_features = release_filter(cat_feat_q).scalar()

    util_feat_q = (
        db.query(func.count(func.distinct(models.FeatureUtilization.catalog_feature_id)))
        .join(models.CatalogFeature, models.CatalogFeature.id == models.FeatureUtilization.catalog_feature_id)
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
        .filter(models.FeatureUtilization.total_count > 0)
    )
    utilized_features = release_filter(util_feat_q).scalar()

    # Top feature
    top_feat_q = (
        db.query(
            models.CatalogFeature.code,
            models.CatalogFeature.name,
            func.sum(models.FeatureUtilization.total_count).label("total"),
        )
        .join(models.FeatureUtilization, models.FeatureUtilization.catalog_feature_id == models.CatalogFeature.id)
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
        .filter(models.FeatureUtilization.total_count > 0)
        .group_by(models.CatalogFeature.id)
        .order_by(func.sum(models.FeatureUtilization.total_count).desc())
    )
    top_feature = release_filter(top_feat_q).first()

    # Top category
    top_cat_q = (
        db.query(
            models.CatalogCategory.name,
            func.sum(models.FeatureUtilization.total_count).label("total"),
        )
        .join(
            models.CatalogFeature,
            (models.CatalogFeature.category_code == models.CatalogCategory.code) &
            (models.CatalogFeature.product_release_id == models.CatalogCategory.product_release_id),
        )
        .join(models.FeatureUtilization, models.FeatureUtilization.catalog_feature_id == models.CatalogFeature.id)
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogCategory.product_release_id)
        .filter(models.FeatureUtilization.total_count > 0)
        .group_by(models.CatalogCategory.name)
        .order_by(func.sum(models.FeatureUtilization.total_count).desc())
    )
    top_category = release_filter(top_cat_q).first()

    # Per-version breakdown (always cross-version for the comparison table)
    versions = (
        db.query(
            models.ProductRelease.product_id,
            models.ProductRelease.version,
            func.count(func.distinct(models.Deployment.customer_id)).label("customers"),
            func.coalesce(func.sum(models.FeatureUtilization.total_count), 0).label("total_events"),
            func.count(func.distinct(models.FeatureUtilization.catalog_feature_id)).label("features_used"),
        )
        .join(models.Deployment, models.Deployment.product_release_id == models.ProductRelease.id)
        .join(models.UtilizationReport, models.UtilizationReport.deployment_id == models.Deployment.id)
        .join(models.FeatureUtilization, models.FeatureUtilization.report_id == models.UtilizationReport.id)
        .filter(models.FeatureUtilization.total_count > 0)
        .group_by(models.ProductRelease.id)
        .order_by(models.ProductRelease.product_id, models.ProductRelease.version)
        .all()
    )

    return {
        "total_customers": total_customers,
        "total_deployments": total_deployments,
        "total_reports": total_reports,
        "total_events": int(total_events),
        "total_catalog_features": total_catalog_features,
        "utilized_features": utilized_features,
        "utilization_rate_pct": round(utilized_features / total_catalog_features * 100, 1) if total_catalog_features else 0,
        "top_feature": {"code": top_feature.code, "name": top_feature.name, "total": int(top_feature.total)} if top_feature else None,
        "top_category": {"name": top_category.name, "total": int(top_category.total)} if top_category else None,
        "by_version": [
            {
                "product_id": v.product_id,
                "version": v.version,
                "customers": v.customers,
                "total_events": int(v.total_events),
                "features_used": v.features_used,
            }
            for v in versions
        ],
    }


def catalog_taxonomy(db: Session, product_id: str, version: str):
    """
    Full taxonomy tree: categories → sub-categories → features.
    Returns the catalog in a nested structure for presentation.
    """
    release = (
        db.query(models.ProductRelease)
        .filter_by(product_id=product_id, version=version)
        .first()
    )
    if not release:
        return None

    # All categories for this release, keyed by id
    all_cats = (
        db.query(models.CatalogCategory)
        .filter_by(product_release_id=release.id)
        .all()
    )
    cat_map = {c.id: c for c in all_cats}

    # All features keyed by category_code
    all_features = (
        db.query(
            models.CatalogFeature,
            func.coalesce(func.sum(models.FeatureUtilization.total_count), 0).label("total_usage"),
        )
        .outerjoin(models.FeatureUtilization, models.FeatureUtilization.catalog_feature_id == models.CatalogFeature.id)
        .filter(models.CatalogFeature.product_release_id == release.id)
        .group_by(models.CatalogFeature.id)
        .all()
    )

    # Group features by category_code
    features_by_cat = {}
    for f, usage in all_features:
        features_by_cat.setdefault(f.category_code, []).append({
            "code": f.code,
            "name": f.name,
            "description": f.description,
            "tier": f.tier,
            "status": f.status,
            "event_name": f.event_name,
            "event_category": f.event_category,
            "platforms": f.platforms or [],
            "total_usage": int(usage),
            "utilized": usage > 0,
        })

    def build_category(cat):
        children = [c for c in all_cats if c.parent_category_id == cat.id]
        return {
            "id": cat.code,
            "name": cat.name,
            "description": cat.description,
            "features": sorted(features_by_cat.get(cat.code, []), key=lambda x: -x["total_usage"]),
            "sub_categories": [build_category(c) for c in children],
        }

    top_level = [c for c in all_cats if c.parent_category_id is None]
    return {
        "product_id": release.product_id,
        "product_name": release.name,
        "version": release.version,
        "description": release.description,
        "team_owner": release.team_owner,
        "categories": [build_category(c) for c in top_level],
    }


def customer_list(db: Session):
    """All customers with basic info."""
    return (
        db.query(
            models.Customer.id,
            models.Customer.name,
            models.Customer.region,
            models.Customer.tier,
        )
        .order_by(models.Customer.name)
        .all()
    )


def customer_portfolio(db: Session):
    """
    All customers with utilization summary for CS management and GM views.
    Returns per-customer: id, name, region, tier, deployment_count, versions,
    features_used, total_events, last_report_to, has_no_report, deployments list.
    """
    # Aggregate stats per customer
    stats = (
        db.query(
            models.Customer.id.label("customer_id"),
            models.Customer.name.label("customer_name"),
            models.Customer.region,
            models.Customer.tier,
            func.count(func.distinct(models.Deployment.id)).label("deployment_count"),
            func.coalesce(func.sum(models.FeatureUtilization.total_count), 0).label("total_events"),
            func.count(func.distinct(models.FeatureUtilization.catalog_feature_id))
                .filter(models.FeatureUtilization.total_count > 0)
                .label("features_used"),
            func.max(models.UtilizationReport.report_to).label("last_report_to"),
        )
        .outerjoin(models.Deployment, models.Deployment.customer_id == models.Customer.id)
        .outerjoin(models.UtilizationReport, models.UtilizationReport.deployment_id == models.Deployment.id)
        .outerjoin(models.FeatureUtilization, models.FeatureUtilization.report_id == models.UtilizationReport.id)
        .group_by(models.Customer.id)
        .order_by(func.coalesce(func.sum(models.FeatureUtilization.total_count), 0).desc())
        .all()
    )

    # Deployment-level detail per customer (version + environment + is_active)
    dep_rows = (
        db.query(
            models.Customer.id.label("customer_id"),
            models.Deployment.id.label("deployment_id"),
            models.Deployment.environment,
            models.ProductRelease.product_id,
            models.ProductRelease.version,
            models.ProductRelease.is_active,
        )
        .join(models.Deployment, models.Deployment.customer_id == models.Customer.id)
        .join(models.ProductRelease, models.ProductRelease.id == models.Deployment.product_release_id)
        .order_by(models.Customer.id, models.Deployment.environment)
        .all()
    )

    deps_by_customer: dict = {}
    for d in dep_rows:
        deps_by_customer.setdefault(d.customer_id, []).append({
            "deployment_id": d.deployment_id,
            "environment": d.environment,
            "product_id": d.product_id,
            "version": d.version,
            "is_active_version": d.is_active,
        })

    result = []
    for r in stats:
        deps = deps_by_customer.get(r.customer_id, [])
        versions = sorted({d["version"] for d in deps})
        result.append({
            "customer_id": r.customer_id,
            "customer_name": r.customer_name,
            "region": r.region,
            "tier": r.tier,
            "deployment_count": r.deployment_count,
            "versions": versions,
            "features_used": r.features_used,
            "total_events": int(r.total_events),
            "last_report_to": r.last_report_to.isoformat() if r.last_report_to else None,
            "has_no_report": r.last_report_to is None,
            "deployments": deps,
        })
    return result


def regional_summary(db: Session):
    """
    Per-region summary for GM view.
    Returns: regions list (with aggregate stats) and customers list (with per-region grouping).
    """
    portfolio = customer_portfolio(db)

    from collections import defaultdict
    region_map: dict = defaultdict(lambda: {
        "customer_count": 0,
        "deployment_count": 0,
        "total_events": 0,
        "tier_breakdown": defaultdict(int),
        "versions": set(),
        "customers": [],
    })

    for c in portfolio:
        region = c["region"] or "unknown"
        rm = region_map[region]
        rm["customer_count"] += 1
        rm["deployment_count"] += c["deployment_count"]
        rm["total_events"] += c["total_events"]
        rm["tier_breakdown"][c["tier"] or "unknown"] += 1
        rm["versions"].update(c["versions"])
        rm["customers"].append(c)

    regions_out = []
    for region, rm in sorted(region_map.items()):
        regions_out.append({
            "region": region,
            "customer_count": rm["customer_count"],
            "deployment_count": rm["deployment_count"],
            "total_events": rm["total_events"],
            "tier_breakdown": dict(rm["tier_breakdown"]),
            "versions": sorted(rm["versions"]),
            "customers": sorted(rm["customers"], key=lambda x: -x["total_events"]),
        })

    return {
        "regions": regions_out,
        "all_customers": sorted(portfolio, key=lambda x: -x["total_events"]),
    }


def feature_heatmap(db: Session, product_id: str, version: str):
    """
    Feature × customer matrix for the product team view.
    Returns features list, customers list, and per-customer rows with both
    enablement and actual usage counts.
    """
    # All features in the catalog for this release
    features = (
        db.query(
            models.CatalogFeature.code,
            models.CatalogFeature.name,
            models.CatalogCategory.name.label("category"),
        )
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
        .join(
            models.CatalogCategory,
            (models.CatalogCategory.code == models.CatalogFeature.category_code) &
            (models.CatalogCategory.product_release_id == models.CatalogFeature.product_release_id),
        )
        .filter(
            models.ProductRelease.product_id == product_id,
            models.ProductRelease.version == version,
        )
        .order_by(models.CatalogCategory.name, models.CatalogFeature.name)
        .all()
    )

    # Per-feature, per-customer usage counts
    matrix_rows = (
        db.query(
            models.CatalogFeature.code.label("feature_code"),
            models.Customer.id.label("customer_id"),
            models.Customer.name.label("customer_name"),
            models.Customer.tier.label("customer_tier"),
            func.bool_or(models.FeatureUtilization.is_enabled).label("is_enabled"),
            func.sum(models.FeatureUtilization.total_count).label("total_count"),
        )
        .join(models.FeatureUtilization, models.FeatureUtilization.catalog_feature_id == models.CatalogFeature.id)
        .join(models.UtilizationReport, models.UtilizationReport.id == models.FeatureUtilization.report_id)
        .join(models.Deployment, models.Deployment.id == models.UtilizationReport.deployment_id)
        .join(models.Customer, models.Customer.id == models.Deployment.customer_id)
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
        .filter(
            models.ProductRelease.product_id == product_id,
            models.ProductRelease.version == version,
        )
        .group_by(models.CatalogFeature.code, models.Customer.id)
        .all()
    )

    # Distinct customers from the matrix
    seen_customers: dict = {}
    for r in matrix_rows:
        if r.customer_id not in seen_customers:
            seen_customers[r.customer_id] = {"id": r.customer_id, "name": r.customer_name, "tier": r.customer_tier}

    return {
        "features": [{"code": f.code, "name": f.name, "category": f.category} for f in features],
        "customers": list(seen_customers.values()),
        "matrix": [
            {
                "feature_code": r.feature_code,
                "customer_id": r.customer_id,
                "is_enabled": bool(r.is_enabled),
                "total_count": int(r.total_count),
            }
            for r in matrix_rows
        ],
    }


def dimension_breakdown_all(db: Session, product_id: str, version: str):
    """
    For each feature in the catalog, aggregate dimension_breakdown across all
    customers. Returns per-feature dimension totals for the product team view.
    """
    rows = (
        db.query(
            models.CatalogFeature.code.label("feature_code"),
            models.CatalogFeature.name.label("feature_name"),
            models.CatalogCategory.name.label("category"),
            models.FeatureUtilization.dimension_breakdown,
        )
        .join(models.FeatureUtilization, models.FeatureUtilization.catalog_feature_id == models.CatalogFeature.id)
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
        .join(
            models.CatalogCategory,
            (models.CatalogCategory.code == models.CatalogFeature.category_code) &
            (models.CatalogCategory.product_release_id == models.CatalogFeature.product_release_id),
        )
        .filter(
            models.ProductRelease.product_id == product_id,
            models.ProductRelease.version == version,
        )
        .all()
    )

    from collections import defaultdict
    features: dict = {}
    for r in rows:
        if r.feature_code not in features:
            features[r.feature_code] = {
                "feature_code": r.feature_code,
                "feature_name": r.feature_name,
                "category": r.category,
                "dimensions": defaultdict(lambda: defaultdict(int)),
            }
        if r.dimension_breakdown and isinstance(r.dimension_breakdown, dict):
            for dim_key, dim_val in r.dimension_breakdown.items():
                if isinstance(dim_val, dict):
                    for value, count in dim_val.items():
                        features[r.feature_code]["dimensions"][dim_key][value] += int(count or 0)
                else:
                    features[r.feature_code]["dimensions"][dim_key][str(dim_val)] += 1

    result = []
    for f in features.values():
        result.append({
            "feature_code": f["feature_code"],
            "feature_name": f["feature_name"],
            "category": f["category"],
            "dimensions": {k: dict(v) for k, v in f["dimensions"].items()},
        })
    return sorted(result, key=lambda x: x["category"])


def feature_customer_breakdown(
    db: Session,
    feature_code: str,
    product_id: str = None,
    version: str = None,
    customer_id: str = None,
):
    """
    For a specific feature, show usage counts per customer with dimension breakdown.
    """
    q = (
        db.query(
            models.Customer.id.label("customer_id"),
            models.Customer.name.label("customer_name"),
            models.Customer.region.label("customer_region"),
            models.Customer.tier.label("customer_tier"),
            models.Deployment.id.label("deployment_id"),
            models.Deployment.environment,
            models.ProductRelease.version,
            models.UtilizationReport.report_from,
            models.UtilizationReport.report_to,
            models.FeatureUtilization.is_enabled,
            models.FeatureUtilization.total_count,
            models.FeatureUtilization.dimension_breakdown,
        )
        .join(models.Deployment, models.Deployment.customer_id == models.Customer.id)
        .join(models.UtilizationReport, models.UtilizationReport.deployment_id == models.Deployment.id)
        .join(models.FeatureUtilization, models.FeatureUtilization.report_id == models.UtilizationReport.id)
        .join(models.CatalogFeature, models.CatalogFeature.id == models.FeatureUtilization.catalog_feature_id)
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
        .filter(models.CatalogFeature.code == feature_code)
    )
    if product_id:
        q = q.filter(models.ProductRelease.product_id == product_id)
    if version:
        q = q.filter(models.ProductRelease.version == version)
    if customer_id:
        q = q.filter(models.Customer.id == customer_id)

    return q.order_by(models.FeatureUtilization.total_count.desc()).all()
