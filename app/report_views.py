from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.reports import catalog_coverage, customer_feature_usage, feature_customer_breakdown, feature_heatmap


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ALL_PRODUCTS = "__all__"


@lru_cache(maxsize=None)
def _load_script(filename: str, module_name: str):
    path = SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load report script: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_product_dev(api_base: str, product_id: str = "identity-server", version: str | None = None) -> str:
    module = _load_script("12_report_product_dev.py", "product_dev_report")
    data = module.load_data(api_base, product_id, version_filter=version)
    return module.build_html(data, product_id)


def render_customer_success(api_base: str, product_id: str | None = None, version: str | None = None, region: str | None = None) -> str:
    module = _load_script("11_report_customer_success.py", "customer_success_report")
    return module.build_html(api_base, product_id=product_id, version=version, region=region)


def render_regional(api_base: str, region: str | None = None) -> str:
    module = _load_script("09_report_regional_gm.py", "regional_managers_report")
    return module.build_html(api_base, region_filter=region)


def render_technical_owner(api_base: str, customer_id: str, product_id: str | None = None) -> str:
    module = _load_script("08_report_account_manager.py", "technical_owner_report")
    return module.build_html(api_base, customer_id, product_id=product_id)


def available_products(db: Session) -> list[dict]:
    rows = (
        db.query(
            models.ProductRelease.product_id,
            func.max(models.ProductRelease.name).label("product_name"),
        )
        .group_by(models.ProductRelease.product_id)
        .order_by(models.ProductRelease.product_id)
        .all()
    )
    return [{"id": row.product_id, "name": row.product_name or row.product_id} for row in rows]


def available_versions(db: Session, product_id: str | None) -> list[str]:
    q = db.query(models.ProductRelease.version).distinct()
    if product_id:
        q = q.filter(models.ProductRelease.product_id == product_id)
    rows = q.order_by(models.ProductRelease.version).all()
    return [row.version for row in rows]


def available_customers(db: Session, product_id: str | None, version: str | None = None) -> list[dict]:
    q = (
        db.query(models.Customer.id, models.Customer.name, models.Customer.region)
        .join(models.Deployment, models.Deployment.customer_id == models.Customer.id)
        .join(models.ProductRelease, models.ProductRelease.id == models.Deployment.product_release_id)
    )
    if product_id:
        q = q.filter(models.ProductRelease.product_id == product_id)
    if version:
        q = q.filter(models.ProductRelease.version == version)
    rows = q.distinct().order_by(models.Customer.name).all()
    return [{"id": row.id, "name": row.name, "region": row.region} for row in rows]


def available_regions(db: Session) -> list[str]:
    rows = (
        db.query(models.Customer.region)
        .distinct()
        .filter(models.Customer.region.isnot(None))
        .order_by(models.Customer.region)
        .all()
    )
    return [row.region for row in rows if row.region]


def available_customer_products(db: Session, customer_id: str) -> list[dict]:
    rows = (
        db.query(
            models.ProductRelease.product_id,
            func.max(models.ProductRelease.name).label("product_name"),
        )
        .join(models.Deployment, models.Deployment.product_release_id == models.ProductRelease.id)
        .filter(models.Deployment.customer_id == customer_id)
        .group_by(models.ProductRelease.product_id)
        .order_by(models.ProductRelease.product_id)
        .all()
    )
    return [{"id": row.product_id, "name": row.product_name or row.product_id} for row in rows]


def _catalog_scope_rows(
    db: Session,
    product_id: str | None,
    versions: list[str],
    product_names: dict[str, str],
    scoped_products: list[str] | None = None,
) -> dict[str, dict]:
    feature_map: dict[str, dict] = {}
    effective_products = scoped_products or ([product_id] if product_id else sorted(product_names.keys()))
    for scope_product in effective_products:
        product_versions = [scope_version for scope_version in versions if scope_version in available_versions(db, scope_product)]
        for scope_version in product_versions:
            for row in catalog_coverage(db, product_id=scope_product, version=scope_version):
                feature_key = f"{scope_product}:{row.feature_code}"
                feature = feature_map.setdefault(
                feature_key,
                {
                    "product_id": scope_product,
                    "product_name": product_names.get(scope_product, scope_product),
                    "code": row.feature_code,
                    "name": row.feature_name,
                    "category": row.category,
                    "tier": row.tier or "",
                    "tiers": {row.tier} if row.tier else set(),
                    "status": row.status or "",
                    "statuses": {row.status} if row.status else set(),
                    "introduced_in": row.introduced_in or "",
                    "versions": set(),
                    "total_usage": 0,
                    "report_count": 0,
                    "enabled_customers": set(),
                    "active_customers": set(),
                    "enabled": False,
                    "active": False,
                    "environments": set(),
                    "latest_report_to": None,
                },
                )
                feature["versions"].add(scope_version)
                if row.tier:
                    feature["tiers"].add(row.tier)
                if row.status:
                    feature["statuses"].add(row.status)
                feature["total_usage"] += int(row.total_usage or 0)
                feature["report_count"] += int(row.report_count or 0)
    return feature_map


def build_feature_explorer_dataset(
    db: Session,
    product_id: str | None = None,
    version: str | None = None,
    customer_id: str | None = None,
    region: str | None = None,
) -> dict:
    products = available_products(db)
    regions = available_regions(db)
    if not products:
        return {
            "products": [],
            "regions": [],
            "versions": [],
            "customers": [],
            "rows": [],
            "selected_product": None,
            "selected_version": None,
            "selected_customer": None,
            "selected_region": None,
            "scope_customer_count": 0,
        }

    valid_product_ids = {product["id"] for product in products}
    product_names = {product["id"]: product["name"] for product in products}
    selected_product = None if not product_id or product_id == ALL_PRODUCTS else (product_id if product_id in valid_product_ids else products[0]["id"])
    selected_product_key = selected_product or ALL_PRODUCTS
    selected_region = region if region in regions else None

    versions = available_versions(db, selected_product)
    selected_version = version if version in versions else None

    customers = available_customers(db, selected_product, selected_version)
    if selected_region:
        customers = [customer for customer in customers if customer.get("region") == selected_region]
    valid_customer_ids = {customer["id"] for customer in customers}
    selected_customer = customer_id if customer_id in valid_customer_ids else None
    customer_products = available_customer_products(db, selected_customer) if selected_customer else []
    scoped_product_ids = (
        [selected_product]
        if selected_product
        else [product["id"] for product in customer_products] if customer_products else sorted(product_names.keys())
    )
    scoped_versions = [selected_version] if selected_version else versions
    product_scope_customer_ids: dict[str, set[str]] = {}
    for scope_product in scoped_product_ids:
        product_customers = available_customers(db, scope_product, selected_version)
        if selected_region:
            product_customers = [
                customer for customer in product_customers if customer.get("region") == selected_region
            ]
        product_scope_customer_ids[scope_product] = {customer["id"] for customer in product_customers}

    feature_map = _catalog_scope_rows(
        db,
        selected_product,
        scoped_versions,
        product_names,
        scoped_products=scoped_product_ids,
    )

    if selected_customer:
        for row in customer_feature_usage(db, selected_customer):
            if selected_product and row.product_id != selected_product:
                continue
            if selected_version and row.version != selected_version:
                continue
            feature_key = f"{row.product_id}:{row.feature_code}"
            feature = feature_map.setdefault(
                feature_key,
                {
                    "product_id": row.product_id,
                    "product_name": product_names.get(row.product_id, row.product_id),
                    "code": row.feature_code,
                    "name": row.feature_name,
                    "category": row.category,
                    "tier": "",
                    "tiers": set(),
                    "status": "",
                    "statuses": set(),
                    "introduced_in": "",
                    "versions": set(),
                    "total_usage": 0,
                    "report_count": 0,
                    "enabled_customers": set(),
                    "active_customers": set(),
                    "enabled": False,
                    "active": False,
                    "environments": set(),
                    "latest_report_to": None,
                },
            )
            feature["versions"].add(row.version)
            feature["enabled"] = True
            feature["total_usage"] += int(row.total_count or 0)
            feature["report_count"] += 1
            feature["environments"].add(row.environment or "")
            if int(row.total_count or 0) > 0:
                feature["active"] = True
            if row.report_to and (
                feature["latest_report_to"] is None or row.report_to > feature["latest_report_to"]
            ):
                feature["latest_report_to"] = row.report_to
    else:
        for scope_product in scoped_product_ids:
            product_versions = [scope_version for scope_version in scoped_versions if scope_version in available_versions(db, scope_product)]
            for scope_version in product_versions:
                heatmap = feature_heatmap(db, product_id=scope_product, version=scope_version)
                for row in heatmap.get("matrix", []):
                    if selected_region and row.get("customer_id") not in valid_customer_ids:
                        continue
                    feature_key = f"{scope_product}:{row['feature_code']}"
                    feature = feature_map.setdefault(
                    feature_key,
                    {
                        "product_id": scope_product,
                        "product_name": product_names.get(scope_product, scope_product),
                        "code": row["feature_code"],
                        "name": row["feature_code"],
                        "category": "",
                        "tier": "",
                        "tiers": set(),
                        "status": "",
                        "statuses": set(),
                        "introduced_in": "",
                        "versions": {scope_version},
                        "total_usage": 0,
                        "report_count": 0,
                        "enabled_customers": set(),
                        "active_customers": set(),
                        "enabled": False,
                        "active": False,
                        "environments": set(),
                        "latest_report_to": None,
                    },
                    )
                    if row.get("is_enabled"):
                        feature["enabled_customers"].add(row["customer_id"])
                    if int(row.get("total_count", 0) or 0) > 0:
                        feature["active_customers"].add(row["customer_id"])

    scope_customer_count = 1 if selected_customer else len(customers)
    rows: list[dict] = []
    for feature in feature_map.values():
        feature_scope_customer_count = (
            1
            if selected_customer
            else len(product_scope_customer_ids.get(feature["product_id"], valid_customer_ids))
        )
        if selected_customer:
            enabled_count = 1 if feature["enabled"] else 0
            active_count = 1 if feature["active"] else 0
            enabled_label = "Yes" if feature["enabled"] else "No"
            active_label = "Yes" if feature["active"] else "No"
        else:
            enabled_count = len(feature["enabled_customers"])
            active_count = len(feature["active_customers"])
            enabled_label = (
                f"{enabled_count}/{feature_scope_customer_count}" if feature_scope_customer_count else "0/0"
            )
            active_label = (
                f"{active_count}/{feature_scope_customer_count}" if feature_scope_customer_count else "0/0"
            )

        adoption_pct = (
            round(active_count / feature_scope_customer_count * 100)
            if feature_scope_customer_count
            else 0
        )
        rows.append(
            {
                "code": feature["code"],
                "product_id": feature["product_id"],
                "product_name": feature["product_name"],
                "name": feature["name"],
                "category": feature["category"] or "Uncategorised",
                "tier": (
                    sorted(feature["tiers"])[0]
                    if len(feature["tiers"]) == 1
                    else f"Mixed ({', '.join(sorted(feature['tiers']))})"
                    if feature["tiers"]
                    else feature["tier"] or "core"
                ),
                "status": (
                    sorted(feature["statuses"])[0]
                    if len(feature["statuses"]) == 1
                    else f"Mixed ({', '.join(sorted(feature['statuses']))})"
                    if feature["statuses"]
                    else feature["status"] or "unknown"
                ),
                "introduced_in": feature["introduced_in"] or "",
                "versions": sorted(v for v in feature["versions"] if v),
                "total_usage": int(feature["total_usage"]),
                "report_count": int(feature["report_count"]),
                "enabled_count": enabled_count,
                "active_count": active_count,
                "enabled_label": enabled_label,
                "active_label": active_label,
                "adoption_pct": adoption_pct,
                "feature_scope_customer_count": feature_scope_customer_count,
                "environments": sorted(env for env in feature["environments"] if env),
                "latest_report_to": feature["latest_report_to"].isoformat() if feature["latest_report_to"] else None,
            }
        )

    rows.sort(key=lambda item: (-item["adoption_pct"], -item["total_usage"], item["name"].lower()))
    return {
        "products": products,
        "regions": regions,
        "versions": versions,
        "customers": customers,
        "rows": rows,
        "selected_product": selected_product_key,
        "selected_version": selected_version,
        "selected_customer": selected_customer,
        "selected_region": selected_region,
        "scope_customer_count": scope_customer_count,
        "scope_products": customer_products if selected_customer and not selected_product else [
            {"id": product_id, "name": product_names.get(product_id, product_id)}
            for product_id in scoped_product_ids
        ],
    }


def _aggregate_dimensions(rows) -> list[dict]:
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        breakdown = row.dimension_breakdown
        if not isinstance(breakdown, dict):
            continue
        for key, value in breakdown.items():
            if isinstance(value, dict):
                for item_key, item_count in value.items():
                    totals[key][str(item_key)] += int(item_count or 0)
            else:
                totals[key][str(value)] += 1

    result = []
    for dim_key, values in sorted(totals.items()):
        ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))
        result.append({"dimension": dim_key, "values": ranked[:8]})
    return result


def _feature_trend(rows) -> dict:
    periods: dict[str, dict[str, int]] = defaultdict(lambda: {"usage": 0, "active_customers": 0})
    active_by_period: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.report_to:
            period = row.report_to.strftime("%Y-%m")
        elif row.report_from:
            period = row.report_from.strftime("%Y-%m")
        else:
            period = row.version or "unknown"
        usage = int(row.total_count or 0)
        periods[period]["usage"] += usage
        if usage > 0 and row.customer_id:
            active_by_period[period].add(row.customer_id)

    ordered = sorted(periods.keys())
    if not ordered:
        return {"label": "No baseline", "delta_pct": None, "series": []}

    series = []
    for period in ordered:
        periods[period]["active_customers"] = len(active_by_period[period])
        series.append({"period": period, "usage": periods[period]["usage"], "active_customers": periods[period]["active_customers"]})

    if len(series) < 2:
        return {"label": "Baseline only", "delta_pct": None, "series": series}

    prev = series[-2]["usage"]
    curr = series[-1]["usage"]
    if prev == 0:
        delta_pct = 100 if curr > 0 else 0
    else:
        delta_pct = round((curr - prev) / prev * 100)

    if delta_pct >= 15:
        label = "Growing"
    elif delta_pct <= -15:
        label = "Declining"
    else:
        label = "Stable"
    return {"label": label, "delta_pct": delta_pct, "series": series}


def _decision_recommendations(summary: dict, rows, explorer_rows: list[dict], trend: dict, customer_id: str | None) -> list[str]:
    recommendations: list[str] = []
    enabled_gap = summary["enabled_count"] - summary["active_count"]

    if summary["adoption_pct"] == 0 and summary["enabled_count"] > 0:
        recommendations.append("Enabled but unused in this scope. Review onboarding, defaults, and discoverability before promoting it further.")
    elif summary["adoption_pct"] <= 10 and summary["total_usage"] <= 5:
        if customer_id:
            recommendations.append("Very limited usage for this customer. Validate whether the feature should stay enabled or be removed from the deployment.")
        else:
            recommendations.append("Very low usage in the current filtered scope. Reassess roadmap priority and consider whether this is a deprecation candidate.")

    if enabled_gap > 0:
        recommendations.append("There is an enablement gap. Some customers have it turned on but are not actively using it, so activation work is likely needed.")

    if trend["label"] == "Declining":
        recommendations.append("Usage is declining in the latest reporting periods. Investigate onboarding friction, product fit, or a competing capability.")
    elif trend["label"] == "Growing":
        recommendations.append("Usage is growing. This is a good candidate for further investment, packaging, or enablement support.")

    if summary["adoption_pct"] >= 70:
        recommendations.append("Broad adoption makes this a high-impact feature. Protect reliability and test coverage because breakage would affect many users.")

    if not customer_id and explorer_rows:
        usage_sorted = sorted(explorer_rows, key=lambda item: (item["total_usage"], item["adoption_pct"], item["name"].lower()))
        low_cutoff = max(1, len(usage_sorted) // 5)
        lowest_codes = {item["code"] for item in usage_sorted[:low_cutoff]}
        if summary["code"] in lowest_codes and summary["adoption_pct"] <= 10:
            recommendations.append("This feature sits in the lowest-usage group for the current product slice, which strengthens the case for simplification or deprecation review.")

    if not recommendations:
        recommendations.append("The current signals look steady. Keep monitoring adoption and usage depth before making a roadmap or rollout change.")
    return recommendations[:4]


def _feature_scope_trends(
    db: Session,
    product_id: str | None,
    version: str | None = None,
    customer_id: str | None = None,
) -> dict[str, dict]:
    q = (
        db.query(
            models.ProductRelease.product_id.label("product_id"),
            models.CatalogFeature.code.label("feature_code"),
            models.Customer.id.label("customer_id"),
            models.UtilizationReport.report_from,
            models.UtilizationReport.report_to,
            models.ProductRelease.version,
            models.FeatureUtilization.total_count,
        )
        .join(models.FeatureUtilization, models.FeatureUtilization.catalog_feature_id == models.CatalogFeature.id)
        .join(models.UtilizationReport, models.UtilizationReport.id == models.FeatureUtilization.report_id)
        .join(models.Deployment, models.Deployment.id == models.UtilizationReport.deployment_id)
        .join(models.Customer, models.Customer.id == models.Deployment.customer_id)
        .join(models.ProductRelease, models.ProductRelease.id == models.CatalogFeature.product_release_id)
    )
    if product_id:
        q = q.filter(models.ProductRelease.product_id == product_id)
    if version:
        q = q.filter(models.ProductRelease.version == version)
    if customer_id:
        q = q.filter(models.Customer.id == customer_id)

    grouped: dict[str, list] = defaultdict(list)
    for row in q.all():
        grouped[f"{row.product_id}:{row.feature_code}"].append(row)
    return {feature_key: _feature_trend(rows) for feature_key, rows in grouped.items()}


def render_feature_utilization(
    db: Session,
    base_url: str,
    product_id: str | None = None,
    version: str | None = None,
    customer_id: str | None = None,
    region: str | None = None,
) -> str:
    data = build_feature_explorer_dataset(db, product_id=product_id, version=version, customer_id=customer_id, region=region)
    rows = data["rows"]
    selected_product = data["selected_product"]
    selected_product_id = None if selected_product == ALL_PRODUCTS else selected_product
    selected_version = data["selected_version"]
    selected_customer = data["selected_customer"]
    selected_region = data["selected_region"]
    trend_map = _feature_scope_trends(
        db,
        product_id=selected_product_id,
        version=selected_version,
        customer_id=selected_customer,
    )

    product_options = f'<option value="{ALL_PRODUCTS}"{" selected" if selected_product == ALL_PRODUCTS else ""}>All Products</option>\n' + "\n".join(
        f'<option value="{escape(product["id"])}"{" selected" if product["id"] == selected_product else ""}>{escape(product["name"])}</option>'
        for product in data["products"]
    )
    version_options = '<option value="">All versions</option>\n' + "\n".join(
        f'<option value="{escape(item)}"{" selected" if item == selected_version else ""}>v{escape(item)}</option>'
        for item in data["versions"]
    )
    customer_options = '<option value="">All customers</option>\n' + "\n".join(
        f'<option value="{escape(customer["id"])}"{" selected" if customer["id"] == selected_customer else ""}>{escape(customer["name"])}</option>'
        for customer in data["customers"]
    )
    region_options = '<option value="">All regions</option>\n' + "\n".join(
        f'<option value="{escape(item)}"{" selected" if item == selected_region else ""}>{escape(item)}</option>'
        for item in data["regions"]
    )

    row_html = []
    for index, row in enumerate(rows, start=1):
        params = {"product_id": row["product_id"], "feature_code": row["code"]}
        if selected_version:
            params["version"] = selected_version
        if selected_customer:
            params["customer_id"] = selected_customer
        if selected_region:
            params["region"] = selected_region
        detail_href = f"{base_url}/views/feature-utilization/detail?{urlencode(params)}"
        row_html.append(
            f"""
            <tr class="feature-row"
                data-href="{escape(detail_href)}"
                data-adoption-tier="{'high' if row['adoption_pct'] > 70 else 'medium' if row['adoption_pct'] >= 30 else 'low' if row['adoption_pct'] > 0 else 'zero'}"
                data-active="{str(row['active_count'] > 0).lower()}"
                data-enabled-quiet="{str(row['enabled_count'] > row['active_count']).lower()}"
                tabindex="0">
              <td class="text-muted">{index}</td>
              {"<td>" + escape(row["product_name"]) + "</td>" if selected_product == ALL_PRODUCTS else ""}
              <td>
                <div style="font-weight:600">{escape(row["name"])}</div>
                <div style="font-size:.78rem;color:#64748b"><code>{escape(row["code"])}</code></div>
              </td>
              <td>{escape(row["category"])}</td>
              <td class="text-center">{escape(row["enabled_label"])}</td>
              <td class="text-center">{escape(row["active_label"])}</td>
              <td class="text-center">
                <span class="pct-pill">{row["adoption_pct"]}%</span>
              </td>
              <td class="text-end">{row["total_usage"]:,}</td>
              <td class="text-center">{escape(", ".join(row["versions"]) if row["versions"] else "—")}</td>
            </tr>
            """
        )

    if selected_customer:
        scope_product_names = ", ".join(product["name"] for product in data.get("scope_products", [])) or "selected products"
        summary_text = (
            f"Showing {len(rows)} features for customer scope <strong>{escape(selected_customer)}</strong> "
            f"across <strong>{escape(scope_product_names)}</strong>."
        )
    elif selected_region:
        summary_text = (
            f"Showing {len(rows)} features across <strong>{data['scope_customer_count']}</strong> customers "
            f"in region <strong>{escape(selected_region)}</strong>."
        )
    elif selected_product == ALL_PRODUCTS:
        summary_text = (
            f"Showing {len(rows)} features across <strong>{data['scope_customer_count']}</strong> customers "
            f"and <strong>all tracked products</strong>."
        )
    else:
        summary_text = f"Showing {len(rows)} features across <strong>{data['scope_customer_count']}</strong> customers in scope."
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    active_rows = sum(1 for row in rows if row["active_count"] > 0)
    enabled_not_active = sum(1 for row in rows if row["enabled_count"] > row["active_count"])
    high_adoption = sum(1 for row in rows if row["adoption_pct"] > 70)
    medium_adoption = sum(1 for row in rows if 30 <= row["adoption_pct"] <= 70)
    low_adoption = sum(1 for row in rows if 0 < row["adoption_pct"] < 30)
    zero_adoption = sum(1 for row in rows if row["adoption_pct"] == 0)
    top_category = "—"
    if rows:
        category_rank: dict[str, int] = defaultdict(int)
        for row in rows:
            category_rank[row["category"]] += row["total_usage"]
        top_category = max(category_rank.items(), key=lambda item: item[1])[0]
    scope_products = data.get("scope_products", [])
    stakeholder_links = []
    if selected_product != ALL_PRODUCTS:
        pd_params = {"product_id": selected_product}
        if selected_version:
            pd_params["version"] = selected_version
        stakeholder_links.append(("Product Development", f"{base_url}/views/product-dev?{urlencode(pd_params)}"))
    cs_params = {}
    if selected_product != ALL_PRODUCTS:
        cs_params["product_id"] = selected_product
    if selected_version:
        cs_params["version"] = selected_version
    if selected_region:
        cs_params["region"] = selected_region
    cs_href = f"{base_url}/views/customer-success"
    if cs_params:
        cs_href = f"{cs_href}?{urlencode(cs_params)}"
    stakeholder_links.append(("Customer Success", cs_href))
    regional_href = f"{base_url}/views/regional"
    if selected_region:
        regional_href = f"{regional_href}?{urlencode({'region': selected_region})}"
    stakeholder_links.append(("Regional Managers", regional_href))
    if selected_customer:
        if selected_product != ALL_PRODUCTS:
            to_params = {"customer_id": selected_customer, "product_id": selected_product}
            stakeholder_links.append(("Technical Owner", f"{base_url}/views/technical-owner?{urlencode(to_params)}"))
        else:
            for product in scope_products:
                to_params = {"customer_id": selected_customer, "product_id": product["id"]}
                label = f"Technical Owner · {product['name']}"
                if len(scope_products) == 1:
                    label += " (only product in scope)"
                stakeholder_links.append((label, f"{base_url}/views/technical-owner?{urlencode(to_params)}"))
    stakeholder_links_html = "".join(
        f'<a class="btn secondary stakeholder-btn" href="{escape(href)}">{escape(label)}</a>'
        for label, href in stakeholder_links
    )
    scope_products_html = ""
    if selected_customer and selected_product == ALL_PRODUCTS and scope_products:
        chips = "".join(
            f'<span class="scope-chip">{escape(product["name"])}</span>'
            for product in scope_products
        )
        noun = "product" if len(scope_products) == 1 else "products"
        scope_products_html = (
            f'<div class="scope-note"><strong>Customer product scope:</strong> '
            f'This customer currently has {len(scope_products)} {noun} in the seeded data. {chips}</div>'
        )
    elif selected_product == ALL_PRODUCTS:
        chips = "".join(
            f'<span class="scope-chip">{escape(product["name"])}</span>'
            for product in data.get("products", [])
        )
        scope_products_html = (
            f'<div class="scope-note"><strong>All Products scope:</strong> '
            f'The explorer is currently combining every tracked product in the repository. The table includes a Product column so you can distinguish feature rows. {chips}</div>'
        )
    deprecation_candidates = [
        row for row in sorted(rows, key=lambda item: (item["total_usage"], item["adoption_pct"], item["name"].lower()))
        if row["adoption_pct"] <= 10 and row["enabled_count"] > 0
    ][:3]
    high_impact = [
        row for row in sorted(rows, key=lambda item: (-item["adoption_pct"], -item["total_usage"], item["name"].lower()))
        if row["adoption_pct"] >= 70
    ][:3]
    gap_priorities = [
        row for row in sorted(rows, key=lambda item: (-(item["enabled_count"] - item["active_count"]), -item["enabled_count"], item["name"].lower()))
        if (row["enabled_count"] - row["active_count"]) > 0
    ][:3]
    growing_features = [
        (row, trend_map.get(f'{row["product_id"]}:{row["code"]}'))
        for row in rows
        if trend_map.get(f'{row["product_id"]}:{row["code"]}')
        and trend_map[f'{row["product_id"]}:{row["code"]}']["delta_pct"] is not None
        and trend_map[f'{row["product_id"]}:{row["code"]}']["delta_pct"] > 0
    ]
    growing_features.sort(key=lambda item: (-item[1]["delta_pct"], -item[0]["total_usage"], item[0]["name"].lower()))
    growing_features = growing_features[:3]

    def render_signal_items(items, formatter):
        if not items:
            return '<div class="signal-empty">No strong signals in this slice yet.</div>'
        return "".join(formatter(item) for item in items)

    deprecation_html = render_signal_items(
        deprecation_candidates,
        lambda row: (
            f'<div class="signal-item"><strong>{escape(row["name"])}</strong>'
            f'<span>{row["adoption_pct"]}% adoption · {row["total_usage"]:,} uses</span></div>'
        ),
    )
    impact_html = render_signal_items(
        high_impact,
        lambda row: (
            f'<div class="signal-item"><strong>{escape(row["name"])}</strong>'
            f'<span>{row["adoption_pct"]}% adoption · {row["total_usage"]:,} uses</span></div>'
        ),
    )
    growth_html = render_signal_items(
        growing_features,
        lambda item: (
            f'<div class="signal-item"><strong>{escape(item[0]["name"])}</strong>'
            f'<span>{item[1]["delta_pct"]:+d}% trend · {item[0]["total_usage"]:,} uses</span></div>'
        ),
    )
    gap_html = render_signal_items(
        gap_priorities,
        lambda row: (
            f'<div class="signal-item"><strong>{escape(row["name"])}</strong>'
            f'<span>{row["enabled_count"] - row["active_count"]} gap · {row["enabled_label"]} enabled</span></div>'
        ),
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Feature Utilization Explorer</title>
  <style>
    :root {{
      --bg: #f5f7fb; --surface: #fff; --ink: #16233a; --muted: #62748d; --line: #d6e0ea;
      --brand: #0b3a67; --brand-2: #ff7300; --brand-soft: #fff1e6; --brand-soft-2: #eaf2fb; --accent: #ff7300; --accent-deep: #d95f00;
    }}
    body {{ margin:0; font-family:"Segoe UI", system-ui, sans-serif; background:var(--bg); color:var(--ink); }}
    .hero {{ background:linear-gradient(135deg,var(--brand) 0%, #15528d 58%, var(--brand-2) 100%); color:#fff; padding:1.5rem 1.8rem; }}
    .hero h1 {{ margin:0 0 .4rem; font-size:1.8rem; }}
    .hero p {{ margin:0; opacity:.84; }}
    .wrap {{ max-width:1280px; margin:0 auto; padding:1.25rem; }}
    .card {{ background:linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%); border:1px solid var(--line); border-radius:16px; box-shadow:0 12px 30px rgba(11,58,103,.06); }}
    .filters {{ padding:1rem; margin-bottom:1rem; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.85rem; align-items:end; }}
    .summary-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.85rem; margin-bottom:1rem; }}
    .mini-stat {{ padding:1rem 1.05rem; cursor:pointer; transition:transform .12s, box-shadow .12s, border-color .12s, background .12s, color .12s; }}
    .mini-stat .value {{ font-size:1.55rem; font-weight:700; line-height:1.1; }}
    .mini-stat .label {{ color:var(--muted); font-size:.76rem; text-transform:uppercase; letter-spacing:.05em; margin-top:.22rem; }}
    .mini-stat:hover {{ transform:translateY(-1px); box-shadow:0 18px 34px rgba(11,58,103,.13); border-color:#f0a96b; background:linear-gradient(180deg, #fffaf5 0%, #fff1e6 100%); }}
    .mini-stat:hover .value, .mini-stat:hover .label {{ color:#9a4300; }}
    .mini-stat.active-filter {{ border-color:#ffb06f; background:linear-gradient(180deg, #fff8f2 0%, #ffe9d7 100%); box-shadow:0 0 0 2px rgba(255,115,0,.14); }}
    .mini-stat.active-filter .value, .mini-stat.active-filter .label {{ color:#9a4300; }}
    .mini-stat.scope-card {{ cursor:pointer; }}
    label {{ display:block; font-size:.8rem; color:var(--muted); margin-bottom:.35rem; }}
    select, button, a.btn {{
      width:100%; box-sizing:border-box; padding:.72rem .82rem; border-radius:10px; border:1px solid var(--line);
      font-size:.92rem; background:#fff; text-decoration:none;
    }}
    select:focus, button:focus, a.btn:focus, .toolbar input:focus, .toolbar select:focus {{ outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgba(255,115,0,.16); }}
    button, a.btn {{ background:linear-gradient(135deg, var(--brand), #15528d); border:none; color:#fff; font-weight:600; cursor:pointer; text-align:center; box-shadow:0 12px 22px rgba(11,58,103,.16); transition:transform .12s, box-shadow .12s, background .12s, border-color .12s, color .12s; }}
    button:hover, a.btn:hover {{ transform:translateY(-1px); box-shadow:0 16px 28px rgba(11,58,103,.22); }}
    a.btn.secondary {{ background:linear-gradient(180deg, #fff7f0 0%, var(--brand-soft) 100%); color:var(--accent-deep); border:1px solid #ffd2b1; box-shadow:none; }}
    .section-head {{ padding:1rem 1.1rem; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap; }}
    .muted {{ color:var(--muted); }}
    .stakeholder-strip {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:.75rem; padding:1rem; margin-bottom:1rem; }}
    .stakeholder-btn {{ display:flex; align-items:center; justify-content:center; min-height:46px; transition:transform .12s, box-shadow .12s, background .12s, border-color .12s, color .12s; }}
    .stakeholder-btn:hover {{ transform:translateY(-1px); background:#ffe7d3; border-color:#f0a96b; color:#9a4300; box-shadow:0 14px 28px rgba(255,115,0,.16); }}
    .btn.secondary:hover {{ background:#ffe7d3; border-color:#f0a96b; color:#9a4300; box-shadow:0 10px 18px rgba(255,115,0,.14); }}
    .scope-note {{ margin:0 1rem 1rem; padding:.8rem .9rem; border:1px solid #ffd2b1; border-radius:12px; background:#fff7f0; color:#7b4a22; font-size:.9rem; }}
    .scope-chip {{ display:inline-block; margin:.35rem .4rem 0 0; padding:.22rem .55rem; border-radius:999px; background:#ffe7d3; color:#9a4300; font-size:.78rem; font-weight:600; }}
    .feature-row:hover a {{ color:#9a4300; text-decoration:underline; }}
    .signal-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.85rem; margin-bottom:1rem; }}
    .signal-card {{ padding:1rem 1.05rem; }}
    .signal-card h3 {{ margin:0 0 .7rem; font-size:.92rem; }}
    .signal-item {{ padding:.55rem 0; border-bottom:1px solid #eef2f7; }}
    .signal-item:last-child {{ border-bottom:none; }}
    .signal-item strong {{ display:block; font-size:.9rem; }}
    .signal-item span {{ display:block; color:var(--muted); font-size:.8rem; margin-top:.15rem; }}
    .signal-empty {{ color:var(--muted); font-size:.84rem; }}
    .toolbar {{ display:grid; grid-template-columns:1.5fr 1fr 180px; gap:.8rem; padding:1rem 1.1rem; border-bottom:1px solid var(--line); background:linear-gradient(180deg, #fffaf5 0%, #fbfdff 100%); }}
    .toolbar input, .toolbar select {{ width:100%; box-sizing:border-box; padding:.72rem .82rem; border-radius:10px; border:1px solid var(--line); font-size:.92rem; background:#fff; }}
    .filter-state {{ display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:.8rem 1.1rem; border-bottom:1px solid var(--line); background:#fff; }}
    .filter-state strong {{ color:#9a4300; }}
    .clear-filter-btn {{ width:auto !important; padding:.5rem .85rem !important; background:#fff7f0 !important; color:#9a4300 !important; border:1px solid #ffd2b1 !important; border-radius:999px !important; font-size:.84rem !important; box-shadow:none !important; }}
    table {{ width:100%; border-collapse:collapse; }}
    thead th {{ text-align:left; font-size:.74rem; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); background:#f8fafc; padding:.8rem; border-bottom:1px solid var(--line); }}
    tbody td {{ padding:.85rem .8rem; border-bottom:1px solid #eef2f7; vertical-align:middle; }}
    .feature-row {{ cursor:pointer; transition:background .15s; }}
    .feature-row:hover, .feature-row:focus {{ background:#fff8f2; outline:none; }}
    code {{ background:#fff1e6; color:#9a4300; padding:.1rem .35rem; border-radius:4px; font-size:.78em; }}
    .pct-pill {{ display:inline-block; min-width:48px; padding:.2rem .55rem; border-radius:999px; background:#eaf2fb; color:#0b3a67; font-weight:700; }}
    .empty {{ padding:2rem 1rem; text-align:center; color:var(--muted); }}
    @media (max-width: 980px) {{ .grid, .summary-grid, .toolbar, .stakeholder-strip, .signal-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="hero">
    <h1>Feature Utilization Explorer</h1>
    <p>Filter by product, version, customer, and region, then click any feature row for a detailed summary.</p>
  </div>
  <div class="wrap">
    <form method="get" action="{base_url}/views/feature-utilization" class="card filters">
      <div class="grid">
        <div>
          <label for="product_id">Product Filter</label>
          <select id="product_id" name="product_id" onchange="this.form.submit()">{product_options}</select>
        </div>
        <div>
          <label for="version">Version Filter</label>
          <select id="version" name="version" onchange="this.form.submit()">{version_options}</select>
        </div>
        <div>
          <label for="customer_id">Customer Filter</label>
          <select id="customer_id" name="customer_id" onchange="this.form.submit()">{customer_options}</select>
        </div>
        <div>
          <label for="region">Region Filter</label>
          <select id="region" name="region" onchange="this.form.submit()">{region_options}</select>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:.65rem">
          <button type="submit">Apply Filters</button>
          <a class="btn secondary" href="{base_url}/views/feature-utilization">Reset Scope</a>
        </div>
      </div>
    </form>

    <div class="card" style="margin-bottom:1rem">
      <div class="section-head" style="padding:.9rem 1rem">
        <div>
          <div style="font-weight:700">Stakeholder Views</div>
          <div class="muted" style="font-size:.88rem">Use this explorer as the landing page, then jump into the stakeholder-specific summaries when you need them.</div>
        </div>
      </div>
      <div class="stakeholder-strip">
        {stakeholder_links_html}
      </div>
      {scope_products_html}
    </div>

    <div class="summary-grid">
      <div class="card mini-stat scope-card" data-filter="all" tabindex="0"><div class="value">{len(rows)}</div><div class="label">Features In Scope</div></div>
      <div class="card mini-stat" data-filter="high" tabindex="0"><div class="value">{high_adoption}</div><div class="label">High Adoption</div></div>
      <div class="card mini-stat" data-filter="medium" tabindex="0"><div class="value">{medium_adoption}</div><div class="label">Medium Adoption</div></div>
      <div class="card mini-stat" data-filter="low" tabindex="0"><div class="value">{low_adoption}</div><div class="label">Low Adoption</div></div>
      <div class="card mini-stat" data-filter="zero" tabindex="0"><div class="value">{zero_adoption}</div><div class="label">Zero Adoption</div></div>
      <div class="card mini-stat" data-filter="active" tabindex="0"><div class="value">{active_rows}</div><div class="label">Actively Used Features</div></div>
      <div class="card mini-stat" data-filter="enabled-quiet" tabindex="0"><div class="value">{enabled_not_active}</div><div class="label">Enabled But Quiet</div></div>
    </div>

    <div class="signal-grid">
      <div class="card signal-card">
        <h3>Deprecation Review Candidates</h3>
        {deprecation_html}
      </div>
      <div class="card signal-card">
        <h3>High Impact Features</h3>
        {impact_html}
      </div>
      <div class="card signal-card">
        <h3>Growing Features</h3>
        {growth_html}
      </div>
      <div class="card signal-card">
        <h3>Enablement Gap Priorities</h3>
        {gap_html}
      </div>
    </div>

    <div class="card">
      <div class="section-head">
        <div>
          <div style="font-weight:700;font-size:1.02rem">Feature Utilization</div>
          <div class="muted" style="font-size:.9rem">{summary_text} Top usage category in this slice: <strong>{escape(top_category)}</strong>.</div>
        </div>
        <div class="muted" style="font-size:.84rem">Generated {generated_at}</div>
      </div>
      {"<div class='empty'>No features found for the selected scope.</div>" if not rows else f'''
      <div class="toolbar">
        <input id="featureSearch" type="search" placeholder="Search by feature, code, or category">
        <select id="sortBy">
          <option value="adoption">Sort by utilization</option>
          <option value="usage">Sort by usage count</option>
          <option value="name">Sort by feature name</option>
          <option value="category">Sort by category</option>
        </select>
        <div class="muted" id="resultCount" style="align-self:center;text-align:right">{len(rows)} rows</div>
      </div>
      <div class="filter-state">
        <div class="muted" id="activeFilterLabel">Showing <strong>all features</strong>. No summary-card filter is applied.</div>
        <button type="button" class="clear-filter-btn" id="clearTableFilters">Clear Table Filters</button>
      </div>
      <div style="overflow:auto">
        <table>
          <thead>
            <tr>
              <th>#</th>
              {"<th>Product</th>" if selected_product == ALL_PRODUCTS else ""}
              <th>Feature</th>
              <th>Category</th>
              <th class="text-center">Enabled</th>
              <th class="text-center">Actively Used</th>
              <th class="text-center">Utilization</th>
              <th class="text-end">Usage Count</th>
              <th class="text-center">Versions</th>
            </tr>
          </thead>
          <tbody>
            {''.join(row_html)}
          </tbody>
        </table>
      </div>
      '''}
    </div>
  </div>
  <script>
    const tbody = document.querySelector('tbody');
    const rows = Array.from(document.querySelectorAll('.feature-row'));
    const search = document.getElementById('featureSearch');
    const sortBy = document.getElementById('sortBy');
    const resultCount = document.getElementById('resultCount');
    const statCards = Array.from(document.querySelectorAll('.mini-stat[data-filter]'));
    const activeFilterLabel = document.getElementById('activeFilterLabel');
    const clearTableFilters = document.getElementById('clearTableFilters');
    const hasProductColumn = {str(selected_product == ALL_PRODUCTS).lower()};
    const featureCol = hasProductColumn ? 2 : 1;
    const categoryCol = hasProductColumn ? 3 : 2;
    const adoptionCol = hasProductColumn ? 6 : 5;
    const usageCol = hasProductColumn ? 7 : 6;
    let activeFilter = null;
    let showAllCardAsActive = false;

    function attachRowHandlers(row) {{
      row.addEventListener('click', () => window.location = row.dataset.href);
      row.addEventListener('keydown', (event) => {{
        if (event.key === 'Enter' || event.key === ' ') {{
          event.preventDefault();
          window.location = row.dataset.href;
        }}
      }});
    }}

    rows.forEach(attachRowHandlers);

    function getCellText(row, index) {{
      return row.children[index]?.innerText?.trim().toLowerCase() || '';
    }}

    function sortRows() {{
      const key = sortBy ? sortBy.value : 'adoption';
      const sorted = [...rows].sort((a, b) => {{
        if (key === 'usage') return Number(b.children[usageCol].innerText.replace(/,/g,'')) - Number(a.children[usageCol].innerText.replace(/,/g,''));
        if (key === 'name') return getCellText(a,featureCol).localeCompare(getCellText(b,featureCol));
        if (key === 'category') return getCellText(a,categoryCol).localeCompare(getCellText(b,categoryCol));
        return Number(b.children[adoptionCol].innerText.replace('%','')) - Number(a.children[adoptionCol].innerText.replace('%',''));
      }});
      sorted.forEach((row, index) => {{
        row.children[0].innerText = index + 1;
        tbody.appendChild(row);
      }});
    }}

    function cardMatches(row) {{
      if (!activeFilter || activeFilter === 'all') return true;
      if (activeFilter === 'active') return row.dataset.active === 'true';
      if (activeFilter === 'enabled-quiet') return row.dataset.enabledQuiet === 'true';
      return row.dataset.adoptionTier === activeFilter;
    }}

    function filterRows() {{
      const term = (search?.value || '').trim().toLowerCase();
      let visible = 0;
      rows.forEach((row) => {{
        const haystack = row.innerText.toLowerCase();
        const match = cardMatches(row) && (!term || haystack.includes(term));
        row.style.display = match ? '' : 'none';
        if (match) visible += 1;
      }});
      if (resultCount) resultCount.innerText = `${{visible}} rows`;
      const filterTextMap = {{
        all: 'all features',
        high: 'high adoption features',
        medium: 'medium adoption features',
        low: 'low adoption features',
        zero: 'zero adoption features',
        active: 'actively used features',
        'enabled-quiet': 'enabled but quiet features',
      }};
      const label = filterTextMap[activeFilter || 'all'] || 'all features';
      const searchText = term ? ` matching "${{search.value.trim()}}"` : '';
      if (activeFilterLabel) {{
        const filterNote = (activeFilter || showAllCardAsActive)
          ? ' Summary-card filter is active.'
          : ' No summary-card filter is applied.';
        activeFilterLabel.innerHTML = `Showing <strong>${{label}}</strong>${{searchText}}.${{filterNote}}`;
      }}
    }}

    function setCardFilter(filter) {{
      activeFilter = filter === 'all' ? null : filter;
      showAllCardAsActive = filter === 'all';
      statCards.forEach((card) => {{
        const isActive = filter === 'all'
          ? card.dataset.filter === 'all'
          : (!!activeFilter && card.dataset.filter === activeFilter);
        card.classList.toggle('active-filter', isActive);
      }});
      filterRows();
    }}

    if (sortBy) {{
      sortBy.addEventListener('change', () => {{
        sortRows();
        filterRows();
      }});
      sortRows();
    }}
    if (search) {{
      search.addEventListener('input', filterRows);
    }}
    if (clearTableFilters) {{
      clearTableFilters.addEventListener('click', () => {{
        activeFilter = null;
        showAllCardAsActive = false;
        if (search) search.value = '';
        statCards.forEach((card) => {{
          card.classList.remove('active-filter');
        }});
        filterRows();
      }});
    }}
    statCards.forEach((card) => {{
      card.addEventListener('click', () => setCardFilter(card.dataset.filter));
      card.addEventListener('keydown', (event) => {{
        if (event.key === 'Enter' || event.key === ' ') {{
          event.preventDefault();
          setCardFilter(card.dataset.filter);
        }}
      }});
    }});
    filterRows();
  </script>
</body>
</html>"""


def render_feature_detail(
    db: Session,
    base_url: str,
    product_id: str,
    feature_code: str,
    version: str | None = None,
    customer_id: str | None = None,
    region: str | None = None,
) -> str:
    explorer = build_feature_explorer_dataset(db, product_id=product_id, version=version, customer_id=customer_id, region=region)
    summary = next((row for row in explorer["rows"] if row["code"] == feature_code), None)
    rows = feature_customer_breakdown(
        db,
        feature_code=feature_code,
        product_id=product_id,
        version=version,
        customer_id=customer_id,
    )
    if region:
        rows = [row for row in rows if getattr(row, "customer_region", None) == region]
    dimensions = _aggregate_dimensions(rows)
    back_params = {"product_id": product_id}
    if version:
        back_params["version"] = version
    if customer_id:
        back_params["customer_id"] = customer_id
    if region:
        back_params["region"] = region
    back_href = f"{base_url}/views/feature-utilization?{urlencode(back_params)}"

    if summary is None:
        return f"""<!DOCTYPE html><html><body style="font-family:Segoe UI,system-ui,sans-serif;padding:2rem">
        <p>Feature <code>{escape(feature_code)}</code> was not found in the selected scope.</p>
        <p><a href="{escape(back_href)}">Back to Feature Utilization Explorer</a></p>
        </body></html>"""

    trend = _feature_trend(rows)
    show_region_column = not region and any(getattr(row, "customer_region", None) for row in rows)
    detail_rows = []
    for row in rows:
        report_window = "—"
        if row.report_from and row.report_to:
            report_window = f"{row.report_from:%Y-%m-%d} → {row.report_to:%Y-%m-%d}"
        detail_rows.append(
            f"""
            <tr>
              <td>{escape(row.customer_name)}</td>
              {"<td>" + escape(getattr(row, "customer_region", None) or "—") + "</td>" if show_region_column else ""}
              <td>{escape(row.environment or "—")}</td>
              <td>{escape(row.version or "—")}</td>
              <td class="text-center">{"Yes" if row.is_enabled else "No"}</td>
              <td class="text-center">{int(row.total_count or 0):,}</td>
              <td>{escape(report_window)}</td>
            </tr>
            """
        )

    dim_cards = []
    for item in dimensions:
        values_html = "".join(
            f'<div class="dim-item"><span>{escape(value)}</span><strong>{count:,}</strong></div>'
            for value, count in item["values"]
        )
        dim_cards.append(
            f"""
            <div class="dim-card">
              <div class="dim-title">{escape(item["dimension"])}</div>
              {values_html}
            </div>
            """
        )

    scope_label = [summary["product_name"]]
    if version:
        scope_label.append(f"v{version}")
    if region:
        scope_label.append(region)
    if customer_id:
        scope_label.append(customer_id)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    detail_count = len(rows)
    enabled_rows = sum(1 for row in rows if row.is_enabled)
    active_rows = sum(1 for row in rows if int(row.total_count or 0) > 0)
    activity_versions = sorted({str(row.version) for row in rows if getattr(row, "version", None)})
    enablement_gap = max(0, summary["enabled_count"] - summary["active_count"])
    breadth_label = (
        f"{summary['active_count']}/{explorer['scope_customer_count']} customers"
        if not customer_id and explorer["scope_customer_count"]
        else ("This customer is active" if summary["active_count"] else "No active customer usage")
    )
    key_message = "No usage has been reported in this scope yet."
    if summary["adoption_pct"] >= 70:
        key_message = "This feature is broadly active in the selected scope."
    elif summary["adoption_pct"] > 0:
        key_message = "This feature is active, but adoption is still limited."
    elif summary["enabled_count"] > 0:
        key_message = "The feature appears enabled, but no active usage was reported."
    recommendations = _decision_recommendations(summary, rows, explorer["rows"], trend, customer_id)
    trend_value = "—" if trend["delta_pct"] is None else f"{trend['delta_pct']:+d}%"
    decision_signal = ("Monitor", "neutral")
    if summary["adoption_pct"] >= 70 and (trend["delta_pct"] is None or trend["delta_pct"] >= 0):
        decision_signal = ("Invest", "good")
    elif summary["enabled_count"] > summary["active_count"]:
        decision_signal = ("Improve Adoption", "warn")
    elif summary["adoption_pct"] == 0 or (
        summary["adoption_pct"] <= 10 and summary["total_usage"] <= 5
    ):
        decision_signal = ("Deprecation Review", "risk")
    elif trend["delta_pct"] is not None and trend["delta_pct"] < 0:
        decision_signal = ("Monitor Decline", "warn")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(summary["name"])} · Feature Detail</title>
  <style>
    :root {{
      --bg:#f4f7fb; --surface:#fff; --ink:#162033; --muted:#6b7b90; --line:#dde5ee; --brand:#214d74; --brand-2:#2d6a73;
    }}
    body {{ margin:0; font-family:"Segoe UI",system-ui,sans-serif; background:var(--bg); color:var(--ink); }}
    .hero {{ background:linear-gradient(135deg,var(--brand),var(--brand-2)); color:#fff; padding:1.4rem 1.8rem; }}
    .hero h1 {{ margin:.35rem 0; font-size:1.8rem; }}
    .hero a {{ color:#dbeafe; text-decoration:none; }}
    .wrap {{ max-width:1200px; margin:0 auto; padding:1.25rem; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; margin-bottom:1rem; }}
    .card {{ background:var(--surface); border:1px solid var(--line); border-radius:16px; box-shadow:0 10px 28px rgba(15,23,42,.05); }}
    .stat {{ padding:1rem 1.1rem; }}
    .stat .value {{ font-size:1.9rem; font-weight:700; }}
    .stat .label {{ color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.05em; }}
    .panel-head {{ padding:1rem 1.1rem; border-bottom:1px solid var(--line); font-weight:700; }}
    .panel-body {{ padding:1rem 1.1rem; }}
    .insight {{ background:#f8fbff; border-left:4px solid #3b82f6; padding:1rem 1.1rem; border-radius:0 12px 12px 0; margin-bottom:1rem; }}
    .decision-list {{ margin:.65rem 0 0; padding-left:1.1rem; }}
    .decision-list li {{ margin:.38rem 0; }}
    .series {{ display:flex; flex-wrap:wrap; gap:.45rem; margin-top:.6rem; }}
    .series-chip {{ background:#eef4fa; color:#244a68; padding:.25rem .55rem; border-radius:999px; font-size:.78rem; }}
    .signal {{ display:inline-flex; align-items:center; gap:.4rem; padding:.3rem .7rem; border-radius:999px; font-size:.8rem; font-weight:700; text-transform:uppercase; letter-spacing:.04em; }}
    .signal.good {{ background:#e7f6ec; color:#166534; }}
    .signal.warn {{ background:#fff4e5; color:#9a4300; }}
    .signal.risk {{ background:#fdeaea; color:#b42318; }}
    .signal.neutral {{ background:#eef4fa; color:#244a68; }}
    table {{ width:100%; border-collapse:collapse; }}
    thead th {{ text-align:left; font-size:.74rem; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); background:#f8fafc; padding:.8rem; border-bottom:1px solid var(--line); }}
    tbody td {{ padding:.85rem .8rem; border-bottom:1px solid #eef2f7; vertical-align:middle; }}
    code {{ background:#eff6ff; color:#1d4ed8; padding:.1rem .35rem; border-radius:4px; font-size:.78em; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:.45rem; margin-top:.45rem; }}
    .chip {{ background:#eef4fa; color:#244a68; padding:.25rem .55rem; border-radius:999px; font-size:.78rem; }}
    .dim-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:1rem; }}
    .dim-card {{ border:1px solid var(--line); border-radius:12px; padding:.85rem; background:#fbfdff; }}
    .dim-title {{ font-weight:700; margin-bottom:.6rem; }}
    .dim-item {{ display:flex; justify-content:space-between; gap:1rem; padding:.28rem 0; border-bottom:1px solid #eef2f7; }}
    .dim-item:last-child {{ border-bottom:none; }}
    .muted {{ color:var(--muted); }}
    @media (max-width: 980px) {{ .grid {{ grid-template-columns:1fr 1fr; }} }}
    @media (max-width: 640px) {{ .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="hero">
    <a href="{escape(back_href)}">← Back to Feature Utilization Explorer</a>
    <h1>{escape(summary["name"])}</h1>
    <div style="opacity:.85"><code>{escape(summary["code"])}</code> · {escape(summary["category"])}{" · " + escape(" · ".join(scope_label)) if scope_label else ""}</div>
  </div>
  <div class="wrap">
    <div class="grid">
      <div class="card stat"><div class="value">{escape(summary["enabled_label"])}</div><div class="label">Enabled</div></div>
      <div class="card stat"><div class="value">{escape(summary["active_label"])}</div><div class="label">Actively Used</div></div>
      <div class="card stat"><div class="value">{summary["adoption_pct"]}%</div><div class="label">Utilization</div></div>
      <div class="card stat"><div class="value">{trend_value}</div><div class="label">Trend</div><div class="muted" style="margin-top:.25rem">{escape(trend["label"])}</div></div>
      <div class="card stat"><div class="value">{escape(breadth_label)}</div><div class="label">Customer Breadth</div></div>
      <div class="card stat"><div class="value">{enablement_gap}</div><div class="label">Enablement Gap</div><div class="muted" style="margin-top:.25rem">enabled minus active</div></div>
    </div>

    <div class="insight">
      <div style="font-weight:700;margin-bottom:.35rem">What this summary says</div>
      <div style="margin-bottom:.5rem"><span class="signal {decision_signal[1]}">{escape(decision_signal[0])}</span></div>
      <div>{escape(key_message)}</div>
      <div class="muted" style="margin-top:.45rem;font-size:.92rem">
        {detail_count} activity rows were found in this scope, with {enabled_rows} enabled record(s) and {active_rows} active record(s).
      </div>
      <ul class="decision-list">
        {''.join(f"<li>{escape(item)}</li>" for item in recommendations)}
      </ul>
    </div>

    <div class="card" style="margin-bottom:1rem">
      <div class="panel-head">Summary</div>
      <div class="panel-body">
        <div><strong>Product:</strong> {escape(summary["product_name"])}</div>
        <div><strong>Status:</strong> {escape(summary["status"])}</div>
        <div><strong>Tier:</strong> {escape(summary["tier"])}</div>
        <div><strong>Catalog versions in scope:</strong> {escape(", ".join(summary["versions"]) if summary["versions"] else "—")}</div>
        <div><strong>Activity versions seen:</strong> {escape(", ".join(activity_versions) if activity_versions else "—")}</div>
        <div><strong>Activity rows in scope:</strong> {detail_count}</div>
        <div><strong>Total usage count:</strong> {summary["total_usage"]:,}</div>
        <div><strong>Generated:</strong> {generated_at}</div>
        {"<div class='chips'>" + "".join(f"<span class='chip'>{escape(env)}</span>" for env in summary["environments"]) + "</div>" if summary["environments"] else ""}
        {"<div style='margin-top:.7rem'><strong>Usage series:</strong><div class='series'>" + "".join(f"<span class='series-chip'>{escape(point['period'])}: {point['usage']:,}</span>" for point in trend['series']) + "</div></div>" if trend['series'] else ""}
      </div>
    </div>

    <div class="card" style="margin-bottom:1rem">
      <div class="panel-head">Detailed Activity</div>
      <div class="panel-body" style="padding:0">
        {"<div class='muted' style='padding:1rem 1.1rem'>No utilization rows were found in the selected scope.</div>" if not detail_rows else f'''
        <div style="overflow:auto">
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                {"<th>Region</th>" if show_region_column else ""}
                <th>Environment</th>
                <th>Version</th>
                <th class="text-center">Enabled</th>
                <th class="text-center">Usage Count</th>
                <th>Report Window</th>
              </tr>
            </thead>
            <tbody>{''.join(detail_rows)}</tbody>
          </table>
        </div>
        '''}
      </div>
    </div>

    <div class="card">
      <div class="panel-head">Dimension Breakdown</div>
      <div class="panel-body">
        {"<div class='muted'>No dimension breakdown data is available for this feature in the selected scope.</div>" if not dim_cards else f"<div class='dim-grid'>{''.join(dim_cards)}</div>"}
      </div>
    </div>
  </div>
</body>
</html>"""
