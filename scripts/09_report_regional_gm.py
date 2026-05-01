#!/usr/bin/env python3
"""
WSO2 Feature Utilization — Regional Managers Dashboard

Goal:
  Give regional leaders an aggregated, comparative, trend-driven view of
  adoption strength, growth signals, risk, and expansion potential.

Sections:
  1. Regional Adoption Overview
  2. Capability Adoption by Region
  3. Expansion Opportunity Index
  4. Regional Risk Heatmap
  5. Adoption Trends
  6. Customer Maturity Distribution

Usage:
    python3 scripts/09_report_regional_gm.py
    python3 scripts/09_report_regional_gm.py --region eu-west
    python3 scripts/09_report_regional_gm.py --api http://127.0.0.1:8001
    python3 scripts/09_report_regional_gm.py --out reports/regional_managers.html
"""

import argparse
import json
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


PALETTE = [
    "#0b3a67", "#ff7300", "#1f6f78", "#4f772d", "#15528d",
    "#d95f00", "#0f766e", "#9f1239", "#7c3aed", "#b91c1c",
]

STATUS_COLOR = {"green": "#15803d", "amber": "#b45309", "red": "#b91c1c"}
STATUS_BG = {"green": "#dcfce7", "amber": "#fef3c7", "red": "#fee2e2"}
STATUS_LABEL = {"green": "Strong", "amber": "Watch", "red": "Weak"}
RISK_LABEL = {"green": "Low", "amber": "Medium", "red": "High"}
RISK_ICON = {"green": "Low", "amber": "Medium", "red": "High"}
TIER_ORDER = {"core": 1, "premium": 2, "enterprise": 3}

BASIC_CODES = {"is.sso.oidc", "is.sso.saml"}
MFA_PREFIX = "is.mfa."
FEDERATION_PREFIXES = ("is.enterprise-login.", "is.social-login.", "is.federation.", "is.eid-login.")
ADAPTIVE_PREFIX = "is.adaptive-auth."
GOVERNANCE_PREFIX = "is.governance."


def fetch(api_base: str, path: str):
    url = f"{api_base}{path}"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.loads(response.read())
    except Exception as exc:
        print(f"  ERROR fetching {url}: {exc}", file=sys.stderr)
        return None


def fmt_int(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def month_key(value: str) -> str:
    if not value:
        return "unknown"
    return value[:7]


def semver_key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(version).split("."))
    except Exception:
        return (0,)


def can_access_feature(customer_tier: str, feature_tier: str) -> bool:
    customer_rank = TIER_ORDER.get((customer_tier or "core").lower(), 1)
    feature_rank = TIER_ORDER.get((feature_tier or "core").lower(), 1)
    return feature_rank <= customer_rank


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


def status_for_score(score: int) -> str:
    if score >= 70:
        return "green"
    if score >= 40:
        return "amber"
    return "red"


def trend_for_change(change_pct: int) -> tuple[str, str]:
    if change_pct <= -15:
        return "Declining", "down"
    if change_pct >= 15:
        return "Growing", "up"
    return "Stable", "flat"


def compute_trend(monthly_values: dict[str, int]) -> dict:
    months = sorted(monthly_values)
    if len(months) < 2:
        month = months[-1] if months else "N/A"
        return {
            "status": "Baseline only",
            "direction": "flat",
            "change_pct": 0,
            "current_month": month,
            "current": monthly_values.get(month, 0) if months else 0,
            "previous": None,
        }

    previous_month, current_month = months[-2], months[-1]
    previous_total = monthly_values[previous_month]
    current_total = monthly_values[current_month]
    if previous_total == 0:
        change_pct = 100 if current_total > 0 else 0
    else:
        change_pct = round((current_total - previous_total) / previous_total * 100)
    status, direction = trend_for_change(change_pct)
    return {
        "status": status,
        "direction": direction,
        "change_pct": change_pct,
        "current_month": current_month,
        "current": current_total,
        "previous": previous_total,
    }


def opportunity_level(coverage_pct: int) -> str:
    if coverage_pct < 35:
        return "Very High"
    if coverage_pct < 50:
        return "High"
    if coverage_pct < 70:
        return "Medium"
    return "Low"


def load_data(api_base: str, region_filter: str | None = None) -> dict:
    print("Fetching regional managers data...")
    regional = fetch(api_base, "/reports/regional") or {"regions": [], "all_customers": []}
    all_regions = regional.get("regions", [])
    all_customers = regional.get("all_customers", [])
    if not all_customers:
        sys.exit("No customer data found. Is the API running and data seeded?")
    if region_filter and not any(region["region"] == region_filter for region in all_regions):
        available = ", ".join(sorted(region["region"] for region in all_regions))
        sys.exit(f"Region '{region_filter}' not found. Available regions: {available}")

    prod_versions = sorted({
        deployment["version"]
        for customer in all_customers
        for deployment in customer.get("deployments", [])
        if deployment.get("environment") == "prod"
    }, key=semver_key)

    coverage_by_version: dict[str, list] = {}
    for version in prod_versions:
        coverage_by_version[version] = (
            fetch(api_base, f"/reports/catalog/coverage?product_id=identity-server&version={version}") or []
        )

    customer_feature_rows: dict[str, list] = {}
    for customer in all_customers:
        rows = fetch(api_base, f"/reports/customers/{customer['customer_id']}/features") or []
        customer_feature_rows[customer["customer_id"]] = rows

    customer_profiles = []
    feature_meta: dict[str, dict] = {}

    for customer in all_customers:
        customer_id = customer["customer_id"]
        customer_name = customer["customer_name"]
        region = customer.get("region") or "unknown"
        customer_tier = (customer.get("tier") or "core").lower()
        rows = customer_feature_rows.get(customer_id, [])
        prod_rows = [row for row in rows if row.get("environment") == "prod"]

        latest_report_to = max((str(row.get("report_to") or "")) for row in prod_rows) if prod_rows else None
        current_rows = [row for row in prod_rows if str(row.get("report_to") or "") == latest_report_to] if latest_report_to else []

        current_feature_usage: dict[str, dict] = {}
        monthly_events: dict[str, int] = defaultdict(int)
        monthly_enabled: dict[str, set] = defaultdict(set)
        current_versions = sorted({row["version"] for row in current_rows}, key=semver_key)

        for row in prod_rows:
            month = month_key(str(row.get("report_to") or ""))
            monthly_events[month] += row["total_count"]
            monthly_enabled[month].add(row["feature_code"])

        for row in current_rows:
            code = row["feature_code"]
            current_feature_usage.setdefault(code, {
                "feature_code": code,
                "feature_name": row["feature_name"],
                "category": row.get("category") or "Unknown",
                "total_count": 0,
            })
            current_feature_usage[code]["total_count"] += row["total_count"]

        if not current_versions:
            current_versions = sorted({
                deployment["version"]
                for deployment in customer.get("deployments", [])
                if deployment.get("environment") == "prod"
            }, key=semver_key)
            if current_versions:
                current_versions = [current_versions[-1]]

        available_features: dict[str, dict] = {}
        for version in current_versions:
            for feature in coverage_by_version.get(version, []):
                if can_access_feature(customer_tier, feature.get("tier") or "core"):
                    available_features.setdefault(feature["feature_code"], feature)
                    feature_meta.setdefault(feature["feature_code"], {
                        "name": feature["feature_name"],
                        "category": feature.get("category") or "Unknown",
                    })

        enabled_codes = set(current_feature_usage)
        used_codes = {code for code, entry in current_feature_usage.items() if entry["total_count"] > 0}
        total_events = sum(entry["total_count"] for entry in current_feature_usage.values())

        available_by_category: dict[str, set] = defaultdict(set)
        used_by_category: dict[str, set] = defaultdict(set)
        for code, feature in available_features.items():
            available_by_category[feature.get("category") or "Unknown"].add(code)
        for code in used_codes:
            if code in available_features:
                used_by_category[available_features[code].get("category") or "Unknown"].add(code)

        relevant_categories = len(available_by_category)
        adopted_categories = sum(1 for category in available_by_category if used_by_category.get(category))
        adoption_score = round(adopted_categories / relevant_categories * 100) if relevant_categories else 0
        feature_coverage_pct = round(len(used_codes & set(available_features)) / len(available_features) * 100) if available_features else 0
        trend = compute_trend(monthly_events)
        segment = classify_segment(used_codes)

        customer_profiles.append({
            "customer_id": customer_id,
            "customer_name": customer_name,
            "region": region,
            "tier": customer_tier,
            "status": status_for_score(adoption_score),
            "score": adoption_score,
            "coverage_pct": feature_coverage_pct,
            "segment": segment,
            "trend": trend,
            "used_codes": used_codes,
            "enabled_codes": enabled_codes,
            "available_features": available_features,
            "available_by_category": available_by_category,
            "used_by_category": used_by_category,
            "current_feature_usage": current_feature_usage,
            "monthly_events": dict(monthly_events),
            "monthly_enabled": {month: set(values) for month, values in monthly_enabled.items()},
            "total_events": total_events,
            "top_category": max(
                (
                    (category, len(codes))
                    for category, codes in used_by_category.items()
                ),
                key=lambda item: item[1],
                default=("—", 0),
            )[0] if used_by_category else "—",
        })

    region_profiles = []
    portfolio_months = sorted({
        month
        for customer in customer_profiles
        for month in customer["monthly_events"]
    })

    for region_obj in sorted(all_regions, key=lambda item: item["region"]):
        region_name = region_obj["region"]
        customers = [customer for customer in customer_profiles if customer["region"] == region_name]
        if not customers:
            continue

        avg_score = round(sum(customer["score"] for customer in customers) / len(customers))
        avg_coverage = round(sum(customer["coverage_pct"] for customer in customers) / len(customers))
        low_adoption_customers = sum(1 for customer in customers if customer["score"] < 40)
        basic_only_customers = sum(1 for customer in customers if customer["used_codes"] and customer["used_codes"].issubset(BASIC_CODES))
        declining_customers = sum(1 for customer in customers if customer["trend"]["status"] == "Declining")

        monthly_region_events: dict[str, int] = defaultdict(int)
        monthly_region_feature_pct: dict[str, int] = {}
        customer_counts_by_month: dict[str, int] = defaultdict(int)
        used_features_by_month: dict[str, set] = defaultdict(set)
        available_features_union: set[str] = set()

        feature_customer_usage: dict[str, int] = defaultdict(int)
        category_customer_usage: dict[str, int] = defaultdict(int)
        maturity_counts = Counter()
        category_gap_totals: dict[str, list] = defaultdict(list)

        for customer in customers:
            maturity_counts[customer["segment"]] += 1
            available_features_union.update(customer["available_features"].keys())
            for month, total in customer["monthly_events"].items():
                monthly_region_events[month] += total
                customer_counts_by_month[month] += 1
                used_features_by_month[month].update(customer["monthly_enabled"].get(month, set()))

            for code in customer["used_codes"]:
                feature_customer_usage[code] += 1
            for category, used_codes_in_category in customer["used_by_category"].items():
                if used_codes_in_category:
                    category_customer_usage[category] += 1

            for category, codes in customer["available_by_category"].items():
                used_total = len(customer["used_by_category"].get(category, set()))
                category_gap_totals[category].append(round(used_total / len(codes) * 100) if codes else 0)

        for month in portfolio_months:
            if month not in monthly_region_events:
                continue
            enabled_total = len(used_features_by_month.get(month, set()))
            available_total = len(available_features_union)
            monthly_region_feature_pct[month] = round(enabled_total / available_total * 100) if available_total else 0

        trend = compute_trend(monthly_region_events)
        latest_month = trend["current_month"]
        trend_pct = monthly_region_feature_pct.get(latest_month, avg_coverage if latest_month != "N/A" else avg_coverage)

        if avg_score < 40 or (trend["status"] == "Declining" and low_adoption_customers >= max(1, len(customers) // 3)):
            risk_level = "red"
        elif avg_score < 55 or trend["status"] == "Declining" or low_adoption_customers > 0 or basic_only_customers > 0:
            risk_level = "amber"
        else:
            risk_level = "green"

        reasons = []
        if avg_score < 40:
            reasons.append("Low regional adoption")
        elif avg_score < 55:
            reasons.append("Moderate regional adoption")
        if trend["status"] == "Declining":
            reasons.append("Usage declining")
        if low_adoption_customers > 0:
            reasons.append(f"{low_adoption_customers} low-adoption customer(s)")
        if basic_only_customers > 0:
            reasons.append(f"{basic_only_customers} basic-auth-only customer(s)")
        if not reasons:
            reasons.append("Healthy adoption and stable demand")

        category_adoption_pct = {
            category: round(count / len(customers) * 100)
            for category, count in category_customer_usage.items()
        }
        for category in category_gap_totals:
            category_adoption_pct.setdefault(category, 0)

        sorted_category_opportunities = sorted(
            (
                {
                    "category": category,
                    "coverage_pct": round(sum(values) / len(values)) if values else 0,
                    "reach_pct": category_adoption_pct.get(category, 0),
                }
                for category, values in category_gap_totals.items()
            ),
            key=lambda row: (row["coverage_pct"], row["reach_pct"], row["category"])
        )
        top_opportunities = sorted_category_opportunities[:3]

        region_profiles.append({
            "region": region_name,
            "customer_count": len(customers),
            "avg_score": avg_score,
            "avg_coverage": avg_coverage,
            "trend": trend,
            "trend_pct": trend_pct,
            "risk_level": risk_level,
            "risk_reason": " + ".join(reasons[:2]),
            "opportunity_level": opportunity_level(avg_coverage),
            "top_opportunities": top_opportunities,
            "feature_customer_usage": feature_customer_usage,
            "category_customer_usage": category_customer_usage,
            "category_adoption_pct": category_adoption_pct,
            "monthly_events": dict(monthly_region_events),
            "monthly_feature_pct": monthly_region_feature_pct,
            "maturity_counts": maturity_counts,
        })

    region_profiles = sorted(region_profiles, key=lambda row: row["region"])

    top_category_candidates: dict[str, dict] = {}
    for region in region_profiles:
        for category, count in region["category_customer_usage"].items():
            top_category_candidates.setdefault(category, {
                "category": category,
                "regions_using": 0,
                "customer_count": 0,
            })
            if count > 0:
                top_category_candidates[category]["regions_using"] += 1
                top_category_candidates[category]["customer_count"] += count

    top_categories = sorted(
        top_category_candidates.values(),
        key=lambda row: (-row["regions_using"], -row["customer_count"], row["category"])
    )[:10]

    selected_region = None
    selected_customers = []
    if region_filter:
        selected_region = next((region for region in region_profiles if region["region"] == region_filter), None)
        selected_customers = sorted(
            [customer for customer in customer_profiles if customer["region"] == region_filter],
            key=lambda row: (-row["score"], -row["total_events"], row["customer_name"])
        )

    return {
        "regions": region_profiles,
        "portfolio_months": portfolio_months,
        "top_categories": top_categories,
        "feature_meta": feature_meta,
        "selected_region": selected_region,
        "selected_customers": selected_customers,
        "region_filter": region_filter,
    }


def section_scorecards(data: dict) -> str:
    regions = data["regions"]
    total_regions = len(regions)
    avg_score = round(sum(region["avg_score"] for region in regions) / total_regions) if total_regions else 0
    growing = sum(1 for region in regions if region["trend"]["status"] == "Growing")
    declining = sum(1 for region in regions if region["trend"]["status"] == "Declining")
    high_opportunity = sum(1 for region in regions if region["opportunity_level"] in {"High", "Very High"})
    high_risk = sum(1 for region in regions if region["risk_level"] == "red")

    labels = json.dumps([region["region"] for region in regions])
    scores = json.dumps([region["avg_score"] for region in regions])
    colors = json.dumps([STATUS_COLOR[status_for_score(region["avg_score"])] for region in regions])

    return f"""
<div class="row g-3 mb-4">
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value text-primary">{total_regions}</div>
      <div class="label">Regions</div>
      <div class="sub">compared markets</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#1d4ed8">{avg_score}%</div>
      <div class="label">Avg Adoption</div>
      <div class="sub">regional health</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#15803d">{growing}</div>
      <div class="label">Growing</div>
      <div class="sub">positive momentum</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#b91c1c">{declining}</div>
      <div class="label">Declining</div>
      <div class="sub">needs attention</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#b45309">{high_opportunity}</div>
      <div class="label">High Opportunity</div>
      <div class="sub">coverage gap regions</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#b91c1c">{high_risk}</div>
      <div class="label">High Risk</div>
      <div class="sub">regional warning</div>
    </div>
  </div>
  <div class="col-12">
    <div class="section-card" style="margin-bottom:0">
      <div class="card-header" style="padding:.7rem 1rem;font-size:.84rem">Regional Adoption Snapshot</div>
      <div class="card-body" style="padding:1rem 1.2rem">
        <div class="text-muted mb-3" style="font-size:.82rem">
          This top view compares regions at a portfolio level.
          Adoption is the average customer adoption score in that region.
          Growing / Declining come from month-over-month production usage trends.
        </div>
        <div class="text-muted mb-3" style="font-size:.82rem">
          Avg Adoption summarizes how broadly customers in a region are using the product.
          High Opportunity means there is still a large gap between what customers could use and what they actually use.
          High Risk means the region shows weaker adoption, a negative trend, or both.
        </div>
        <div style="position:relative;height:280px"><canvas id="regionalScoreChart"></canvas></div>
      </div>
    </div>
  </div>
</div>
<script>
new Chart(document.getElementById('regionalScoreChart'), {{
  type: 'bar',
  data: {{
    labels: {labels},
    datasets: [{{ data: {scores}, backgroundColor: {colors}, borderRadius: 6 }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ display: false }} }},
      y: {{ max: 100, grid: {{ color: '#eef2f7' }}, ticks: {{ callback: value => value + '%' }} }}
    }}
  }}
}});
</script>"""


def section_adoption_overview(data: dict) -> str:
    rows = ""
    for region in sorted(data["regions"], key=lambda row: (-row["avg_score"], row["region"])):
        trend = region["trend"]
        if trend["direction"] == "up":
            icon = "↑"
            color = STATUS_COLOR["green"]
        elif trend["direction"] == "down":
            icon = "↓"
            color = STATUS_COLOR["red"]
        else:
            icon = "→"
            color = "#64748b"
        change_label = f"{trend['change_pct']}%" if trend["previous"] is not None else "—"
        rows += f"""
        <tr>
          <td class="ps-3"><strong>{region['region']}</strong></td>
          <td class="text-center">{region['customer_count']}</td>
          <td class="text-center"><strong style="color:{STATUS_COLOR[status_for_score(region['avg_score'])]}">{region['avg_score']}%</strong></td>
          <td><span style="color:{color};font-weight:600">{icon} {trend['status']}</span></td>
          <td class="text-muted">{change_label}</td>
        </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    1. Regional Adoption Overview
    <span class="text-muted fw-normal" style="font-size:.82rem"> — average customer adoption score by region and its recent direction</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      Avg Adoption Score shows how broadly customers in that region are using the product.
      Trend compares the last two months of regional production usage.
      A higher score and an upward trend usually indicate a stronger market position.
    </div>
    <div class="text-muted mb-3" style="font-size:.82rem">
      Trend shows direction, while Change shows the percentage increase or decrease in total production usage between the latest two months available for that region.
      Regions with both low adoption and a negative trend usually need the fastest commercial attention.
    </div>
    <div class="text-muted mb-3" style="font-size:.82rem">
      If Change shows <strong>—</strong>, that region only has one month of reporting data right now, so the report cannot yet tell whether it is growing or declining.
    </div>
    <table class="table table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Region</th>
          <th class="text-center">Customers</th>
          <th class="text-center">Avg Adoption Score</th>
          <th>Trend</th>
          <th>Change</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""


def section_feature_adoption(data: dict) -> str:
    regions = data["regions"]
    top_categories = data["top_categories"]
    if not regions or not top_categories:
        return ""

    header_cells = "".join(f'<th class="text-center">{region["region"]}</th>' for region in regions)
    body = ""
    for category in top_categories:
        cells = ""
        for region in regions:
            reach_pct = region["category_adoption_pct"].get(category["category"], 0)
            color = STATUS_COLOR["green"] if reach_pct >= 60 else STATUS_COLOR["amber"] if reach_pct >= 30 else STATUS_COLOR["red"]
            cells += f'<td class="text-center"><strong style="color:{color}">{reach_pct}%</strong></td>'
        body += f"""
        <tr>
          <td class="ps-3"><strong>{category['category']}</strong><div class="text-muted" style="font-size:.76rem">{category['customer_count']} customer activations across regions</div></td>
          {cells}
        </tr>"""

    chart_labels = json.dumps([category["category"] for category in top_categories[:8]])
    datasets = []
    for index, region in enumerate(regions):
        datasets.append({
            "label": region["region"],
            "data": [region["category_adoption_pct"].get(category["category"], 0) for category in top_categories[:8]],
            "backgroundColor": PALETTE[index % len(PALETTE)],
            "borderRadius": 3,
        })
    chart_datasets = json.dumps(datasets)

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    2. Capability Adoption by Region
    <span class="text-muted fw-normal" style="font-size:.82rem"> — which product categories have the strongest customer reach in each region</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      Each percentage shows how many customers in that region are actively using at least one feature in that category in the latest production snapshot.
      This helps reveal regional capability preferences without overwhelming the report with feature-level noise.
    </div>
    <div class="text-muted mb-3" style="font-size:.82rem">
      A value like 100% means every customer in that region is using that category now.
      A lower value means the category is either niche in that market or still a strong GTM opportunity.
    </div>
    <div style="position:relative;height:320px;margin-bottom:1rem"><canvas id="featureRegionChart"></canvas></div>
    <table class="table table-sm table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Category</th>
          {header_cells}
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</div>
<script>
new Chart(document.getElementById('featureRegionChart'), {{
  type: 'bar',
  data: {{
    labels: {chart_labels},
    datasets: {chart_datasets}
  }},
  options: {{
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ font: {{ size: 10 }}, boxWidth: 12 }} }}
    }},
    scales: {{
      x: {{ stacked: false, ticks: {{ font: {{ size: 10 }} }} }},
      y: {{ max: 100, grid: {{ color: '#eef2f7' }}, ticks: {{ callback: value => value + '%' }} }}
    }}
  }}
}});
</script>"""


def section_opportunity(data: dict) -> str:
    rows = ""
    for region in sorted(data["regions"], key=lambda row: (row["avg_coverage"], row["region"])):
        rows += f"""
        <tr>
          <td class="ps-3"><strong>{region['region']}</strong></td>
          <td class="text-center">{region['avg_coverage']}%</td>
          <td><span class="status-pill" style="background:{STATUS_BG[status_for_score(region['avg_coverage'])]};color:{STATUS_COLOR[status_for_score(region['avg_coverage'])]}">{region['opportunity_level']}</span></td>
          <td class="text-muted">{", ".join(op['category'] for op in region['top_opportunities'][:2])}</td>
        </tr>"""

    labels = json.dumps([region["region"] for region in data["regions"]])
    values = json.dumps([region["avg_coverage"] for region in data["regions"]])

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    3. Expansion Opportunity Index
    <span class="text-muted fw-normal" style="font-size:.82rem"> — how much of the available product is being used in each region</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      Coverage % is the average share of available features that customers in the region are actively using.
      Lower coverage means more room for upsell, education, and regional campaigns.
    </div>
    <div class="text-muted mb-3" style="font-size:.82rem">
      Primary Opportunity points to the next product area or capability that could create growth in that region.
      Very High or High opportunity regions are usually the best places to focus expansion messaging and field effort.
    </div>
    <div style="position:relative;height:260px;margin-bottom:1rem"><canvas id="opportunityChart"></canvas></div>
    <table class="table table-sm table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Region</th>
          <th class="text-center">Coverage %</th>
          <th>Opportunity Level</th>
          <th>Primary Opportunity</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
<script>
new Chart(document.getElementById('opportunityChart'), {{
  type: 'bar',
  data: {{
    labels: {labels},
    datasets: [{{
      data: {values},
      backgroundColor: {json.dumps([PALETTE[i % len(PALETTE)] for i in range(len(data["regions"]))])},
      borderRadius: 6
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ display: false }} }},
      y: {{ max: 100, grid: {{ color: '#eef2f7' }}, ticks: {{ callback: value => value + '%' }} }}
    }}
  }}
}});
</script>"""


def section_risk(data: dict) -> str:
    rows = ""
    for region in sorted(data["regions"], key=lambda row: (row["risk_level"] != "red", row["risk_level"] != "amber", row["region"])):
        rows += f"""
        <tr>
          <td class="ps-3"><strong>{region['region']}</strong></td>
          <td><span class="status-pill" style="background:{STATUS_BG[region['risk_level']]};color:{STATUS_COLOR[region['risk_level']]}">{RISK_LABEL[region['risk_level']]}</span></td>
          <td>{region['risk_reason']}</td>
          <td class="text-center">{region['trend']['status']}</td>
        </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    4. Regional Risk Heatmap
    <span class="text-muted fw-normal" style="font-size:.82rem"> — where adoption weakness or softening demand may need intervention</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      Risk Level combines regional adoption strength, recent usage trend, and concentration of weaker customers.
      Use this section to decide where sales, customer success, or GTM support may need to step in first.
    </div>
    <div class="text-muted mb-3" style="font-size:.82rem">
      Low risk means the region is broadly healthy.
      Medium risk means growth may be slow or adoption is only moderate.
      High risk means the region shows a meaningful warning sign such as low adoption, clear decline, or both.
    </div>
    <table class="table table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Region</th>
          <th>Risk Level</th>
          <th>Reason</th>
          <th class="text-center">Trend</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""


def section_trends(data: dict) -> str:
    regions = data["regions"]
    months = data["portfolio_months"]
    if not regions or not months:
        return ""

    datasets = []
    for index, region in enumerate(regions):
        datasets.append({
            "label": region["region"],
            "data": [region["monthly_feature_pct"].get(month) for month in months],
            "borderColor": PALETTE[index % len(PALETTE)],
            "backgroundColor": "transparent",
            "tension": 0.25,
            "pointRadius": 4,
        })

    header_cells = "".join(f'<th class="text-center">{month}</th>' for month in months)
    body = ""
    for region in regions:
        cells = "".join(
            f'<td class="text-center"><strong>{region["monthly_feature_pct"][month]}%</strong></td>' if month in region["monthly_feature_pct"]
            else '<td class="text-center text-muted">—</td>'
            for month in months
        )
        body += f"""
        <tr>
          <td class="ps-3"><strong>{region['region']}</strong></td>
          {cells}
        </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    5. Adoption Trends
    <span class="text-muted fw-normal" style="font-size:.82rem"> — regional movement over time based on monthly feature usage breadth</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      The chart shows how broadly each region is using the product over time.
      Each monthly percentage compares the number of features used in that month against the total feature set currently available in that region.
      Rising lines suggest successful regional adoption momentum; falling lines are an early warning sign.
    </div>
    <div class="text-muted mb-3" style="font-size:.82rem">
      Use this view to compare momentum across regions, not just current size.
      A region with a lower current score but a rising trend may deserve more investment than a larger region that is flattening or slipping.
    </div>
    <div style="position:relative;height:320px;margin-bottom:1rem"><canvas id="regionalTrendChart"></canvas></div>
    <table class="table table-sm table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Region</th>
          {header_cells}
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</div>
<script>
new Chart(document.getElementById('regionalTrendChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(months)},
    datasets: {json.dumps(datasets)}
  }},
  options: {{
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ font: {{ size: 10 }}, boxWidth: 12 }} }}
    }},
    scales: {{
      x: {{ grid: {{ color: '#eef2f7' }} }},
      y: {{ max: 100, grid: {{ color: '#eef2f7' }}, ticks: {{ callback: value => value + '%' }} }}
    }}
  }}
}});
</script>"""


def section_maturity(data: dict) -> str:
    rows = ""
    for region in data["regions"]:
        total = max(region["customer_count"], 1)
        beginner = round(region["maturity_counts"].get("Beginner", 0) / total * 100)
        intermediate = round(region["maturity_counts"].get("Intermediate", 0) / total * 100)
        advanced = round(region["maturity_counts"].get("Advanced", 0) / total * 100)
        rows += f"""
        <tr>
          <td class="ps-3"><strong>{region['region']}</strong></td>
          <td class="text-center">{beginner}%</td>
          <td class="text-center">{intermediate}%</td>
          <td class="text-center">{advanced}%</td>
        </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    6. Customer Maturity Distribution
    <span class="text-muted fw-normal" style="font-size:.82rem"> — how advanced each region’s customer base is today</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      Beginner means customers are mostly using basic login.
      Intermediate means they have moved into MFA or federation.
      Advanced means they are using deeper capabilities such as adaptive authentication or governance.
    </div>
    <div class="text-muted mb-3" style="font-size:.82rem">
      A region with more Advanced customers is generally more mature and may be ready for deeper platform positioning.
      A region with more Beginner customers may need simpler packaging, onboarding, and education.
    </div>
    <table class="table table-sm table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Region</th>
          <th class="text-center">Beginner</th>
          <th class="text-center">Intermediate</th>
          <th class="text-center">Advanced</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""


def section_region_summary(data: dict) -> str:
    region = data["selected_region"]
    if not region:
        return ""

    trend = region["trend"]
    if trend["direction"] == "up":
        trend_label = "Growing"
        trend_color = STATUS_COLOR["green"]
    elif trend["direction"] == "down":
        trend_label = "Declining"
        trend_color = STATUS_COLOR["red"]
    else:
        trend_label = trend["status"]
        trend_color = "#64748b"

    return f"""
<div class="row g-3 mb-4">
  <div class="col-6 col-md-3">
    <div class="stat-card">
      <div class="value text-primary">{region['customer_count']}</div>
      <div class="label">Customers</div>
      <div class="sub">in this region</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="stat-card">
      <div class="value" style="color:{STATUS_COLOR[status_for_score(region['avg_score'])]}">{region['avg_score']}%</div>
      <div class="label">Adoption</div>
      <div class="sub">regional average</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:{trend_color}">{trend['change_pct']}%</div>
      <div class="label">Trend</div>
      <div class="sub">{trend_label}</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#b45309">{region['avg_coverage']}%</div>
      <div class="label">Coverage</div>
      <div class="sub">{region['opportunity_level']} opportunity</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:{STATUS_COLOR[region['risk_level']]}">{RISK_LABEL[region['risk_level']]}</div>
      <div class="label">Risk</div>
      <div class="sub">{region['risk_reason']}</div>
    </div>
  </div>
</div>"""


def section_region_capabilities(data: dict) -> str:
    region = data["selected_region"]
    customers = data["selected_customers"]
    if not region or not customers:
        return ""

    category_rows = []
    all_categories = sorted(region["category_adoption_pct"])
    for category in all_categories:
        reach_pct = region["category_adoption_pct"].get(category, 0)
        customer_count = region["category_customer_usage"].get(category, 0)
        category_rows.append({
            "category": category,
            "reach_pct": reach_pct,
            "customer_count": customer_count,
        })

    strongest_rows = sorted(
        category_rows,
        key=lambda row: (-row["reach_pct"], -row["customer_count"], row["category"]),
    )
    weakest_rows = sorted(
        category_rows,
        key=lambda row: (row["reach_pct"], row["category"]),
    )

    chart_rows = []
    seen_categories = set()
    for row in strongest_rows:
        if row["reach_pct"] > 0 and row["category"] not in seen_categories:
            chart_rows.append(row)
            seen_categories.add(row["category"])
        if len(chart_rows) >= 5:
            break
    for row in weakest_rows:
        if row["category"] not in seen_categories:
            chart_rows.append(row)
            seen_categories.add(row["category"])
        if len(chart_rows) >= 8:
            break

    table_rows = sorted(
        category_rows,
        key=lambda row: (-row["reach_pct"], -row["customer_count"], row["category"]),
    )[:12]

    body = ""
    for row in table_rows:
        color = STATUS_COLOR["green"] if row["reach_pct"] >= 60 else STATUS_COLOR["amber"] if row["reach_pct"] >= 30 else STATUS_COLOR["red"]
        body += f"""
        <tr>
          <td class="ps-3"><strong>{row['category']}</strong></td>
          <td class="text-center">{row['customer_count']} / {region['customer_count']}</td>
          <td class="text-center"><strong style="color:{color}">{row['reach_pct']}%</strong></td>
        </tr>"""

    labels = json.dumps([row["category"] for row in chart_rows])
    values = json.dumps([row["reach_pct"] for row in chart_rows])

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    2. Capability Adoption in This Region
    <span class="text-muted fw-normal" style="font-size:.82rem"> — which categories are broadly used vs under-adopted in {region['region']}</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      Reach % shows what share of customers in this region are using at least one feature in the category.
      The chart mixes strongest categories with a few weakest ones, so you can quickly see both what is working and what is missing.
      Lower reach categories are usually the best places to focus regional field campaigns, onboarding, and messaging.
    </div>
    <div style="position:relative;height:300px;margin-bottom:1rem"><canvas id="regionCapabilityChart"></canvas></div>
    <table class="table table-sm table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Category</th>
          <th class="text-center">Customers Using</th>
          <th class="text-center">Reach %</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</div>
<script>
new Chart(document.getElementById('regionCapabilityChart'), {{
  type: 'bar',
  data: {{
    labels: {labels},
    datasets: [{{
      data: {values},
      backgroundColor: {json.dumps([PALETTE[i % len(PALETTE)] for i in range(min(8, len(category_rows)))])},
      borderRadius: 6
    }}]
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


def section_region_customers(data: dict) -> str:
    customers = data["selected_customers"]
    region = data["selected_region"]
    if not region or not customers:
        return ""

    body = ""
    for customer in sorted(customers, key=lambda row: (row["score"], row["total_events"], row["customer_name"])):
        trend = customer["trend"]
        change = f"{trend['change_pct']}%" if trend["previous"] is not None else "—"
        body += f"""
        <tr>
          <td class="ps-3"><strong>{customer['customer_name']}</strong></td>
          <td class="text-center"><strong style="color:{STATUS_COLOR[status_for_score(customer['score'])]}">{customer['score']}%</strong></td>
          <td>{customer['top_category']}</td>
          <td class="text-end">{fmt_int(customer['total_events'])}</td>
          <td class="text-center">{trend['status']}</td>
          <td class="text-center">{change}</td>
        </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    3. Customer Contribution
    <span class="text-muted fw-normal" style="font-size:.82rem"> — which accounts are driving or weakening the regional picture</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      This is the one place where the region view goes customer-level.
      It helps a Regional GM see whether momentum is broad-based or driven by only one or two accounts.
    </div>
    <table class="table table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Customer</th>
          <th class="text-center">Adoption</th>
          <th>Strongest Category</th>
          <th class="text-end">Current Usage</th>
          <th class="text-center">Trend</th>
          <th class="text-center">Change</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</div>"""


def section_region_opportunities(data: dict) -> str:
    region = data["selected_region"]
    if not region:
        return ""

    body = ""
    for item in region["top_opportunities"]:
        body += f"""
        <tr>
          <td class="ps-3"><strong>{item['category']}</strong></td>
          <td class="text-center">{item['reach_pct']}%</td>
          <td class="text-center">{item['coverage_pct']}%</td>
          <td>{'Grow category usage in more accounts' if item['reach_pct'] < 50 else 'Deepen usage within existing accounts'}</td>
        </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    4. Expansion Opportunities
    <span class="text-muted fw-normal" style="font-size:.82rem"> — where this region still has the best growth headroom</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      Reach % tells you how widely the category is used across accounts in this region.
      Coverage % reflects how deeply customers use that category once it is available.
      Low reach and low coverage together point to the strongest regional upsell opportunities.
    </div>
    <table class="table table-sm table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Category</th>
          <th class="text-center">Reach %</th>
          <th class="text-center">Coverage %</th>
          <th>Recommended Focus</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</div>"""


def section_region_risk(data: dict) -> str:
    customers = data["selected_customers"]
    region = data["selected_region"]
    if not region or not customers:
        return ""

    risky = []
    for customer in customers:
        reasons = []
        if customer["score"] < 40:
            reasons.append("Low adoption")
        if customer["trend"]["status"] == "Declining":
            reasons.append("Declining usage")
        if customer["used_codes"] and customer["used_codes"].issubset(BASIC_CODES):
            reasons.append("Basic auth only")
        if reasons:
            risky.append((customer, reasons))

    if not risky:
        body = '<tr><td colspan="3" class="ps-3 text-muted">No high-priority account risk signals detected in this region.</td></tr>'
    else:
        body = ""
        for customer, reasons in risky:
            body += f"""
            <tr>
              <td class="ps-3"><strong>{customer['customer_name']}</strong></td>
              <td>{", ".join(reasons)}</td>
              <td class="text-center">{customer['trend']['status']}</td>
            </tr>"""

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    5. Risk Watchlist
    <span class="text-muted fw-normal" style="font-size:.82rem"> — accounts most likely to drag the region down</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      This section isolates customers whose adoption or recent trend may be weakening the region.
      It gives a Regional GM a short list for targeted field follow-up and customer success support.
    </div>
    <table class="table table-sm table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Customer</th>
          <th>Risk Reason</th>
          <th class="text-center">Trend</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</div>"""


def section_region_trend(data: dict) -> str:
    region = data["selected_region"]
    if not region:
        return ""

    months = data["portfolio_months"]
    values = [region["monthly_feature_pct"].get(month) for month in months]
    cells = "".join(
        f'<td class="text-center"><strong>{region["monthly_feature_pct"][month]}%</strong></td>' if month in region["monthly_feature_pct"]
        else '<td class="text-center text-muted">—</td>'
        for month in months
    )
    headers = "".join(f'<th class="text-center">{month}</th>' for month in months)

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    6. Regional Trend Over Time
    <span class="text-muted fw-normal" style="font-size:.82rem"> — how adoption breadth is moving over time in {region['region']}</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      This trend shows whether the selected region is broadening or narrowing its real product usage over time.
      It is especially useful for seeing whether regional programs are taking effect.
    </div>
    <div style="position:relative;height:280px;margin-bottom:1rem"><canvas id="singleRegionTrendChart"></canvas></div>
    <table class="table table-sm table-hover mb-0">
      <thead><tr><th class="ps-3">Region</th>{headers}</tr></thead>
      <tbody><tr><td class="ps-3"><strong>{region['region']}</strong></td>{cells}</tr></tbody>
    </table>
  </div>
</div>
<script>
new Chart(document.getElementById('singleRegionTrendChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(months)},
    datasets: [{{
      label: '{region["region"]}',
      data: {json.dumps(values)},
      borderColor: '#1f6f78',
      backgroundColor: 'transparent',
      tension: 0.25,
      pointRadius: 4
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: '#eef2f7' }} }},
      y: {{ max: 100, grid: {{ color: '#eef2f7' }}, ticks: {{ callback: value => value + '%' }} }}
    }}
  }}
}});
</script>"""


def section_region_maturity(data: dict) -> str:
    region = data["selected_region"]
    if not region:
        return ""

    total = max(region["customer_count"], 1)
    beginner = round(region["maturity_counts"].get("Beginner", 0) / total * 100)
    intermediate = round(region["maturity_counts"].get("Intermediate", 0) / total * 100)
    advanced = round(region["maturity_counts"].get("Advanced", 0) / total * 100)

    return f"""
<div class="section-card mb-4">
  <div class="card-header">
    7. Customer Maturity Mix
    <span class="text-muted fw-normal" style="font-size:.82rem"> — how advanced the customer base is in {region['region']}</span>
  </div>
  <div class="card-body">
    <div class="text-muted mb-3" style="font-size:.82rem">
      This mix helps a Regional GM decide whether the market needs foundational adoption work or is ready for more advanced positioning.
    </div>
    <table class="table table-sm table-hover mb-0">
      <thead>
        <tr>
          <th class="ps-3">Region</th>
          <th class="text-center">Beginner</th>
          <th class="text-center">Intermediate</th>
          <th class="text-center">Advanced</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td class="ps-3"><strong>{region['region']}</strong></td>
          <td class="text-center">{beginner}%</td>
          <td class="text-center">{intermediate}%</td>
          <td class="text-center">{advanced}%</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>"""


def build_html(api_base: str, region_filter: str | None = None) -> str:
    data = load_data(api_base, region_filter=region_filter)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    page_title = f"Regional Managers Dashboard — {region_filter}" if region_filter else "Regional Managers Dashboard"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
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
    table thead th {{
      background:#f8fafc; color:#64748b; font-size:.74rem; text-transform:uppercase;
      letter-spacing:.04em; border-bottom:2px solid #e5e7eb;
    }}
    table tbody td {{ vertical-align:middle; }}
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
      <span class="tag-pill">REGIONAL MANAGERS VIEW</span>
      <span class="tag-pill">{region_filter if region_filter else 'All Regions'}</span>
      <span class="tag-pill">{'Operational Regional Focus' if region_filter else 'Aggregated + Comparative'}</span>
      <span class="tag-pill">Growth + GTM Focused</span>
    </div>
    <h1 class="mb-1" style="font-size:1.95rem;font-weight:700">{page_title}</h1>
    <div class="subtitle">
      Generated {generated_at}
      &nbsp;·&nbsp; objective: regional growth, adoption strength, and GTM prioritization
    </div>
  </div>
</div>

<div class="container py-4">
  {section_region_summary(data) if region_filter else section_scorecards(data)}
  {section_region_capabilities(data) if region_filter else section_adoption_overview(data)}
  {section_region_customers(data) if region_filter else section_feature_adoption(data)}
  {section_region_opportunities(data) if region_filter else section_opportunity(data)}
  {section_region_risk(data) if region_filter else section_risk(data)}
  {section_region_trend(data) if region_filter else section_trends(data)}
  {section_region_maturity(data) if region_filter else section_maturity(data)}
</div>

<div class="footer container">
  WSO2 Feature Utilization — {page_title}
  &nbsp;·&nbsp; Generated {generated_at}
</div>

</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate WSO2 Regional Managers HTML report")
    parser.add_argument("--api", default="http://127.0.0.1:8001", help="API base URL")
    parser.add_argument("--out", default="reports/regional_managers.html", help="Output HTML path")
    parser.add_argument("--region", help="Generate a focused report for a single region, e.g. eu-west")
    args = parser.parse_args()

    html = build_html(args.api, region_filter=args.region)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"\nReport saved -> {out_path.resolve()}")
    print(f"Open in browser: open {args.out}")


if __name__ == "__main__":
    main()
