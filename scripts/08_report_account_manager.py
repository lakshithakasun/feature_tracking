#!/usr/bin/env python3
"""
WSO2 Feature Utilization — Technical Owner Dashboard (Per Account)

Account-specific report for architects / technical leads who need to understand:
  - what is enabled vs actually used
  - where configurations look weak or redundant
  - which flows are carrying traffic
  - where security posture can improve
  - what concrete technical actions to take next

Examples:
  python3 scripts/08_report_account_manager.py --list-customers
  python3 scripts/08_report_account_manager.py --customer acme-corp
  python3 scripts/08_report_account_manager.py --customer umbrella --out reports/technical_owner_umbrella.html
"""

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def fetch(api_base: str, path: str):
    url = f"{api_base}{path}"
    try:
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read())
    except Exception as exc:
        print(f"ERROR fetching {url}: {exc}", file=sys.stderr)
        return None


def parse_dt(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value)


def is_prod(environment: str | None) -> bool:
    env = (environment or "").lower()
    return "prod" in env


def is_staging(environment: str | None) -> bool:
    env = (environment or "").lower()
    return "stag" in env


def fmt_int(value: int) -> str:
    return f"{int(value):,}"


def fmt_pct(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"{round(value)}%"


def merge_dimensions(target: dict, incoming: dict | None):
    if not incoming or not isinstance(incoming, dict):
        return
    for dim_key, dim_val in incoming.items():
        if isinstance(dim_val, dict):
            bucket = target.setdefault(dim_key, {})
            for value, count in dim_val.items():
                bucket[value] = bucket.get(value, 0) + int(count or 0)
        else:
            bucket = target.setdefault(dim_key, {})
            key = str(dim_val)
            bucket[key] = bucket.get(key, 0) + 1


def summarize_snapshot(rows: list[dict]) -> dict[str, dict]:
    feature_map: dict[str, dict] = {}
    for row in rows:
        code = row["feature_code"]
        feature = feature_map.setdefault(code, {
            "code": code,
            "name": row["feature_name"],
            "category": row["category"],
            "total_count": 0,
            "dimensions": {},
            "environments": set(),
            "report_to": row["report_to"],
            "report_from": row["report_from"],
            "version": row["version"],
        })
        feature["total_count"] += int(row.get("total_count") or 0)
        feature["environments"].add(row.get("environment") or "?")
        merge_dimensions(feature["dimensions"], row.get("dimension_breakdown"))
    return feature_map


def latest_period_rows(rows: list[dict], env_filter) -> tuple[list[dict], list[dict], str | None, str | None]:
    matching = [row for row in rows if env_filter(row.get("environment"))]
    periods = sorted({row["report_to"] for row in matching if row.get("report_to")}, key=parse_dt)
    if not periods:
        return [], [], None, None
    latest = periods[-1]
    previous = periods[-2] if len(periods) > 1 else None
    latest_rows = [row for row in matching if row.get("report_to") == latest]
    previous_rows = [row for row in matching if previous and row.get("report_to") == previous]
    return latest_rows, previous_rows, latest, previous


def category_totals(feature_map: dict[str, dict]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for feature in feature_map.values():
        totals[feature["category"]] += feature["total_count"]
    return dict(totals)


def infer_flow_family(feature: dict) -> str:
    category = feature["category"]
    dims = feature.get("dimensions", {})
    if isinstance(dims.get("action"), dict) and dims["action"]:
        return f"{category} - operational path"
    if isinstance(dims.get("outcome"), dict) and dims["outcome"]:
        return f"{category} - decision path"
    return category


def flow_usage(feature_map: dict[str, dict]) -> list[dict]:
    flows: dict[str, int] = defaultdict(int)
    for feature in feature_map.values():
        if feature["total_count"] <= 0:
            continue
        flows[infer_flow_family(feature)] += feature["total_count"]
    rows = [
        {"flow": flow, "total_count": total}
        for flow, total in flows.items()
    ]
    rows.sort(key=lambda row: (-row["total_count"], row["flow"]))
    if not rows:
        return []
    max_total = rows[0]["total_count"]
    for row in rows:
        if row["total_count"] >= max_total * 0.55:
            row["usage_band"] = "High"
        elif row["total_count"] >= max_total * 0.2:
            row["usage_band"] = "Medium"
        else:
            row["usage_band"] = "Low"
    return rows


def status_class(label: str) -> str:
    return {
        "Healthy": "good",
        "Monitor": "info",
        "Underused": "warn",
        "Configured / Unused": "warn",
        "Not Enabled": "muted",
        "Needs Review": "bad",
    }.get(label, "muted")


def usage_band(total_count: int, max_total: int) -> str:
    if total_count <= 0:
        return "—"
    if max_total <= 0:
        return "Low"
    ratio = total_count / max_total
    if ratio >= 0.4:
        return "High"
    if ratio >= 0.12:
        return "Medium"
    return "Low"


def matrix_status(enabled: bool, active: bool, catalog_status: str, band: str) -> str:
    if not enabled:
        return "Not Enabled"
    if catalog_status == "deprecated":
        return "Needs Review"
    if not active:
        return "Configured / Unused"
    if catalog_status == "beta":
        return "Monitor"
    if band == "Low":
        return "Underused"
    return "Healthy"


def dimension_total(dims: dict, key: str, values: tuple[str, ...]) -> int:
    bucket = dims.get(key, {})
    if not isinstance(bucket, dict):
        return 0
    total = 0
    for item in values:
        total += int(bucket.get(item, 0) or 0)
    return total


def failure_summary(feature: dict) -> tuple[int, int, int]:
    dims = feature.get("dimensions", {})
    success = 0
    failure = 0
    for key in ("action", "outcome"):
        success += dimension_total(dims, key, ("login-success", "verify", "verified", "triggered", "success"))
        failure += dimension_total(dims, key, ("login-failed", "verify-failed", "failed", "expired", "access-denied"))
    total = success + failure
    return success, failure, total


def usage_metric(feature: dict) -> str:
    success, failure, observed = failure_summary(feature)
    if observed > 0:
        rate = round(success / observed * 100) if observed else 0
        return f"Success rate {rate}%"

    dims = feature.get("dimensions", {})
    action = dims.get("action", {})
    outcome = dims.get("outcome", {})
    if isinstance(outcome, dict) and outcome:
        step_up = int(outcome.get("step-up-triggered", 0) or 0)
        total = sum(int(v or 0) for v in outcome.values())
        if step_up and total:
            return f"Step-up triggered {round(step_up / total * 100)}%"
    if isinstance(action, dict):
        sent = int(action.get("sent", 0) or 0)
        verified = int(action.get("verified", 0) or 0)
        if sent and verified:
            return f"Verified after send {round(verified / sent * 100)}%"
    for dim_key in ("grant_type", "binding_type", "template", "org_type", "event_type", "response_type"):
        bucket = dims.get(dim_key, {})
        if isinstance(bucket, dict) and bucket:
            top_key, top_val = max(bucket.items(), key=lambda item: item[1])
            total = sum(int(v or 0) for v in bucket.values())
            if total:
                return f"{dim_key.replace('_', ' ').title()}: {top_key} ({round(top_val / total * 100)}%)"
    return f"{fmt_int(feature['total_count'])} events"


def load_account_data(api_base: str, customer_id: str) -> dict:
    customers = fetch(api_base, "/customers") or []
    customer = next((item for item in customers if item["id"] == customer_id), None)
    if not customer:
        sys.exit(f"Customer '{customer_id}' not found. Use --list-customers to see valid IDs.")

    portfolio = fetch(api_base, "/reports/customers/portfolio") or []
    portfolio_item = next((item for item in portfolio if item["customer_id"] == customer_id), None)
    rows = fetch(api_base, f"/reports/customers/{customer_id}/features") or []

    latest_prod_rows, previous_prod_rows, latest_prod_to, previous_prod_to = latest_period_rows(rows, is_prod)
    latest_staging_rows, _, latest_staging_to, _ = latest_period_rows(rows, is_staging)

    latest_prod = summarize_snapshot(latest_prod_rows)
    previous_prod = summarize_snapshot(previous_prod_rows)
    latest_staging = summarize_snapshot(latest_staging_rows)

    product_id = "identity-server"
    version = ""
    if latest_prod_rows:
        product_id = latest_prod_rows[0]["product_id"]
        version = latest_prod_rows[0]["version"]
    elif portfolio_item and portfolio_item.get("deployments"):
        version = portfolio_item["deployments"][0]["version"]

    coverage = fetch(api_base, f"/reports/catalog/coverage?product_id={product_id}&version={version}") or []
    catalog = {row["feature_code"]: row for row in coverage}

    return {
        "customer": customer,
        "portfolio": portfolio_item or {},
        "all_rows": rows,
        "latest_prod": latest_prod,
        "previous_prod": previous_prod,
        "latest_staging": latest_staging,
        "latest_prod_to": latest_prod_to,
        "previous_prod_to": previous_prod_to,
        "latest_staging_to": latest_staging_to,
        "catalog": catalog,
        "coverage": coverage,
        "product_id": product_id,
        "version": version,
    }


def build_model(data: dict) -> dict:
    latest_prod = data["latest_prod"]
    previous_prod = data["previous_prod"]
    latest_staging = data["latest_staging"]
    catalog = data["catalog"]
    coverage = data["coverage"]

    enabled_codes = set(latest_prod.keys())
    active_codes = {code for code, feature in latest_prod.items() if feature["total_count"] > 0}
    previous_active_codes = {code for code, feature in previous_prod.items() if feature["total_count"] > 0}

    max_total = max((feature["total_count"] for feature in latest_prod.values()), default=0)

    matrix_rows = []
    for row in coverage:
        code = row["feature_code"]
        feature = latest_prod.get(code)
        enabled = code in enabled_codes
        active = code in active_codes
        total_count = feature["total_count"] if feature else 0
        band = usage_band(total_count, max_total)
        status = matrix_status(enabled, active, row.get("status", "stable"), band)
        matrix_rows.append({
            "feature_code": code,
            "feature_name": row["feature_name"],
            "category": row["category"],
            "tier": row["tier"],
            "catalog_status": row["status"],
            "enabled": enabled,
            "active": active,
            "usage_band": band,
            "total_count": total_count,
            "status": status,
        })
    matrix_rows.sort(key=lambda row: (row["category"], 0 if row["enabled"] else 1, -row["total_count"], row["feature_name"]))

    enabled_but_unused = [
        row for row in matrix_rows
        if row["enabled"] and not row["active"]
    ]
    staging_active_not_prod = []
    for code, feature in latest_staging.items():
        if feature["total_count"] > 0 and code not in active_codes:
            staging_active_not_prod.append({
                "feature_code": code,
                "feature_name": feature["name"],
                "category": feature["category"],
                "staging_events": feature["total_count"],
            })
    staging_active_not_prod.sort(key=lambda row: (-row["staging_events"], row["feature_name"]))

    deprecated_or_beta = [
        row for row in matrix_rows
        if row["active"] and row["catalog_status"] in ("deprecated", "beta")
    ]

    failure_issues = []
    for code, feature in latest_prod.items():
        success, failure, observed = failure_summary(feature)
        if observed >= 50 and failure > 0:
            failure_pct = round(failure / observed * 100)
            if failure_pct >= 5:
                failure_issues.append({
                    "feature_code": code,
                    "feature_name": feature["name"],
                    "category": feature["category"],
                    "failure_pct": failure_pct,
                    "failure_count": failure,
                })
    failure_issues.sort(key=lambda row: (-row["failure_pct"], -row["failure_count"]))

    top_features = sorted(
        [feature for feature in latest_prod.values() if feature["total_count"] > 0],
        key=lambda feature: (-feature["total_count"], feature["name"])
    )[:12]
    usage_details = [
        {
            "feature_name": feature["name"],
            "feature_code": feature["code"],
            "category": feature["category"],
            "total_count": feature["total_count"],
            "metric": usage_metric(feature),
        }
        for feature in top_features
    ]

    current_total = sum(feature["total_count"] for feature in latest_prod.values())
    previous_total = sum(feature["total_count"] for feature in previous_prod.values())
    total_change_pct = round((current_total - previous_total) / previous_total * 100) if previous_total else None
    category_current = category_totals(latest_prod)
    category_previous = category_totals(previous_prod)
    enabled_active_ratio = round(len(active_codes) / len(enabled_codes) * 100) if enabled_codes else 0
    category_usage = sorted(category_current.items(), key=lambda item: (-item[1], item[0]))
    top_category, top_category_total = category_usage[0] if category_usage else ("—", 0)
    top_category_share = round(top_category_total / current_total * 100) if current_total else 0
    total_observed_success = 0
    total_observed_failure = 0
    for feature in latest_prod.values():
        success, failure, observed = failure_summary(feature)
        if observed:
            total_observed_success += success
            total_observed_failure += failure
    observed_total = total_observed_success + total_observed_failure
    failure_rate = round(total_observed_failure / observed_total * 100) if observed_total else None
    activation_gap = len(coverage) - len(enabled_codes)

    security_indicators = [
        {
            "indicator": "Enabled capabilities with real traffic",
            "status": (
                "Strong" if enabled_active_ratio >= 80 else
                "Moderate" if enabled_active_ratio >= 55 else
                "Low"
            ),
            "detail": f"{enabled_active_ratio}% of enabled production features generated non-zero traffic in the latest reporting window.",
        },
        {
            "indicator": "Observed failure rate",
            "status": (
                "Stable" if failure_rate is not None and failure_rate < 5 else
                "Watch" if failure_rate is not None and failure_rate < 12 else
                "No signal" if failure_rate is None else
                "Elevated"
            ),
            "detail": (
                f"{failure_rate}% of tracked success/failure outcomes ended in failure."
                if failure_rate is not None else
                "The current feature dimensions do not expose enough success/failure data to estimate a failure rate."
            ),
        },
        {
            "indicator": "Traffic concentration",
            "status": (
                "Balanced" if top_category_share < 50 else
                "Concentrated" if top_category_share < 75 else
                "Highly concentrated"
            ),
            "detail": (
                f"{top_category_share}% of current production traffic comes from {top_category}."
                if top_category_total > 0 else
                "No active production traffic was reported in the latest window."
            ),
        },
        {
            "indicator": "Environment drift",
            "status": "Review" if staging_active_not_prod else "Clear",
            "detail": (
                f"{len(staging_active_not_prod)} feature(s) show activity in staging but not in production."
                if staging_active_not_prod else
                "No active staging-only feature drift was detected."
            ),
        },
        {
            "indicator": "Lifecycle risk in production",
            "status": "Review" if deprecated_or_beta else "Clear",
            "detail": (
                f"{len(deprecated_or_beta)} production feature(s) are beta or deprecated."
                if deprecated_or_beta else
                "No beta or deprecated features are active in production."
            ),
        },
        {
            "indicator": "Version alignment gap",
            "status": (
                "Wide" if activation_gap >= 20 else
                "Moderate" if activation_gap >= 8 else
                "Tight"
            ),
            "detail": f"{activation_gap} catalog feature(s) available in this version are not currently enabled in the live environment.",
        },
    ]

    unused_items = []
    for row in enabled_but_unused[:20]:
        zero_periods = sum(
            1
            for item in data["all_rows"]
            if item["feature_code"] == row["feature_code"] and is_prod(item.get("environment")) and int(item.get("total_count") or 0) == 0
        )
        unused_items.append({
            "item": row["feature_name"],
            "category": row["category"],
            "status": f"Enabled, 0 events across {zero_periods} prod period(s)",
        })
    for row in staging_active_not_prod[:10]:
        unused_items.append({
            "item": row["feature_name"],
            "category": row["category"],
            "status": f"Active in staging only ({fmt_int(row['staging_events'])} events)",
        })

    recommendations = []
    if enabled_active_ratio < 55:
        recommendations.append({
            "priority": "High",
            "recommendation": "Reduce the gap between configured capabilities and real usage",
            "reason": f"Only {enabled_active_ratio}% of enabled production features generated real traffic in the latest reporting window.",
        })
    if failure_issues:
        issue = failure_issues[0]
        recommendations.append({
            "priority": "High",
            "recommendation": f"Investigate failure-heavy flow for {issue['feature_name']}",
            "reason": f"{issue['failure_pct']}% of the observed success/failure events for this feature ended in failure.",
        })
    if enabled_but_unused:
        recommendations.append({
            "priority": "Medium",
            "recommendation": "Clean up or complete rollout of enabled-but-unused features",
            "reason": f"{len(enabled_but_unused)} feature(s) are configured in production but produced no usage in the latest reporting window.",
        })
    if staging_active_not_prod:
        recommendations.append({
            "priority": "Medium",
            "recommendation": "Promote validated staging features into production",
            "reason": f"{len(staging_active_not_prod)} feature(s) show live activity in staging but not in production.",
        })
    if top_category_share >= 75 and top_category_total > 0:
        recommendations.append({
            "priority": "Low",
            "recommendation": "Review traffic concentration around a single capability family",
            "reason": f"{top_category_share}% of current production traffic is concentrated in {top_category}, which may hide underused capabilities elsewhere.",
        })
    if activation_gap >= 12:
        recommendations.append({
            "priority": "Low",
            "recommendation": "Review unused capabilities already available in the current version",
            "reason": f"{activation_gap} catalog features are available in v{data['version'] or 'current'} but not enabled for this account.",
        })
    if deprecated_or_beta:
        recommendations.append({
            "priority": "Medium",
            "recommendation": "Review beta or deprecated capabilities before they become production dependencies",
            "reason": f"{len(deprecated_or_beta)} active feature(s) need lifecycle review.",
        })

    if not recommendations:
        recommendations.append({
            "priority": "Low",
            "recommendation": "No urgent technical actions detected",
            "reason": "The latest production snapshot does not show major security, usage, or redundancy signals.",
        })

    tier_order = {"enterprise": 0, "premium": 1, "core": 2}
    category_meta: dict[str, dict] = {}
    for row in matrix_rows:
        entry = category_meta.setdefault(row["category"], {
            "category": row["category"],
            "available": 0,
            "enabled": 0,
            "active": 0,
            "current_total": 0,
            "previous_total": 0,
        })
        entry["available"] += 1
        if row["enabled"]:
            entry["enabled"] += 1
        if row["active"]:
            entry["active"] += 1
            entry["current_total"] += row["total_count"]

    for category, total in category_previous.items():
        category_meta.setdefault(category, {
            "category": category,
            "available": 0,
            "enabled": 0,
            "active": 0,
            "current_total": 0,
            "previous_total": 0,
        })["previous_total"] = total

    category_rows = []
    for category, row in category_meta.items():
        coverage_pct = round(row["active"] / row["available"] * 100) if row["available"] else 0
        enabled_pct = round(row["enabled"] / row["available"] * 100) if row["available"] else 0
        change_pct = round((row["current_total"] - row["previous_total"]) / row["previous_total"] * 100) if row["previous_total"] else None
        category_rows.append({
            "category": category,
            "available": row["available"],
            "enabled": row["enabled"],
            "active": row["active"],
            "enabled_pct": enabled_pct,
            "coverage_pct": coverage_pct,
            "current_total": row["current_total"],
            "change_pct": change_pct,
        })
    category_rows.sort(key=lambda row: (row["coverage_pct"], -row["current_total"], row["category"]))

    alignment_rows = []
    for row in matrix_rows:
        if not row["enabled"]:
            alignment_rows.append({
                "feature_name": row["feature_name"],
                "feature_code": row["feature_code"],
                "category": row["category"],
                "tier": row["tier"],
                "available": "Yes",
                "enabled": "No",
                "used": "No",
                "note": "Available in this version but not enabled",
            })
    alignment_rows.sort(key=lambda row: (tier_order.get((row["tier"] or "").lower(), 3), row["category"], row["feature_name"]))

    summary_cards = {
        "available": len(coverage),
        "enabled": len(enabled_codes),
        "active": len(active_codes),
        "unused": len(enabled_but_unused),
        "current_total": current_total,
        "change_pct": total_change_pct,
        "recommendations": len(recommendations),
    }

    return {
        "matrix_rows": matrix_rows,
        "enabled_but_unused": enabled_but_unused,
        "staging_active_not_prod": staging_active_not_prod,
        "failure_issues": failure_issues,
        "usage_details": usage_details,
        "category_rows": category_rows,
        "security_indicators": security_indicators,
        "unused_items": unused_items,
        "recommendations": recommendations,
        "alignment_rows": alignment_rows[:18],
        "summary_cards": summary_cards,
        "deprecated_or_beta": deprecated_or_beta,
        "enabled_active_ratio": enabled_active_ratio,
        "failure_rate": failure_rate,
        "top_category_share": top_category_share,
        "top_category": top_category,
        "activation_gap": activation_gap,
        "current_total": current_total,
        "previous_total": previous_total,
        "current_categories": category_current,
        "previous_categories": category_previous,
        "previous_active_codes": previous_active_codes,
    }


CSS = """
  :root {
    --bg: #eef3f7;
    --surface: #ffffff;
    --ink: #12263a;
    --muted: #5d7187;
    --line: #dbe4ee;
    --accent: #165dff;
    --good-bg: #e7f8ee;
    --good-ink: #166534;
    --warn-bg: #fff4dd;
    --warn-ink: #b45309;
    --bad-bg: #fde8e8;
    --bad-ink: #b91c1c;
    --info-bg: #e8f1ff;
    --info-ink: #1d4ed8;
    --muted-bg: #eef2f7;
    --muted-ink: #607286;
  }
  body { margin: 0; background: var(--bg); color: var(--ink); font-family: "Segoe UI", system-ui, sans-serif; }
  .hero { background: linear-gradient(135deg, #12334a, #1f5c73); color: white; padding: 2.4rem 0 2rem; }
  .container { width: min(1420px, calc(100vw - 48px)); margin: 0 auto; }
  .eyebrow { display: inline-block; padding: .35rem .65rem; border-radius: 999px; background: rgba(255,255,255,.14); font-size: .78rem; letter-spacing: .06em; text-transform: uppercase; }
  .hero h1 { margin: .8rem 0 .4rem; font-size: 2rem; }
  .subtitle { color: rgba(255,255,255,.78); }
  .grid { display: grid; gap: 16px; }
  .cards { grid-template-columns: repeat(6, minmax(0, 1fr)); margin: 24px 0; }
  .card, .section { background: var(--surface); border-radius: 16px; box-shadow: 0 10px 28px rgba(18, 38, 58, .06); }
  .card { padding: 1.15rem 1.2rem; }
  .card .value { font-size: 2rem; font-weight: 700; }
  .card .label { margin-top: .35rem; color: var(--muted); text-transform: uppercase; font-size: .78rem; letter-spacing: .06em; }
  .card .sub { margin-top: .4rem; color: var(--muted); }
  .section { margin-bottom: 18px; overflow: hidden; }
  .section-head { padding: 1rem 1.2rem; border-bottom: 1px solid var(--line); font-weight: 700; font-size: 1rem; }
  .section-body { padding: 1.2rem; }
  .explain { color: var(--muted); line-height: 1.55; margin-bottom: 1rem; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: .72rem .75rem; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { text-align: left; font-size: .76rem; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; background: #f8fbfd; }
  tr:last-child td { border-bottom: none; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem; color: #335; }
  .pill { display: inline-block; padding: .22rem .5rem; border-radius: 999px; font-size: .75rem; font-weight: 600; }
  .good { background: var(--good-bg); color: var(--good-ink); }
  .warn { background: var(--warn-bg); color: var(--warn-ink); }
  .bad { background: var(--bad-bg); color: var(--bad-ink); }
  .info { background: var(--info-bg); color: var(--info-ink); }
  .muted { background: var(--muted-bg); color: var(--muted-ink); }
  .soft-grid { display: grid; grid-template-columns: 1.2fr .8fr; gap: 16px; }
  .issue { border-left: 4px solid #f59e0b; background: #fffaf0; border-radius: 10px; padding: .9rem 1rem; margin-bottom: .8rem; }
  .issue.bad { border-left-color: #ef4444; background: #fff4f4; }
  .issue.info { border-left-color: #3b82f6; background: #f7fbff; }
  .issue strong { display: block; margin-bottom: .25rem; }
  .split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .mini { color: var(--muted); font-size: .88rem; }
  .chart-wrap { height: 300px; }
  .footer { color: var(--muted); text-align: center; padding: 1.5rem 0 2rem; font-size: .84rem; }
  .stack > * + * { margin-top: .7rem; }
  @media (max-width: 1200px) {
    .cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .soft-grid, .split { grid-template-columns: 1fr; }
  }
  @media (max-width: 760px) {
    .container { width: min(100vw - 24px, 1420px); }
    .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .hero h1 { font-size: 1.6rem; }
  }
"""


def render_summary(data: dict, model: dict) -> str:
    cards = model["summary_cards"]
    change_text = fmt_pct(cards["change_pct"]) if cards["change_pct"] is not None else "—"
    return f"""
<div class="grid cards">
  <div class="card">
    <div class="value" style="color:#165dff">{cards['enabled']}</div>
    <div class="label">Enabled Features</div>
    <div class="sub">listed in latest production report</div>
  </div>
  <div class="card">
    <div class="value" style="color:#0f9d58">{cards['active']}</div>
    <div class="label">Actively Used</div>
    <div class="sub">features with non-zero production traffic</div>
  </div>
  <div class="card">
    <div class="value" style="color:#b45309">{cards['unused']}</div>
    <div class="label">Configured / Unused</div>
    <div class="sub">enabled but zero events in latest production period</div>
  </div>
  <div class="card">
    <div class="value" style="color:#7c3aed">{fmt_int(cards['current_total'])}</div>
    <div class="label">Production Events</div>
    <div class="sub">latest reporting window total</div>
  </div>
  <div class="card">
    <div class="value" style="color:#2563eb">{change_text}</div>
    <div class="label">Period Change</div>
    <div class="sub">vs previous production reporting window</div>
  </div>
  <div class="card">
    <div class="value" style="color:#dc2626">{cards['recommendations']}</div>
    <div class="label">Action Items</div>
    <div class="sub">prioritized technical follow-ups</div>
  </div>
</div>
"""


def render_matrix(model: dict) -> str:
    rows = []
    current_category = None
    for row in model["matrix_rows"]:
        if row["category"] != current_category:
            current_category = row["category"]
            rows.append(
                f'<tr><td colspan="7" style="background:#f8fbfd;font-weight:700;color:#506275">{current_category}</td></tr>'
            )
        enabled = "Yes" if row["enabled"] else "No"
        active = "Yes" if row["active"] else "No"
        cls = status_class(row["status"])
        catalog_state = row["catalog_status"].title()
        rows.append(f"""
        <tr>
          <td>
            <div><strong>{row['feature_name']}</strong></div>
            <div class="mono">{row['feature_code']}</div>
          </td>
          <td>{enabled}</td>
          <td>{active}</td>
          <td>{row['usage_band']}</td>
          <td>{fmt_int(row['total_count']) if row['active'] else '—'}</td>
          <td><span class="pill {cls}">{row['status']}</span></td>
          <td><span class="pill muted">{catalog_state}</span></td>
        </tr>
        """)
    return f"""
<section class="section">
  <div class="section-head">1. Feature Status Matrix</div>
  <div class="section-body">
    <div class="explain">
      This is the core technical view of the account. A feature counts as <strong>Enabled</strong> when it appears in the latest production utilization report for this customer. It counts as <strong>Actively used</strong> when that same production snapshot reports more than zero events. The <strong>Usage</strong> band compares active features inside this account only: the busiest features appear as High, the middle layer as Medium, and the long tail as Low.
    </div>
    <table>
      <thead>
        <tr>
          <th>Feature</th>
          <th>Enabled</th>
          <th>Actively Used</th>
          <th>Usage</th>
          <th>Events</th>
          <th>Status</th>
          <th>Catalog State</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>
"""


def render_gaps(model: dict) -> str:
    issues = []
    for row in model["enabled_but_unused"][:8]:
        issues.append(f"""
        <div class="issue">
          <strong>{row['feature_name']}</strong>
          Enabled in production but produced no events in the latest reporting window. This usually means incomplete rollout, dormant configuration, or a capability users are not reaching.
        </div>
        """)
    for row in model["staging_active_not_prod"][:5]:
        issues.append(f"""
        <div class="issue info">
          <strong>{row['feature_name']}</strong>
          Active in staging with {fmt_int(row['staging_events'])} events, but not active in production. This suggests a rollout stuck between testing and go-live.
        </div>
        """)
    for row in model["failure_issues"][:5]:
        issues.append(f"""
        <div class="issue bad">
          <strong>{row['feature_name']}</strong>
          {row['failure_pct']}% of observed success/failure outcomes were failures. This is a technical health signal worth investigating before users feel it more broadly.
        </div>
        """)
    for row in model["deprecated_or_beta"][:4]:
        issues.append(f"""
        <div class="issue bad">
          <strong>{row['feature_name']}</strong>
          Active in production while the catalog marks it as {row['catalog_status']}. Treat this as a lifecycle review item.
        </div>
        """)
    if not issues:
        issues.append('<div class="issue info"><strong>No major misconfiguration signal detected</strong>The latest production and staging snapshots do not show obvious redundant or failure-heavy configurations.</div>')
    return f"""
<section class="section">
  <div class="section-head">2. Configuration Gaps / Misconfigurations</div>
  <div class="section-body">
    <div class="explain">
      This section highlights technical patterns that usually deserve follow-up: features configured but unused, capabilities active only in staging, production paths with high failure rates, and lifecycle risks such as beta or deprecated features running live.
    </div>
    <div class="stack">{''.join(issues)}</div>
  </div>
</section>
"""


def render_usage_detail(model: dict) -> str:
    rows = []
    for item in model["usage_details"]:
        rows.append(f"""
        <tr>
          <td>
            <div><strong>{item['feature_name']}</strong></div>
            <div class="mono">{item['feature_code']}</div>
          </td>
          <td>{item['category']}</td>
          <td>{fmt_int(item['total_count'])}</td>
          <td>{item['metric']}</td>
        </tr>
        """)
    return f"""
<section class="section">
  <div class="section-head">3. Feature Usage Detail</div>
  <div class="section-body">
    <div class="explain">
      This drill-down focuses on the busiest production features in the latest reporting window. The metric column interprets each feature’s dimension breakdown where possible, for example success rate, dominant action, leading template, or the most common event type.
    </div>
    <table>
      <thead>
        <tr>
          <th>Feature</th>
          <th>Category</th>
          <th>Events</th>
          <th>Key Metric</th>
        </tr>
      </thead>
      <tbody>{''.join(rows) or '<tr><td colspan="4">No active production usage was reported.</td></tr>'}</tbody>
    </table>
  </div>
</section>
"""


def render_category_health(model: dict) -> str:
    rows = []
    for row in model["category_rows"][:12]:
        if row["coverage_pct"] >= 70:
            cls = "good"
            state = "Strong"
        elif row["coverage_pct"] >= 35:
            cls = "warn"
            state = "Partial"
        else:
            cls = "bad"
            state = "Weak"
        change = fmt_pct(row["change_pct"]) if row["change_pct"] is not None else "—"
        rows.append(f"""
        <tr>
          <td>{row['category']}</td>
          <td>{row['active']} / {row['available']}</td>
          <td>{row['enabled_pct']}%</td>
          <td>{row['coverage_pct']}%</td>
          <td>{change}</td>
          <td><span class="pill {cls}">{state}</span></td>
        </tr>
        """)
    return f"""
<section class="section">
  <div class="section-head">4. Capability / Category Health</div>
  <div class="section-body">
    <div class="explain">
      This section shows how each capability area is doing as a whole. <strong>Enabled %</strong> is the share of features in that category that are configured in the latest production snapshot. <strong>Active %</strong> is the share that actually generated traffic. <strong>Change</strong> compares current category traffic with the previous production period when history exists.
    </div>
    <table>
      <thead>
        <tr>
          <th>Category</th>
          <th>Active Features</th>
          <th>Enabled %</th>
          <th>Active %</th>
          <th>Change</th>
          <th>Health</th>
        </tr>
      </thead>
      <tbody>{''.join(rows) or '<tr><td colspan="6">No category-level production health data is available.</td></tr>'}</tbody>
    </table>
  </div>
</section>
"""


def render_security(model: dict) -> str:
    rows = []
    for row in model["security_indicators"]:
        cls = (
            "good" if row["status"] in ("Strong", "Stable", "Balanced", "Clear", "Tight") else
            "warn" if row["status"] in ("Moderate", "Watch", "Concentrated", "Review", "Moderate") else
            "bad" if row["status"] in ("Low", "Elevated", "Highly concentrated", "Wide") else
            "muted"
        )
        rows.append(f"""
        <tr>
          <td>{row['indicator']}</td>
          <td><span class="pill {cls}">{row['status']}</span></td>
          <td>{row['detail']}</td>
        </tr>
        """)
    return f"""
<section class="section">
  <div class="section-head">5. Technical Posture Indicators</div>
  <div class="section-body">
    <div class="explain">
      These are lightweight technical posture signals rather than deep product-specific audits. They focus on whether enabled capabilities are actually active, whether observed outcomes show elevated failure, whether traffic is concentrated in only one area, whether staging and production have drifted apart, and whether the live environment is lagging behind what the current version already makes available.
    </div>
    <table>
      <thead>
        <tr>
          <th>Indicator</th>
          <th>Status</th>
          <th>Interpretation</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>
"""


def render_unused(model: dict) -> str:
    rows = []
    for row in model["unused_items"]:
        rows.append(f"""
        <tr>
          <td>{row['item']}</td>
          <td>{row['category']}</td>
          <td>{row['status']}</td>
        </tr>
        """)
    return f"""
<section class="section">
  <div class="section-head">6. Unused / Redundant Configurations</div>
  <div class="section-body">
    <div class="explain">
      This section is about cleanup. It isolates technical clutter already present in the environment: features that exist in production but show no usage, plus features that appear to be active only in staging. These are good cleanup candidates because they add mental overhead without delivering runtime value.
    </div>
    <table>
      <thead>
        <tr>
          <th>Item</th>
          <th>Category</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>{''.join(rows) or '<tr><td colspan="3">No obvious redundant configurations were detected.</td></tr>'}</tbody>
    </table>
  </div>
</section>
"""


def render_recommendations(model: dict) -> str:
    rows = []
    priority_order = {"High": 0, "Medium": 1, "Low": 2}
    for row in sorted(model["recommendations"], key=lambda item: priority_order.get(item["priority"], 9)):
        cls = "bad" if row["priority"] == "High" else "warn" if row["priority"] == "Medium" else "info"
        rows.append(f"""
        <tr>
          <td><span class="pill {cls}">{row['priority']}</span></td>
          <td>{row['recommendation']}</td>
          <td>{row['reason']}</td>
        </tr>
        """)
    return f"""
<section class="section">
  <div class="section-head">7. Optimization Recommendations</div>
  <div class="section-body">
    <div class="explain">
      This is the execution list for the technical owner. The priorities come from the latest production snapshot first, then staging and feature-alignment context. High means a security or reliability concern is visible now. Medium usually means cleanup or rollout friction. Low points to modernization or value-expansion opportunities.
    </div>
    <table>
      <thead>
        <tr>
          <th>Priority</th>
          <th>Recommendation</th>
          <th>Why It Matters</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>
"""


def render_alignment(data: dict, model: dict) -> str:
    rows = []
    for row in model["alignment_rows"]:
        rows.append(f"""
        <tr>
          <td>
            <div><strong>{row['feature_name']}</strong></div>
            <div class="mono">{row['feature_code']}</div>
          </td>
          <td>{row['category']}</td>
          <td>{row['tier']}</td>
          <td>{row['available']}</td>
          <td>{row['enabled']}</td>
          <td>{row['used']}</td>
          <td>{row['note']}</td>
        </tr>
        """)
    return f"""
<section class="section">
  <div class="section-head">8. Version &amp; Feature Alignment</div>
  <div class="section-body">
    <div class="explain">
      This section is about adoption opportunity, not cleanup. It compares the customer’s live environment with the features available in version <strong>{data['version'] or '—'}</strong> and highlights capabilities that the account could adopt immediately without upgrading.
    </div>
    <table>
      <thead>
        <tr>
          <th>Feature</th>
          <th>Category</th>
          <th>Tier</th>
          <th>Available</th>
          <th>Enabled</th>
          <th>Used</th>
          <th>Interpretation</th>
        </tr>
      </thead>
      <tbody>{''.join(rows) or '<tr><td colspan="7">No immediate feature-alignment opportunities were identified for the current version.</td></tr>'}</tbody>
    </table>
  </div>
</section>
"""


def build_html(api_base: str, customer_id: str) -> str:
    data = load_account_data(api_base, customer_id)
    model = build_model(data)

    customer = data["customer"]
    portfolio = data["portfolio"]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    latest_report = data["latest_prod_to"] or portfolio.get("last_report_to") or "—"
    prev_report = data["previous_prod_to"] or "—"
    envs = ", ".join(sorted({deployment["environment"] for deployment in portfolio.get("deployments", [])})) or "—"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Technical Owner Dashboard — {customer['name']}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>{CSS}</style>
</head>
<body>
  <header class="hero">
    <div class="container">
      <span class="eyebrow">Technical Owner Dashboard</span>
      <h1>{customer['name']}</h1>
      <div class="subtitle">
        Customer ID: <strong>{customer['id']}</strong> · Region: <strong>{customer.get('region') or '—'}</strong> · Tier: <strong>{customer.get('tier') or '—'}</strong> · Version: <strong>{data['version'] or '—'}</strong>
      </div>
      <div class="subtitle" style="margin-top:.45rem">
        Environments: <strong>{envs}</strong> · Latest prod report: <strong>{latest_report}</strong> · Previous prod report: <strong>{prev_report}</strong> · Generated {generated_at}
      </div>
    </div>
  </header>

  <main class="container">
    {render_summary(data, model)}
    {render_matrix(model)}
    {render_gaps(model)}
    <div class="split">
      {render_usage_detail(model)}
      {render_category_health(model)}
    </div>
    {render_security(model)}
    {render_unused(model)}
    {render_recommendations(model)}
    {render_alignment(data, model)}
  </main>

  <div class="footer">
    WSO2 Feature Utilization — Technical Owner Dashboard · {customer['name']} · Generated {generated_at}
  </div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate WSO2 Technical Owner HTML report (per account)"
    )
    parser.add_argument("--api", default="http://127.0.0.1:8001", help="API base URL")
    parser.add_argument("--customer", help="Customer ID to generate the technical owner report for")
    parser.add_argument("--customers", nargs="+", default=None, help="Deprecated alias for --customer; only the first customer will be used")
    parser.add_argument("--out", default=None, help="Output HTML path")
    parser.add_argument("--list-customers", action="store_true", help="List customers and exit")
    args = parser.parse_args()

    if args.list_customers:
        customers = fetch(args.api, "/customers") or []
        if not customers:
            print("No customers found.")
            return
        print(f"\n{'ID':<24} {'Name':<34} {'Region':<16} Tier")
        print("─" * 88)
        for customer in customers:
            print(f"{customer['id']:<24} {customer['name']:<34} {(customer.get('region') or '—'):<16} {customer.get('tier') or '—'}")
        return

    customer_id = args.customer
    if not customer_id and args.customers:
        expanded = []
        for token in args.customers:
            expanded.extend(item.strip() for item in token.split(",") if item.strip())
        customer_id = expanded[0] if expanded else None

    if not customer_id:
        parser.error("--customer is required (or use --list-customers)")

    html = build_html(args.api, customer_id)
    outfile = args.out or f"reports/technical_owner_{customer_id.replace('-', '_')}.html"
    Path(outfile).write_text(html, encoding="utf-8")
    print(f"\nReport saved → {Path(outfile).resolve()}")


if __name__ == "__main__":
    main()
