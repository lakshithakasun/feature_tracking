#!/usr/bin/env python3
"""
WSO2 Feature Utilization — Customer Success Management Report

Goal:
  Give CSM leadership a business-facing view of customer health, adoption,
  underutilization, churn risk, and expansion opportunities.

Sections:
  1. Customer Adoption Score (Health)
  2. Feature Coverage vs Capability
  3. Underutilized Features
  4. Usage Trends
  5. Risk Indicators + Expansion Opportunities

Usage:
    python3 scripts/11_report_customer_success.py
    python3 scripts/11_report_customer_success.py --api http://127.0.0.1:8001
    python3 scripts/11_report_customer_success.py --product identity-server --version 7.3.0
    python3 scripts/11_report_customer_success.py --out reports/customer_success.html
"""

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path


PALETTE = [
    "#0b3a67", "#ff7300", "#1f6f78", "#4f772d", "#15528d",
    "#9f1239", "#7c3aed", "#047857", "#b91c1c", "#d95f00",
]

TIER_ORDER = {"core": 1, "premium": 2, "enterprise": 3}
STATUS_LABEL = {"green": "Healthy", "amber": "Moderate", "red": "At Risk"}
STATUS_COLOR = {"green": "#15803d", "amber": "#b45309", "red": "#b91c1c"}
STATUS_BG = {"green": "#dcfce7", "amber": "#fef3c7", "red": "#fee2e2"}

BASIC_CODES = {"is.sso.oidc", "is.sso.saml"}
MFA_PREFIX = "is.mfa."
FEDERATION_PREFIXES = ("is.enterprise-login.", "is.social-login.", "is.federation.", "is.eid-login.")
ADAPTIVE_PREFIX = "is.adaptive-auth."
GOVERNANCE_PREFIX = "is.governance."


def fetch(api_base: str, path: str):
    url = f"{api_base}{path}"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.loads(response.read())
    except Exception as exc:
        print(f"  ERROR fetching {url}: {exc}", file=sys.stderr)
        return None


def status_for_score(score: int) -> str:
    if score >= 70:
        return "green"
    if score >= 40:
        return "amber"
    return "red"


def tier_badge(tier: str) -> str:
    tier = (tier or "").lower()
    styles = {
        "enterprise": "background:#fee2e2;color:#991b1b",
        "premium": "background:#fef3c7;color:#92400e",
        "core": "background:#e5e7eb;color:#374151",
    }
    style = styles.get(tier, "background:#f3f4f6;color:#6b7280")
    label = tier or "unknown"
    return f'<span style="padding:.15rem .45rem;border-radius:999px;font-size:.72rem;{style}">{label}</span>'


def fmt_int(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def can_access_feature(customer_tier: str, feature_tier: str) -> bool:
    customer_rank = TIER_ORDER.get((customer_tier or "core").lower(), 1)
    feature_rank = TIER_ORDER.get((feature_tier or "core").lower(), 1)
    return feature_rank <= customer_rank


def month_key(value: str) -> str:
    if not value:
        return "unknown"
    return value[:7]


def semver_key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(version).split("."))
    except Exception:
        return (0,)


def classify_segment(used_codes: set[str]) -> str:
    has_mfa = any(code.startswith(MFA_PREFIX) for code in used_codes)
    has_federation = any(code.startswith(prefix) for prefix in FEDERATION_PREFIXES for code in used_codes)
    has_advanced = any(
        code.startswith(ADAPTIVE_PREFIX) or code.startswith(GOVERNANCE_PREFIX)
        for code in used_codes
    )
    if has_advanced:
        return "Advanced"
    if has_mfa or has_federation:
        return "Intermediate"
    return "Beginner"


def low_usage_threshold(total_events: int) -> int:
    return max(25, int(total_events * 0.002))


def compute_trend(monthly_events: dict[str, int]) -> dict:
    months = sorted(monthly_events)
    if len(months) < 2:
        month = months[-1] if months else "N/A"
        total = monthly_events[month] if months else 0
        return {
            "status": "Baseline only",
            "direction": "flat",
            "change_pct": 0,
            "month": month,
            "current": total,
            "previous": None,
        }

    previous_month, current_month = months[-2], months[-1]
    previous_total = monthly_events[previous_month]
    current_total = monthly_events[current_month]
    if previous_total == 0:
        change_pct = 100 if current_total > 0 else 0
    else:
        change_pct = round((current_total - previous_total) / previous_total * 100)

    if change_pct <= -15:
        status = "Declining"
        direction = "down"
    elif change_pct >= 15:
        status = "Growing"
        direction = "up"
    else:
        status = "Stable"
        direction = "flat"

    return {
        "status": status,
        "direction": direction,
        "change_pct": change_pct,
        "month": current_month,
        "current": current_total,
        "previous": previous_total,
    }


def category_label(category_name: str) -> str:
    return category_name or "Unknown"


def load_data(
    api_base: str,
    product_id: str | None = None,
    version: str | None = None,
    region: str | None = None,
    customer_tier: str | None = None,
) -> dict:
    selected_customer_tier = customer_tier
    print("Fetching customer success management data...")
    portfolio = fetch(api_base, "/reports/customers/portfolio") or []
    dashboard_path = "/reports/dashboard"
    if product_id or version:
        query = []
        if product_id:
            query.append(f"product_id={product_id}")
        if version:
            query.append(f"version={version}")
        dashboard_path = f"{dashboard_path}?{'&'.join(query)}"
    dashboard = fetch(api_base, dashboard_path) or {}
    if not portfolio:
        sys.exit("No customer portfolio data found. Is the API running and data seeded?")

    customer_feature_rows: dict[str, list] = {}
    for customer in portfolio:
        customer_id = customer["customer_id"]
        rows = fetch(api_base, f"/reports/customers/{customer_id}/features") or []
        filtered_rows = [
            row for row in rows
            if (not product_id or row.get("product_id") == product_id)
            and (not version or row.get("version") == version)
        ]
        customer_feature_rows[customer_id] = filtered_rows

    filtered_portfolio = []
    for customer in portfolio:
        filtered_deployments = [
            deployment for deployment in customer.get("deployments", [])
            if (not product_id or deployment.get("product_id") == product_id)
            and (not version or deployment.get("version") == version)
        ]
        filtered_rows = customer_feature_rows.get(customer["customer_id"], [])
        if region and (customer.get("region") or "unknown") != region:
            continue
        if selected_customer_tier and (customer.get("tier") or "unknown") != selected_customer_tier:
            continue
        if filtered_deployments or filtered_rows:
            copy = dict(customer)
            copy["deployments"] = filtered_deployments
            filtered_portfolio.append(copy)

    portfolio = filtered_portfolio

    prod_release_pairs = sorted({
        (deployment.get("product_id"), deployment.get("version"))
        for customer in portfolio
        for deployment in customer.get("deployments", [])
        if deployment.get("environment") == "prod" and deployment.get("product_id") and deployment.get("version")
    }, key=lambda item: ((item[0] or ""), semver_key(item[1] or "")))

    coverage_by_release: dict[tuple[str, str], list] = {}
    for release_product_id, release_version in prod_release_pairs:
        coverage_by_release[(release_product_id, release_version)] = (
            fetch(api_base, f"/reports/catalog/coverage?product_id={release_product_id}&version={release_version}") or []
        )

    customer_metrics = []
    coverage_rows = []
    underutilized_rows = []
    risk_rows = []
    expansion_rows = []
    monthly_portfolio_events: dict[str, int] = defaultdict(int)

    for customer in portfolio:
        customer_id = customer["customer_id"]
        customer_name = customer["customer_name"]
        customer_tier_value = (customer.get("tier") or "core").lower()
        rows = customer_feature_rows.get(customer_id, [])
        prod_rows = [row for row in rows if row.get("environment") == "prod"]

        latest_report_to = max((str(row.get("report_to") or "")) for row in prod_rows) if prod_rows else None
        current_rows = [row for row in prod_rows if str(row.get("report_to") or "") == latest_report_to] if latest_report_to else []

        feature_usage: dict[str, dict] = {}
        current_feature_usage: dict[str, dict] = {}
        monthly_events: dict[str, int] = defaultdict(int)
        for row in prod_rows:
            code = row["feature_code"]
            feature_usage.setdefault(code, {
                "code": code,
                "name": row["feature_name"],
                "category": category_label(row.get("category")),
                "total_count": 0,
            })
            feature_usage[code]["total_count"] += row["total_count"]
            month = month_key(str(row.get("report_to") or ""))
            monthly_events[month] += row["total_count"]
            monthly_portfolio_events[month] += row["total_count"]

        for row in current_rows:
            code = row["feature_code"]
            current_feature_usage.setdefault(code, {
                "code": code,
                "name": row["feature_name"],
                "category": category_label(row.get("category")),
                "total_count": 0,
            })
            current_feature_usage[code]["total_count"] += row["total_count"]

        enabled_codes = set(current_feature_usage)
        used_codes = {code for code, entry in current_feature_usage.items() if entry["total_count"] > 0}
        total_events = sum(entry["total_count"] for entry in current_feature_usage.values())

        current_versions = sorted({row["version"] for row in current_rows}, key=semver_key)
        if not current_versions:
            current_versions = sorted({
                deployment["version"]
                for deployment in customer.get("deployments", [])
                if deployment.get("environment") == "prod"
            }, key=semver_key)
            if current_versions:
                current_versions = [current_versions[-1]]

        current_release_pairs = sorted({
            (row.get("product_id"), row.get("version"))
            for row in current_rows
            if row.get("product_id") and row.get("version")
        }, key=lambda item: ((item[0] or ""), semver_key(item[1] or "")))
        if not current_release_pairs:
            current_release_pairs = sorted({
                (deployment.get("product_id"), deployment.get("version"))
                for deployment in customer.get("deployments", [])
                if deployment.get("environment") == "prod" and deployment.get("product_id") and deployment.get("version")
            }, key=lambda item: ((item[0] or ""), semver_key(item[1] or "")))

        available_features: dict[str, dict] = {}
        for release_product_id, release_version in current_release_pairs:
            for feature in coverage_by_release.get((release_product_id, release_version), []):
                if can_access_feature(customer_tier_value, feature.get("tier") or "core"):
                    available_features.setdefault(feature["feature_code"], feature)

        available_by_category: dict[str, set] = defaultdict(set)
        used_by_category: dict[str, set] = defaultdict(set)
        for code, feature in available_features.items():
            category = category_label(feature.get("category"))
            available_by_category[category].add(code)
        for code in used_codes:
            feature = available_features.get(code)
            if feature:
                used_by_category[category_label(feature.get("category"))].add(code)

        available_count = len(available_features)
        used_count = len(used_codes & set(available_features))
        relevant_categories = len(available_by_category)
        adopted_categories = sum(1 for category in available_by_category if used_by_category.get(category))
        adoption_score = round(adopted_categories / relevant_categories * 100) if relevant_categories else 0
        status = status_for_score(adoption_score)
        segment = classify_segment(used_codes)

        weakest_categories = []
        for category, codes in available_by_category.items():
            available_total = len(codes)
            used_total = len(used_by_category.get(category, set()))
            coverage_pct = round(used_total / available_total * 100) if available_total else 0
            weakest_categories.append({
                "customer_id": customer_id,
                "customer_name": customer_name,
                "category": category,
                "available": available_total,
                "used": used_total,
                "coverage_pct": coverage_pct,
            })
        weakest_categories.sort(key=lambda row: (row["coverage_pct"], row["category"]))
        coverage_rows.extend(weakest_categories)

        threshold = low_usage_threshold(total_events)
        customer_underutilized = []
        for code in sorted(enabled_codes):
            entry = current_feature_usage[code]
            total_count = entry["total_count"]
            if total_count == 0:
                insight = "Enabled but no observed usage"
            elif total_count <= threshold:
                insight = f"Enabled but low usage ({total_count} events)"
            else:
                continue

            row = {
                "customer_name": customer_name,
                "feature_code": code,
                "feature_name": entry["name"],
                "category": entry["category"],
                "status": "Enabled",
                "insight": insight,
                "total_count": total_count,
            }
            customer_underutilized.append(row)
            underutilized_rows.append(row)

        trend = compute_trend(monthly_events)
        risk_reasons = []
        if adoption_score < 40:
            risk_reasons.append(f"Low adoption score ({adoption_score}%)")
        if trend["status"] == "Declining":
            risk_reasons.append("Usage declining")
        if used_codes and used_codes.issubset(BASIC_CODES):
            risk_reasons.append("Only using basic authentication")
        if customer.get("has_no_report"):
            risk_reasons.append("No utilization report this period")

        expansion = []
        if not any(code.startswith(MFA_PREFIX) for code in used_codes):
            mfa_options = [code for code in available_features if code.startswith(MFA_PREFIX)]
            if mfa_options:
                expansion.append("MFA")
        if not any(code.startswith(prefix) for prefix in FEDERATION_PREFIXES for code in used_codes):
            fed_options = [code for code in available_features if code.startswith(FEDERATION_PREFIXES)]
            if fed_options:
                expansion.append("Federation (SAML/OIDC)")
        if not any(code.startswith(ADAPTIVE_PREFIX) for code in used_codes):
            adaptive_options = [code for code in available_features if code.startswith(ADAPTIVE_PREFIX)]
            if adaptive_options:
                expansion.append("Adaptive Auth")
        if not any(code.startswith(GOVERNANCE_PREFIX) for code in used_codes):
            governance_options = [code for code in available_features if code.startswith(GOVERNANCE_PREFIX)]
            if governance_options:
                expansion.append("Governance")

        if not expansion and weakest_categories:
            expansion.append(f"Expand {weakest_categories[0]['category']}")

        risk_rows.append({
            "customer_name": customer_name,
            "segment": segment,
            "status": status,
            "score": adoption_score,
            "reasons": risk_reasons,
        })
        expansion_rows.append({
            "customer_name": customer_name,
            "segment": segment,
            "status": status,
            "score": adoption_score,
            "suggestions": expansion[:3] or ["Maintain current adoption"],
        })

        customer_metrics.append({
            "customer_id": customer_id,
            "customer_name": customer_name,
            "tier": customer_tier_value,
            "region": customer.get("region") or "unknown",
            "status": status,
            "score": adoption_score,
            "segment": segment,
            "relevant_categories": relevant_categories,
            "adopted_categories": adopted_categories,
            "available_count": available_count,
            "used_count": used_count,
            "total_events": total_events,
            "trend": trend,
            "risk_reasons": risk_reasons,
            "expansion": expansion[:3],
            "versions": current_versions,
        })

    return {
        "dashboard": dashboard,
        "portfolio": portfolio,
        "selected_product": product_id,
        "selected_version": version,
        "selected_region": region,
        "selected_customer_tier": selected_customer_tier,
        "customers": sorted(customer_metrics, key=lambda row: (-row["score"], row["customer_name"])),
        "coverage_rows": sorted(coverage_rows, key=lambda row: (row["coverage_pct"], row["customer_name"], row["category"])),
        "underutilized_rows": sorted(underutilized_rows, key=lambda row: (row["total_count"], row["customer_name"], row["feature_name"])),
        "risk_rows": sorted(risk_rows, key=lambda row: (row["score"], row["customer_name"])),
        "expansion_rows": sorted(expansion_rows, key=lambda row: (row["status"] != "green", -row["score"], row["customer_name"])),
        "portfolio_monthly_events": dict(sorted(monthly_portfolio_events.items())),
    }


def section_scorecards(data: dict) -> str:
    customers = data["customers"]
    total = len(customers)
    avg_score = round(sum(customer["score"] for customer in customers) / total) if total else 0
    healthy = sum(1 for customer in customers if customer["status"] == "green")
    moderate = sum(1 for customer in customers if customer["status"] == "amber")
    risk_signals = sum(1 for customer in customers if customer["risk_reasons"])
    declining = sum(1 for customer in customers if customer["trend"]["status"] == "Declining")
    avg_events = round(sum(customer["total_events"] for customer in customers) / total) if total else 0

    dist_labels = json.dumps(["Healthy", "Moderate", "At Risk"])
    red_status = sum(1 for customer in customers if customer["status"] == "red")
    dist_values = json.dumps([healthy, moderate, red_status])
    dist_colors = json.dumps([STATUS_COLOR["green"], STATUS_COLOR["amber"], STATUS_COLOR["red"]])

    return f"""
<div class="row g-3 mb-4">
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value text-primary">{total}</div>
      <div class="label">Customers</div>
      <div class="sub">managed accounts</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#15803d">{healthy}</div>
      <div class="label">Healthy</div>
      <div class="sub">score ≥ 70%</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#b45309">{moderate}</div>
      <div class="label">Moderate</div>
      <div class="sub">score 40-69%</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#b91c1c">{risk_signals}</div>
      <div class="label">Risk Signals</div>
      <div class="sub">needs CSM attention</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#1d4ed8">{avg_score}%</div>
      <div class="label">Avg Adoption</div>
      <div class="sub">health score</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#7c3aed">{declining}</div>
      <div class="label">Declining</div>
      <div class="sub">trend signal</div>
    </div>
  </div>
  <div class="col-12 col-md-5">
    <div class="section-card" style="margin-bottom:0">
      <div class="card-header" style="padding:.7rem 1rem;font-size:.84rem">Portfolio Health Distribution</div>
      <div class="card-body" style="padding:.8rem 1rem">
        <div style="position:relative;height:160px"><canvas id="healthDistChart"></canvas></div>
      </div>
    </div>
  </div>
  <div class="col-12 col-md-7">
    <div class="section-card h-100" style="margin-bottom:0">
      <div class="card-header" style="padding:.7rem 1rem;font-size:.84rem">Management Summary</div>
      <div class="card-body" style="padding:1rem 1.2rem">
        <div style="font-size:.92rem;color:#374151;line-height:1.6">
          This dashboard focuses on customer value, adoption breadth, underused capabilities,
          and early churn signals. Average current production event volume per customer is <strong>{fmt_int(avg_events)}</strong>.
        </div>
        <div class="text-muted mt-2" style="font-size:.82rem;line-height:1.6">
          Healthy / Moderate come from the adoption score in Section 1.
          Risk Signals counts customers showing stronger warning signs, such as falling usage,
          very narrow adoption, or missing reporting.
          Declining counts customers whose latest month is clearly lower than the month before.
        </div>
      </div>
    </div>
  </div>
</div>
<script>
new Chart(document.getElementById('healthDistChart'), {{
  type: 'doughnut',
  data: {{
    labels: {dist_labels},
    datasets: [{{ data: {dist_values}, backgroundColor: {dist_colors}, borderWidth: 0 }}]
  }},
  options: {{
    cutout: '62%',
    plugins: {{ legend: {{ position: 'right', labels: {{ font: {{ size: 11 }}, boxWidth: 12, padding: 10 }} }} }}
  }}
}});
</script>"""


def section_adoption_score(data: dict) -> str:
    rows = ""
    for customer in sorted(data["customers"], key=lambda row: (row["score"], row["customer_name"])):
        status = customer["status"]
        score = customer["score"]
        bar = (
            f'<div class="d-flex align-items-center gap-2">'
            f'<div class="progress flex-grow-1" style="height:6px;border-radius:999px;background:#e5e7eb">'
            f'<div class="progress-bar" style="width:{score}%;background:{STATUS_COLOR[status]}"></div>'
            f'</div>'
            f'<span style="font-size:.76rem;white-space:nowrap">{customer["adopted_categories"]}/{customer["relevant_categories"]}</span>'
            f'</div>'
        )
        rows += f"""
        <tr>
          <td class="ps-3"><strong>{customer['customer_name']}</strong></td>
          <td>{tier_badge(customer['tier'])}</td>
          <td>{customer['segment']}</td>
          <td style="min-width:160px">{bar}</td>
          <td class="text-center"><strong style="color:{STATUS_COLOR[status]}">{score}%</strong></td>
          <td><span class="status-pill" style="background:{STATUS_BG[status]};color:{STATUS_COLOR[status]}">{STATUS_LABEL[status]}</span></td>
        </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    1. Customer Adoption Score (Health)
    <span class="text-muted fw-normal" style="font-size:.82rem"> — simple health indicator based on how many relevant product categories show real usage</span>
  </div>
  <div class="card-body p-0">
    <div class="px-3 py-2 text-muted" style="font-size:.82rem;border-bottom:1px solid #e5e7eb;background:#fbfcfe">
      Adoption Score = number of product areas the customer is actively using / number of product areas available to them.
      A product area counts as used when at least one feature in that area shows real usage.
      Higher scores mean the customer is getting value from a broader part of the product.
    </div>
    <table class="table table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Customer</th>
          <th>Tier</th>
          <th>Segment</th>
          <th style="min-width:160px">Category Adoption</th>
          <th class="text-center">Adoption Score</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""


def section_coverage(data: dict) -> str:
    grouped_rows: dict[str, list] = defaultdict(list)
    for row in data["coverage_rows"]:
        grouped_rows[row["customer_name"]].append(row)

    rows = []
    for customer_name in sorted(grouped_rows):
        ranked = sorted(
            grouped_rows[customer_name],
            key=lambda row: (row["coverage_pct"], -(row["available"] - row["used"]), row["category"]),
        )
        chosen = []

        zero_gap = next((row for row in ranked if row["coverage_pct"] == 0), None)
        if zero_gap:
            chosen.append(zero_gap)

        partial_gap = next((row for row in ranked if 0 < row["coverage_pct"] < 100), None)
        if partial_gap and partial_gap not in chosen:
            chosen.append(partial_gap)

        for row in ranked:
            if row not in chosen:
                chosen.append(row)
            if len(chosen) >= 2:
                break

        rows.extend(chosen[:2])

    rows = sorted(
        rows,
        key=lambda row: (row["coverage_pct"], -(row["available"] - row["used"]), row["customer_name"], row["category"]),
    )[:20]

    category_totals: dict[str, list] = defaultdict(list)
    for row in data["coverage_rows"]:
        category_totals[row["category"]].append(row["coverage_pct"])

    avg_categories = sorted(
        (
            {"category": category, "coverage_pct": round(sum(values) / len(values))}
            for category, values in category_totals.items()
        ),
        key=lambda row: row["coverage_pct"],
    )[:8]

    labels = json.dumps([row["category"] for row in avg_categories])
    values = json.dumps([row["coverage_pct"] for row in avg_categories])
    colors = json.dumps([PALETTE[i % len(PALETTE)] for i in range(len(avg_categories))])

    body = ""
    for row in rows:
        body += f"""
        <tr>
          <td class="ps-3"><strong>{row['customer_name']}</strong></td>
          <td>{row['category']}</td>
          <td class="text-center">{row['available']}</td>
          <td class="text-center">{row['used']}</td>
          <td class="text-center"><strong style="color:{STATUS_COLOR[status_for_score(row['coverage_pct'])]}">{row['coverage_pct']}%</strong></td>
        </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    2. Feature Coverage vs Capability
    <span class="text-muted fw-normal" style="font-size:.82rem"> — biggest category gaps per customer, based on the latest production snapshot</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      Available shows how many features the customer could use in that product area.
      Used shows how many of those features are actually being used now.
      Coverage is the share of available features that are in use.
      Low coverage usually points to a customer growth opportunity.
    </div>
    <div class="row g-3">
      <div class="col-md-5">
        <div style="position:relative;height:300px"><canvas id="coverageChart"></canvas></div>
      </div>
      <div class="col-md-7">
        <table class="table table-sm table-hover mb-0">
          <thead>
            <tr>
              <th class="ps-3">Customer</th>
              <th>Category</th>
              <th class="text-center">Available</th>
              <th class="text-center">Used</th>
              <th class="text-center">Coverage</th>
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>
<script>
new Chart(document.getElementById('coverageChart'), {{
  type: 'bar',
  data: {{
    labels: {labels},
    datasets: [{{ data: {values}, backgroundColor: {colors}, borderRadius: 4 }}]
  }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ max: 100, grid: {{ color: '#eef2f7' }}, ticks: {{ callback: value => value + '%' }} }},
      y: {{ ticks: {{ font: {{ size: 10 }} }} }}
    }}
  }}
}});
</script>"""


def section_underutilized(data: dict) -> str:
    rows = data["underutilized_rows"][:24]
    if not rows:
        return """
<div class="section-card mb-4">
  <div class="card-header">3. Underutilized Features</div>
  <div class="card-body"><p class="text-muted mb-0">No enabled-but-underused features detected in the current data.</p></div>
</div>"""

    body = ""
    for row in rows:
        body += f"""
        <tr>
          <td class="ps-3"><strong>{row['customer_name']}</strong></td>
          <td><code>{row['feature_code']}</code><div style="font-size:.82rem">{row['feature_name']}</div></td>
          <td>{row['status']}</td>
          <td>{row['insight']}</td>
        </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    3. Underutilized Features
    <span class="text-muted fw-normal" style="font-size:.82rem"> — features enabled but not used, or enabled with very low usage</span>
  </div>
  <div class="card-body pb-0">
    <div class="text-muted" style="font-size:.82rem">
      This section highlights quick wins.
      A feature appears here when it is available in the customer's current setup but is not being used,
      or is being used only rarely.
      These are usually good candidates for training, onboarding, or activation campaigns.
    </div>
  </div>
  <div class="card-body p-0">
    <table class="table table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Customer</th>
          <th>Feature</th>
          <th>Status</th>
          <th>Insight</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</div>"""


def section_trends(data: dict) -> str:
    monthly = data["portfolio_monthly_events"]
    labels = json.dumps(list(monthly.keys()))
    values = json.dumps(list(monthly.values()))

    body = ""
    for customer in sorted(data["customers"], key=lambda row: (row["trend"]["status"] == "Declining", row["score"], row["customer_name"])):
        trend = customer["trend"]
        if trend["direction"] == "down":
            icon = "⬇"
            color = STATUS_COLOR["red"]
        elif trend["direction"] == "up":
            icon = "⬆"
            color = STATUS_COLOR["green"]
        else:
            icon = "➡"
            color = "#64748b"
        previous = fmt_int(trend["previous"]) if trend["previous"] is not None else "N/A"
        current = fmt_int(trend["current"])
        change = f"{trend['change_pct']}%" if trend["previous"] is not None else "single period"
        body += f"""
        <tr>
          <td class="ps-3"><strong>{customer['customer_name']}</strong></td>
          <td>{trend['month']}</td>
          <td class="text-end">{previous}</td>
          <td class="text-end">{current}</td>
          <td><span style="color:{color};font-weight:600">{icon} {trend['status']}</span></td>
          <td class="text-muted">{change}</td>
        </tr>"""

    note = ""
    if len(monthly) < 2:
        note = '<div class="text-muted mt-3" style="font-size:.82rem">Only one reporting month is available in the current seed data, so customer-level trends are shown as baseline signals. Add more monthly reports to make churn detection stronger.</div>'

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    4. Usage Trends
    <span class="text-muted fw-normal" style="font-size:.82rem"> — growth, stability, or decline based on monthly production usage totals</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      The line chart shows overall customer usage by month across the portfolio.
      In the table, Previous and Current compare each customer's last two months.
      Declining means usage has dropped clearly, Stable means little change, and Growing means usage has increased clearly.
    </div>
    <div style="position:relative;height:240px;margin-bottom:1rem"><canvas id="trendChart"></canvas></div>
    <table class="table table-sm table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Customer</th>
          <th>Latest Month</th>
          <th class="text-end">Previous</th>
          <th class="text-end">Current</th>
          <th>Trend</th>
          <th>Change</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
    {note}
  </div>
</div>
<script>
new Chart(document.getElementById('trendChart'), {{
  type: 'line',
  data: {{
    labels: {labels},
    datasets: [{{
      label: 'Portfolio Events',
      data: {values},
      borderColor: '#1f6f78',
      backgroundColor: 'rgba(31,111,120,.12)',
      fill: true,
      tension: 0.25,
      pointRadius: 4
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: '#eef2f7' }} }},
      y: {{ grid: {{ color: '#eef2f7' }} }}
    }}
  }}
}});
</script>"""


def section_risk_and_expansion(data: dict) -> str:
    risk_rows = [row for row in data["risk_rows"] if row["reasons"]][:12]
    expansion_rows = data["expansion_rows"][:12]

    risk_body = ""
    if risk_rows:
        for row in risk_rows:
            risk_body += f"""
        <tr>
          <td class="ps-3"><strong>{row['customer_name']}</strong></td>
          <td>{row['segment']}</td>
          <td><span class="status-pill" style="background:{STATUS_BG[row['status']]};color:{STATUS_COLOR[row['status']]}">{STATUS_LABEL[row['status']]}</span></td>
          <td>{row['reasons'][0]}</td>
        </tr>"""
    else:
        risk_body = """
        <tr>
          <td colspan="4" class="ps-3 text-muted">No active customer risk signals detected in the current snapshot.</td>
        </tr>"""

    expansion_body = ""
    for row in expansion_rows:
        suggestions = ", ".join(row["suggestions"])
        expansion_body += f"""
        <tr>
          <td class="ps-3"><strong>{row['customer_name']}</strong></td>
          <td>{row['segment']}</td>
          <td><span class="status-pill" style="background:{STATUS_BG[row['status']]};color:{STATUS_COLOR[row['status']]}">{STATUS_LABEL[row['status']]}</span></td>
          <td>{suggestions}</td>
        </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    5. Risk Indicators + Expansion Opportunities
    <span class="text-muted fw-normal" style="font-size:.82rem"> — retention signals on the left, growth suggestions on the right</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      Risk Indicators highlights accounts that may need attention now.
      Expansion Opportunities suggests the next product area worth growing based on what is missing or lightly adopted.
      Read the two sides together: the left side helps protect retention, and the right side helps grow value.
    </div>
    <div class="row g-3">
      <div class="col-md-6">
        <div class="sub-card">
          <div class="sub-card-title">Risk Indicators</div>
          <table class="table table-sm table-hover mb-0">
            <thead>
              <tr>
                <th class="ps-3">Customer</th>
                <th>Segment</th>
                <th>Status</th>
                <th>Risk Reason</th>
              </tr>
            </thead>
            <tbody>{risk_body}</tbody>
          </table>
        </div>
      </div>
      <div class="col-md-6">
        <div class="sub-card">
          <div class="sub-card-title">Expansion Opportunities</div>
          <table class="table table-sm table-hover mb-0">
            <thead>
              <tr>
                <th class="ps-3">Customer</th>
                <th>Segment</th>
                <th>Status</th>
                <th>Suggested Feature</th>
              </tr>
            </thead>
            <tbody>{expansion_body}</tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</div>"""


def build_html(
    api_base: str,
    product_id: str | None = None,
    version: str | None = None,
    region: str | None = None,
    customer_tier: str | None = None,
) -> str:
    data = load_data(api_base, product_id=product_id, version=version, region=region, customer_tier=customer_tier)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    scope_parts = []
    if data.get("selected_product"):
        scope_parts.append(data["selected_product"])
    else:
        scope_parts.append("all products")
    scope_parts.append(f"v{data['selected_version']}" if data.get("selected_version") else "all versions")
    scope_parts.append(data["selected_region"] if data.get("selected_region") else "all regions")
    scope_parts.append(data["selected_customer_tier"] if data.get("selected_customer_tier") else "all customer tiers")
    scope_label = " / ".join(scope_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Customer Success Management Dashboard</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --brand-dark: #0b3a67;
      --brand-mid: #15528d;
      --brand-accent: #ff7300;
    }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background:#f5f7fb; color:#16233a; }}
    .page-header {{
      background: linear-gradient(135deg, var(--brand-dark) 0%, var(--brand-mid) 58%, var(--brand-accent) 100%);
      color: white; padding: 2.4rem 0 2rem;
    }}
    .page-header .subtitle {{ opacity:.78; font-size:.94rem; }}
    .tag-pill {{
      background: rgba(255,255,255,.14); border-radius:999px;
      padding:.35rem .8rem; font-size:.76rem; letter-spacing:.05em;
    }}
    .stat-card {{
      background:linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%); border-radius:14px; padding:1.2rem 1.3rem;
      box-shadow:0 12px 30px rgba(11,58,103,.06); height:100%;
    }}
    .stat-card .value {{ font-size:1.9rem; font-weight:700; line-height:1; }}
    .stat-card .label {{ color:#64748b; font-size:.75rem; text-transform:uppercase; letter-spacing:.05em; margin-top:.35rem; }}
    .stat-card .sub {{ color:#64748b; font-size:.79rem; margin-top:.3rem; }}
    .section-card {{
      background:linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%); border-radius:14px; box-shadow:0 12px 30px rgba(11,58,103,.06);
      margin-bottom:1.5rem; overflow:hidden;
    }}
    .section-card .card-header {{
      background:none; border-bottom:1px solid #e5e7eb; padding:1rem 1.25rem;
      font-weight:650; font-size:.96rem;
    }}
    .section-card .card-body {{ padding:1.25rem; }}
    .sub-card {{
      background:#fbfcfe; border:1px solid #e5e7eb; border-radius:12px; overflow:hidden;
    }}
    .sub-card-title {{
      padding:.85rem 1rem; border-bottom:1px solid #e5e7eb; font-weight:600; font-size:.88rem;
      background:#f8fafc;
    }}
    table thead th {{
      background:#f8fafc; color:#64748b; font-size:.74rem; text-transform:uppercase;
      letter-spacing:.04em; border-bottom:2px solid #e5e7eb;
    }}
    table tbody td {{ vertical-align:middle; }}
    code {{
      background:#fff1e6; color:#9a4300; padding:.1em .35em; border-radius:4px; font-size:.78em;
    }}
    .status-pill {{
      display:inline-block; padding:.18rem .55rem; border-radius:999px; font-size:.73rem; font-weight:600;
    }}
    .footer {{ color:#7b8798; font-size:.8rem; padding:1.2rem 0 2rem; text-align:center; }}
  </style>
</head>
<body>

<div class="page-header">
  <div class="container">
    <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
      <span class="tag-pill">CUSTOMER SUCCESS MANAGEMENT VIEW</span>
      <span class="tag-pill">Health + Engagement Focused</span>
      <span class="tag-pill">Scope: {scope_label}</span>
    </div>
    <h1 class="mb-1" style="font-size:1.95rem;font-weight:700">Customer Success Management Dashboard</h1>
    <div class="subtitle">
      Generated {generated_at}
      &nbsp;·&nbsp; objective: retention, growth, and customer value realization
    </div>
  </div>
</div>

<div class="container py-4">
  {section_scorecards(data)}
  {section_adoption_score(data)}
  {section_coverage(data)}
  {section_underutilized(data)}
  {section_trends(data)}
  {section_risk_and_expansion(data)}
</div>

<div class="footer container">
  WSO2 Feature Utilization — Customer Success Management Dashboard
  &nbsp;·&nbsp; Generated {generated_at}
</div>

</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate WSO2 Customer Success Management HTML report")
    parser.add_argument("--api", default="http://127.0.0.1:8001", help="API base URL")
    parser.add_argument("--product", default=None, help="Optional product ID scope")
    parser.add_argument("--version", default=None, help="Optional version scope")
    parser.add_argument("--region", default=None, help="Optional region scope")
    parser.add_argument("--customer-tier", default=None, help="Optional customer tier scope")
    parser.add_argument("--out", default="reports/customer_success.html", help="Output HTML path")
    args = parser.parse_args()

    html = build_html(
        args.api,
        product_id=args.product,
        version=args.version,
        region=args.region,
        customer_tier=args.customer_tier,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"\nReport saved -> {out_path.resolve()}")
    print(f"Open in browser: open {args.out}")


if __name__ == "__main__":
    main()
