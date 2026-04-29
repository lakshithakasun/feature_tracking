#!/usr/bin/env python3
"""
WSO2 Feature Utilization — Product Development Team Report (View 3)

Sections:
  Scorecard     — headline KPIs + category bar chart
  A. Feature Adoption Ranking    — top features by usage + tier-weighted breadth
  B. Feature × Customer Heatmap  — per-row heat scaling, adoption summary columns
  C. Dimension Breakdown         — HOW each feature is used, failure rates highlighted
  D. Staging → Prod Pipeline     — features tested in staging, not yet live in prod
  E. Zero-Adoption Features      — unused features + months since introduced
  F. Version Comparison          — cross-version feature coverage
  G. Deprecation Decision Panel  — 🟢 safe · 🟡 migrate first · 🔴 do not touch
  H. Security Advisory           — JS dropdown: pick feature → see affected customers
  I. New Features Adoption       — features introduced in current version, adoption callout

Usage:
    python3 scripts/10_report_product_team.py
    python3 scripts/10_report_product_team.py --product identity-server --version 7.2.0
    python3 scripts/10_report_product_team.py --out report_product_team.html
    python3 scripts/10_report_product_team.py --api http://127.0.0.1:8001
"""

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

PALETTE = [
    "#4F86C6", "#E07B54", "#5AB08E", "#A06EC9",
    "#E8B84B", "#4BC0C0", "#E66A9A", "#7B9E3C",
    "#C76B6B", "#6B8EC7", "#D4A050", "#8E6BC7",
]

TIER_BADGE = {
    "enterprise": "bg-danger",
    "premium":    "bg-warning text-dark",
    "core":       "bg-secondary",
}
TIER_ORDER   = {"enterprise": 0, "premium": 1, "core": 2}
TIER_WEIGHTS = {"enterprise": 3, "premium": 2, "core": 1}

FAILURE_KEYS = {"verify-failed", "auth-failed", "failed", "login-failed",
                "expired", "denied", "access-denied"}

# Maps product version → approximate release month (for "months since introduced")
VERSION_RELEASE_DATES: dict[str, datetime] = {
    "7.2.0": datetime(2025, 9, 1),
    "7.3.0": datetime(2026, 1, 1),
}


def fetch(api_base: str, path: str):
    url = f"{api_base}{path}"
    try:
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
        return None


def color(i: int) -> str:
    return PALETTE[i % len(PALETTE)]


def tier_badge(tier: str) -> str:
    cls = TIER_BADGE.get((tier or "").lower(), "bg-light text-dark border")
    return f'<span class="badge {cls}">{tier or "—"}</span>'


def heat_color_row(count: int, row_max: int) -> tuple[str, str]:
    """
    Return (bg_color, text_color) scaled to count / row_max for this feature's row.
    Uses a per-row max so every active feature gets meaningful color variation.
    """
    if count == 0 or row_max == 0:
        return "#f5f5f5", "#bbb"
    intensity = count / row_max
    # Light green (#e8f5e9) → dark green (#1b5e20)
    r = int(232 - intensity * (232 - 27))
    g = int(245 - intensity * (245 - 94))
    b = int(233 - intensity * (233 - 32))
    txt = "white" if intensity > 0.55 else "#1b5e20"
    return f"#{r:02x}{g:02x}{b:02x}", txt


def fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}k"
    return str(n)


# ── Data loading ──────────────────────────────────────────────────────────────

def load_data(api_base: str, product_id: str, version: str) -> dict:
    print(f"Fetching product team data for {product_id} v{version}...")

    dashboard   = fetch(api_base, f"/reports/dashboard?product_id={product_id}&version={version}")
    summary     = fetch(api_base, f"/reports/features/summary?product_id={product_id}&version={version}") or []
    coverage    = fetch(api_base, f"/reports/catalog/coverage?product_id={product_id}&version={version}") or []
    heatmap     = fetch(api_base, f"/reports/features/heatmap?product_id={product_id}&version={version}") or {}
    dimensions  = fetch(api_base, f"/reports/features/dimensions?product_id={product_id}&version={version}") or []
    by_category = fetch(api_base, f"/reports/features/by-category?product_id={product_id}&version={version}") or []

    if not dashboard:
        sys.exit("Could not reach API. Is the server running?")

    # Staging pipeline: per-customer prod vs staging feature comparison
    print("Fetching customer feature data for staging pipeline...")
    customers_list = fetch(api_base, "/customers") or []
    staging_map: dict[str, dict] = {}   # feature_code → {name, category, customers_testing: set}

    for c in customers_list:
        cid   = c["id"]
        cname = c["name"]
        raw   = fetch(api_base, f"/reports/customers/{cid}/features") or []

        prod_codes    = {f["feature_code"] for f in raw if f.get("environment") == "prod"
                         and f.get("version") == version}
        staging_feats = [f for f in raw if f.get("environment") == "staging"
                         and f.get("version") == version]

        for f in staging_feats:
            code = f["feature_code"]
            if code not in prod_codes:   # tested in staging, not yet in prod
                if code not in staging_map:
                    staging_map[code] = {
                        "name":              f["feature_name"],
                        "category":          f.get("category", ""),
                        "customers_testing": set(),
                        "total_staging":     0,
                    }
                staging_map[code]["customers_testing"].add(cname)
                staging_map[code]["total_staging"] += f["total_count"]

    # ── Tier-weighted breadth ─────────────────────────────────────────────────
    # For each feature: weighted_breadth = sum of TIER_WEIGHTS[customer_tier]
    # for customers that have used the feature (from heatmap matrix).
    customers_from_heatmap = heatmap.get("customers", [])
    customer_tier_map = {c["id"]: (c.get("tier") or "core").lower()
                         for c in customers_from_heatmap}
    # Max possible weighted breadth = sum of all customer weights
    max_weighted = sum(TIER_WEIGHTS.get(t, 1) for t in customer_tier_map.values()) or 1

    # Build feature_code → weighted_breadth
    feature_weighted: dict[str, int] = defaultdict(int)
    for row in heatmap.get("matrix", []):
        if row.get("total_count", 0) > 0:
            t = customer_tier_map.get(row["customer_id"], "core")
            feature_weighted[row["feature_code"]] += TIER_WEIGHTS.get(t, 1)

    # ── Security advisory data ─────────────────────────────────────────────────
    # feature_code → list of {customer_name, customer_tier, total_count}
    security_advisory: dict[str, list] = defaultdict(list)
    customer_name_map = {c["id"]: c["name"] for c in customers_from_heatmap}
    for row in heatmap.get("matrix", []):
        if row.get("total_count", 0) > 0:
            cid = row["customer_id"]
            security_advisory[row["feature_code"]].append({
                "customer_name": customer_name_map.get(cid, cid),
                "customer_tier": customer_tier_map.get(cid, "core"),
                "total_count": row["total_count"],
            })

    return {
        "dashboard":        dashboard,
        "summary":          summary,
        "coverage":         coverage,
        "heatmap":          heatmap,
        "dimensions":       dimensions,
        "by_category":      by_category,
        "staging_map":      staging_map,
        "total_customers":  dashboard.get("total_customers", 0),
        "feature_weighted": dict(feature_weighted),
        "max_weighted":     max_weighted,
        "security_advisory": dict(security_advisory),
    }


# ── Scorecard ─────────────────────────────────────────────────────────────────

def section_scorecard(data: dict, product_id: str, version: str) -> str:
    d             = data["dashboard"]
    by_category   = data["by_category"]
    utilized      = d["utilized_features"]
    total_cat     = d["total_catalog_features"]
    unused        = total_cat - utilized
    staging_count = len(data["staging_map"])

    # Category bar chart data
    cat_labels = json.dumps([r["category_name"] for r in by_category])
    cat_data   = json.dumps([r["total_usage"] for r in by_category])
    cat_colors = json.dumps([color(i) for i in range(len(by_category))])

    return f"""
<!-- ── SCORECARD ── -->
<div class="row g-3 mb-4">
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value text-primary">{d['total_customers']}</div>
      <div class="label">Customers</div>
      <div class="sub">{d['total_deployments']} deployments</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#E07B54">{d['total_events']:,}</div>
      <div class="label">Feature Events</div>
      <div class="sub">{d['total_reports']} reports</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#5AB08E">{d['utilization_rate_pct']}%</div>
      <div class="label">Feature Adoption</div>
      <div class="sub">{utilized} of {total_cat} used</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#A06EC9">{unused}</div>
      <div class="label">Zero-Adoption</div>
      <div class="sub">features never used</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value" style="color:#E8B84B">{staging_count}</div>
      <div class="label">Staging Pipeline</div>
      <div class="sub">features not yet in prod</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="stat-card">
      <div class="value text-muted" style="font-size:1.4rem">N/A</div>
      <div class="label">MoM Event Change</div>
      <div class="sub" style="color:#aaa">multi-month data needed</div>
    </div>
  </div>
  <div class="col-12 col-md-6">
    <div class="section-card" style="margin-bottom:0">
      <div class="card-header" style="padding:.7rem 1.2rem">Events by Category</div>
      <div class="card-body" style="padding:.8rem 1.2rem">
        <div style="position:relative;height:160px"><canvas id="catChart"></canvas></div>
      </div>
    </div>
  </div>
</div>
<script>
new Chart(document.getElementById('catChart'), {{
  type: 'bar',
  data: {{ labels: {cat_labels}, datasets: [{{ data: {cat_data}, backgroundColor: {cat_colors}, borderRadius: 4 }}] }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: '#f0f0f0' }}, ticks: {{ font: {{ size: 9 }} }} }},
      y: {{ ticks: {{ font: {{ size: 9 }} }} }}
    }}
  }}
}});
</script>"""


# ── Section A — Feature Adoption Ranking ─────────────────────────────────────

def section_a_adoption_ranking(data: dict) -> str:
    summary         = data["summary"]
    total_customers = data["total_customers"]
    feature_weighted = data["feature_weighted"]
    max_weighted     = data["max_weighted"]

    if not summary:
        return ""

    top = summary[:25]

    # Assign a consistent color per category
    cats = list({f["category"] for f in summary})
    cat_color_map = {c: color(i) for i, c in enumerate(sorted(cats))}

    # Horizontal bar chart — top 20 features by total usage
    chart_top = top[:20]
    chart_labels  = json.dumps([f["feature_name"] for f in chart_top])
    chart_data    = json.dumps([f["total_usage"] for f in chart_top])
    chart_colors  = json.dumps([cat_color_map.get(f["category"], "#999") for f in chart_top])
    chart_height  = max(280, len(chart_top) * 28)

    # Legend
    legend_items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px;font-size:.75rem">'
        f'<span style="width:10px;height:10px;border-radius:2px;background:{cat_color_map[c]};display:inline-block"></span>'
        f'{c}</span>'
        for c in sorted(cats)
    )

    # Table
    rows = ""
    for i, f in enumerate(top, 1):
        breadth  = round(f["customer_count"] / total_customers * 100) if total_customers else 0
        bar_w    = breadth
        bar_col  = "#5AB08E" if breadth >= 60 else ("#E8B84B" if breadth >= 30 else "#E07B54")
        t_badge  = tier_badge(f.get("tier", ""))
        cat_col  = cat_color_map.get(f["category"], "#999")
        cat_pill = (
            f'<span style="background:{cat_col}20;color:{cat_col};border:1px solid {cat_col}40;'
            f'padding:.15rem .45rem;border-radius:10px;font-size:.72rem;white-space:nowrap">'
            f'{f["category"]}</span>'
        )

        # Tier-weighted breadth: score / max_weighted * 100%
        w_score = feature_weighted.get(f["feature_code"], 0)
        w_pct   = round(w_score / max_weighted * 100) if max_weighted else 0
        w_col   = "#5AB08E" if w_pct >= 60 else ("#E8B84B" if w_pct >= 30 else "#E07B54")

        rows += f"""
        <tr>
          <td class="ps-3 text-muted" style="font-size:.8rem;width:28px">{i}</td>
          <td><strong style="font-size:.88rem">{f['feature_name']}</strong>
              <div><code style="font-size:.7rem">{f['feature_code']}</code></div></td>
          <td>{cat_pill}</td>
          <td>{t_badge}</td>
          <td class="text-end fw-semibold">{f['total_usage']:,}</td>
          <td style="min-width:130px">
            <div class="d-flex align-items-center gap-2">
              <div class="progress flex-grow-1" style="height:5px;border-radius:3px">
                <div class="progress-bar" style="width:{bar_w}%;background:{bar_col};border-radius:3px"></div>
              </div>
              <span style="font-size:.75rem;white-space:nowrap">{f['customer_count']}/{total_customers}</span>
            </div>
          </td>
          <td style="min-width:110px">
            <div class="d-flex align-items-center gap-2">
              <div class="progress flex-grow-1" style="height:5px;border-radius:3px">
                <div class="progress-bar" style="width:{w_pct}%;background:{w_col};border-radius:3px"></div>
              </div>
              <span style="font-size:.75rem;white-space:nowrap" title="enterprise×3, premium×2, core×1">{w_score}/{max_weighted}</span>
            </div>
          </td>
        </tr>"""

    return f"""
<!-- ── A. FEATURE ADOPTION RANKING ── -->
<div class="section-card mb-4">
  <div class="card-header">
    📊 Section A — Feature Adoption Ranking
    <span class="text-muted fw-normal" style="font-size:.82rem"> — top 20 features by event volume</span>
  </div>
  <div class="card-body">
    <div class="mb-2">{legend_items}</div>
    <div style="position:relative;height:{chart_height}px">
      <canvas id="adoptChart"></canvas>
    </div>
  </div>
</div>
<div class="section-card mb-4">
  <div class="card-header">Feature Adoption — Detail Table
    <span class="text-muted fw-normal" style="font-size:.82rem">
     — sorted by event volume · breadth = % of customers · weighted breadth = enterprise×3, premium×2, core×1
    </span>
  </div>
  <div class="card-body p-0">
    <table class="table table-sm table-hover mb-0">
      <thead><tr>
        <th class="ps-3" style="width:28px">#</th>
        <th>Feature</th><th>Category</th><th>Tier</th>
        <th class="text-end">Total Events</th>
        <th>Customer Breadth</th>
        <th title="enterprise×3, premium×2, core×1">Weighted Breadth</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
<script>
new Chart(document.getElementById('adoptChart'), {{
  type: 'bar',
  data: {{ labels: {chart_labels}, datasets: [{{ data: {chart_data}, backgroundColor: {chart_colors}, borderRadius: 3 }}] }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: '#f0f0f0' }}, ticks: {{ font: {{ size: 10 }} }} }},
      y: {{ ticks: {{ font: {{ size: 10 }} }} }}
    }}
  }}
}});
</script>"""


# ── Section B — Feature × Customer Heatmap ────────────────────────────────────

def section_b_heatmap(data: dict) -> str:
    heatmap_data  = data["heatmap"]
    total_customers = data["total_customers"]

    features    = heatmap_data.get("features", [])
    customers   = heatmap_data.get("customers", [])
    matrix_rows = heatmap_data.get("matrix", [])

    if not customers:
        return """
<div class="section-card mb-4">
  <div class="card-header">🔥 Section B — Feature × Customer Heatmap</div>
  <div class="card-body"><p class="text-muted mb-0">No utilization data available yet.</p></div>
</div>"""

    # Build cell_map: feature_code → customer_id → count
    cell_map: dict = defaultdict(dict)
    for row in matrix_rows:
        cell_map[row["feature_code"]][row["customer_id"]] = row["total_count"]

    # Group features by category; only show features with at least one non-zero cell
    feat_by_cat: dict = defaultdict(list)
    for f in features:
        if any(cell_map.get(f["code"], {}).values()):
            feat_by_cat[f["category"]].append(f)

    # Customer column headers (vertical text, short names)
    col_headers = "".join(
        f'<th style="font-size:.65rem;writing-mode:vertical-rl;white-space:nowrap;'
        f'max-width:22px;padding:.4rem .15rem;text-align:left">'
        f'{c["name"][:18]}</th>'
        for c in customers
    )

    rows_html = ""
    for cat_name in sorted(feat_by_cat.keys()):
        rows_html += (
            f'<tr style="background:#f0f4ff">'
            f'<td colspan="{3 + len(customers)}" class="small fw-bold text-primary ps-2 py-1">'
            f'{cat_name}</td></tr>'
        )
        # Sort features within category by total events desc
        cat_feats = sorted(
            feat_by_cat[cat_name],
            key=lambda f: -sum(cell_map.get(f["code"], {}).values()),
        )
        for f in cat_feats:
            row_vals  = cell_map.get(f["code"], {})
            row_max   = max(row_vals.values(), default=1)
            row_total = sum(row_vals.values())
            row_cust  = sum(1 for v in row_vals.values() if v > 0)

            cells = ""
            for c in customers:
                cnt = row_vals.get(c["id"], 0)
                bg, txt = heat_color_row(cnt, row_max)
                display = fmt_count(cnt) if cnt else ""
                title   = f'{c["name"]}: {cnt:,}' if cnt else f'{c["name"]}: no usage'
                cells += (
                    f'<td style="background:{bg};color:{txt};font-size:.7rem;'
                    f'text-align:center;padding:.2rem .25rem;min-width:46px" title="{title}">'
                    f'{display}</td>'
                )

            # Adoption summary columns
            adopt_pct = round(row_cust / len(customers) * 100)
            bar_col   = "#5AB08E" if adopt_pct >= 60 else ("#E8B84B" if adopt_pct >= 30 else "#E07B54")

            rows_html += (
                f'<tr>'
                f'<td class="ps-2" style="white-space:nowrap;min-width:180px;vertical-align:middle">'
                f'<div style="font-size:.72rem"><code>{f["code"]}</code></div>'
                f'<div class="text-muted" style="font-size:.7rem">{f["name"][:42]}</div>'
                f'</td>'
                f'<td style="font-size:.72rem;white-space:nowrap;vertical-align:middle;padding:.2rem .4rem">'
                f'<div class="progress" style="height:4px;width:50px;border-radius:2px">'
                f'<div class="progress-bar" style="width:{adopt_pct}%;background:{bar_col};border-radius:2px"></div>'
                f'</div>'
                f'<span style="color:#666">{row_cust}/{len(customers)}</span>'
                f'</td>'
                f'<td class="text-end" style="font-size:.72rem;vertical-align:middle;padding:.2rem .4rem;white-space:nowrap">'
                f'{fmt_count(row_total)}</td>'
                f'{cells}'
                f'</tr>'
            )

    return f"""
<!-- ── B. HEATMAP ── -->
<div class="section-card mb-4">
  <div class="card-header d-flex align-items-center gap-3 flex-wrap">
    🔥 Section B — Feature × Customer Heatmap
    <span class="heatmap-legend">
      <span style="width:11px;height:11px;background:#e8f5e9;border:1px solid #ccc;display:inline-block;border-radius:2px"></span> low
      <span style="width:11px;height:11px;background:#388e3c;display:inline-block;border-radius:2px;margin-left:4px"></span> high
      <span style="width:11px;height:11px;background:#f5f5f5;border:1px solid #ddd;display:inline-block;border-radius:2px;margin-left:4px"></span> none
    </span>
    <span class="text-muted fw-normal" style="font-size:.78rem">color scale is per-row (each feature scaled independently)</span>
  </div>
  <div class="card-body p-0" style="overflow-x:auto">
    <table class="table table-sm mb-0 heatmap-table">
      <thead><tr>
        <th class="ps-2" style="min-width:180px">Feature</th>
        <th style="min-width:70px;font-size:.72rem">Adoption</th>
        <th class="text-end" style="font-size:.72rem;min-width:52px">Events</th>
        {col_headers}
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</div>"""


# ── Section C — Dimension Breakdown ──────────────────────────────────────────

def section_c_dimensions(data: dict) -> str:
    dimensions  = data["dimensions"]
    summary     = data["summary"]

    dims_with_data = [d for d in dimensions if d.get("dimensions")]
    if not dims_with_data:
        return """
<div class="section-card mb-4">
  <div class="card-header">📐 Section C — Dimension Breakdown</div>
  <div class="card-body"><p class="text-muted mb-0">No dimension data available.</p></div>
</div>"""

    # Sort by total usage (top 15 features only — keeps the section manageable)
    usage_rank = {f["feature_code"]: f["total_usage"] for f in summary}
    dims_sorted = sorted(
        dims_with_data,
        key=lambda d: -usage_rank.get(d["feature_code"], 0),
    )[:15]

    sections_html = ""
    chart_scripts = ""

    for i, feat in enumerate(dims_sorted):
        dim_charts = ""
        for dk, dv in feat["dimensions"].items():
            if not dv:
                continue
            cid = f"dim_{i}_{dk.replace('-', '_').replace(' ', '_').replace('.', '_')}"

            # Split keys into failure vs success
            fail_keys   = [k for k in dv if k in FAILURE_KEYS]
            total_count = sum(dv.values())
            fail_total  = sum(dv[k] for k in fail_keys)
            fail_pct    = round(fail_total / total_count * 100, 1) if total_count else 0
            fail_badge  = (
                f'<span class="badge bg-danger ms-1" style="font-size:.68rem">'
                f'{fail_pct}% failure rate</span>'
                if fail_keys and fail_pct > 0 else ""
            )

            labels  = json.dumps(list(dv.keys()))
            vals    = json.dumps(list(dv.values()))
            bar_colors = json.dumps([
                "#E07B54" if k in FAILURE_KEYS else color(j)
                for j, k in enumerate(dv.keys())
            ])

            dim_charts += f"""
            <div class="col-sm-6 col-md-4 mb-2">
              <div class="dim-chart-box">
                <div class="d-flex align-items-center gap-1 mb-1">
                  <span class="small text-muted fw-semibold">{dk}</span>{fail_badge}
                </div>
                <div style="position:relative;height:120px"><canvas id="{cid}"></canvas></div>
              </div>
            </div>"""

            chart_scripts += f"""
new Chart(document.getElementById('{cid}'), {{
  type: 'bar',
  data: {{ labels: {labels}, datasets: [{{ data: {vals}, backgroundColor: {bar_colors}, borderRadius: 3 }}] }},
  options: {{
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{
      label: ctx => ctx.parsed.y.toLocaleString()
    }} }} }},
    scales: {{
      x: {{ ticks: {{ font: {{ size: 8 }}, maxRotation: 30 }} }},
      y: {{ ticks: {{ font: {{ size: 8 }} }} }}
    }}
  }}
}});"""

        if dim_charts:
            usage = usage_rank.get(feat["feature_code"], 0)
            sections_html += f"""
            <div class="mb-4 pb-3 border-bottom">
              <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
                <code style="font-size:.8rem">{feat['feature_code']}</code>
                <strong style="font-size:.9rem">{feat['feature_name']}</strong>
                <span class="badge bg-light text-dark border">{feat['category']}</span>
                <span class="text-muted" style="font-size:.8rem">{usage:,} events</span>
              </div>
              <div class="row g-2">{dim_charts}</div>
            </div>"""

    return f"""
<!-- ── C. DIMENSION BREAKDOWN ── -->
<div class="section-card mb-4">
  <div class="card-header">
    📐 Section C — Dimension Breakdown
    <span class="text-muted fw-normal" style="font-size:.82rem">
     — HOW each feature is used · top 15 by volume · failure bars shown in red
    </span>
  </div>
  <div class="card-body">
    {sections_html}
  </div>
</div>
<script>{chart_scripts}</script>"""


# ── Section D — Staging → Production Pipeline ─────────────────────────────────

def section_d_staging_pipeline(data: dict) -> str:
    staging_map = data["staging_map"]

    if not staging_map:
        return """
<!-- ── D. STAGING PIPELINE ── -->
<div class="section-card mb-4">
  <div class="card-header">🔬 Section D — Staging → Production Pipeline</div>
  <div class="card-body">
    <p class="text-muted mb-0">No staging-only features found — all staging features are already live in prod.</p>
  </div>
</div>"""

    # Sort by number of customers testing (most validated first), then by events
    sorted_pipeline = sorted(
        staging_map.items(),
        key=lambda x: (-len(x[1]["customers_testing"]), -x[1]["total_staging"]),
    )

    rows = ""
    for code, info in sorted_pipeline:
        cust_list = sorted(info["customers_testing"])
        cust_badges = "".join(
            f'<span class="badge bg-light text-dark border me-1" style="font-size:.72rem">{n}</span>'
            for n in cust_list
        )
        strength = len(cust_list)
        if strength >= 3:
            signal = '<span class="badge bg-success">strong</span>'
        elif strength == 2:
            signal = '<span class="badge bg-warning text-dark">moderate</span>'
        else:
            signal = '<span class="badge bg-secondary">early</span>'

        rows += f"""
        <tr>
          <td class="ps-3"><code style="font-size:.8rem">{code}</code></td>
          <td><strong style="font-size:.88rem">{info['name']}</strong></td>
          <td><span class="badge bg-light text-dark border" style="font-size:.75rem">{info['category']}</span></td>
          <td class="text-center">{strength}</td>
          <td>{signal}</td>
          <td class="text-end">{info['total_staging']:,}</td>
          <td>{cust_badges}</td>
        </tr>"""

    return f"""
<!-- ── D. STAGING PIPELINE ── -->
<div class="section-card mb-4">
  <div class="card-header d-flex align-items-center gap-2 flex-wrap">
    🔬 Section D — Staging → Production Pipeline
    <span class="badge bg-warning text-dark">{len(staging_map)} features</span>
    <span class="text-muted fw-normal" style="font-size:.82rem">
     — features being tested in staging but not yet live in production
    </span>
  </div>
  <div class="card-body p-0">
    <table class="table table-sm table-hover mb-0">
      <thead><tr>
        <th class="ps-3">Feature Code</th>
        <th>Feature Name</th>
        <th>Category</th>
        <th class="text-center">Customers Testing</th>
        <th>Signal Strength</th>
        <th class="text-end">Staging Events</th>
        <th>Testing Customers</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""


# ── Section E — Zero-Adoption Features ───────────────────────────────────────

def _months_since(version_str: str | None, now: datetime | None = None) -> str:
    """Return 'N mo' since the release date of version_str, or '—' if unknown."""
    if not version_str:
        return "—"
    release = VERSION_RELEASE_DATES.get(version_str)
    if not release:
        return "—"
    ref = now or datetime.now()
    months = (ref.year - release.year) * 12 + (ref.month - release.month)
    return f"{months} mo"


def section_e_zero_adoption(data: dict) -> str:
    coverage = data["coverage"]
    now      = datetime.now()

    zero = [f for f in coverage if not f.get("utilized")]
    if not zero:
        return """
<div class="section-card mb-4">
  <div class="card-header">⬜ Section E — Zero-Adoption Features</div>
  <div class="card-body"><p class="text-muted mb-0">All catalog features have been used by at least one customer.</p></div>
</div>"""

    # Group by category, sort tier priority within each category
    by_cat: dict = defaultdict(list)
    for f in zero:
        by_cat[f.get("category", "—")].append(f)

    enterprise_count = sum(1 for f in zero if (f.get("tier") or "").lower() == "enterprise")
    premium_count    = sum(1 for f in zero if (f.get("tier") or "").lower() == "premium")

    tbody = ""
    for cat_name in sorted(by_cat.keys()):
        cat_feats = sorted(
            by_cat[cat_name],
            key=lambda x: (TIER_ORDER.get((x.get("tier") or "").lower(), 3), x.get("feature_name", "")),
        )
        tbody += (
            f'<tr class="table-light">'
            f'<td colspan="5" class="ps-3 py-1">'
            f'<strong style="font-size:.82rem">{cat_name}</strong>'
            f'<span class="badge bg-secondary ms-1" style="font-size:.7rem">{len(cat_feats)}</span>'
            f'</td></tr>'
        )
        for f in cat_feats:
            t_badge  = tier_badge(f.get("tier", ""))
            s_badge  = (
                f'<span class="badge bg-info text-dark ms-1" style="font-size:.68rem">'
                f'{f["status"]}</span>'
                if f.get("status") and f["status"] != "ga" else ""
            )
            intro_v  = f.get("introduced_in") or "—"
            age_str  = _months_since(f.get("introduced_in"), now)
            tbody += (
                f'<tr>'
                f'<td class="ps-4"><code style="font-size:.78rem">{f["feature_code"]}</code></td>'
                f'<td style="font-size:.85rem">{f["feature_name"]}</td>'
                f'<td>{t_badge}{s_badge}</td>'
                f'<td class="text-muted" style="font-size:.8rem">{f.get("status") or "—"}</td>'
                f'<td class="text-muted text-center" style="font-size:.8rem" '
                f'    title="introduced in v{intro_v}">{age_str}</td>'
                f'</tr>'
            )

    return f"""
<!-- ── E. ZERO ADOPTION ── -->
<div class="section-card mb-4">
  <div class="card-header d-flex align-items-center gap-2 flex-wrap">
    ⬜ Section E — Zero-Adoption Features
    <span class="badge bg-secondary">{len(zero)} features</span>
    <span class="badge bg-danger">{enterprise_count} enterprise</span>
    <span class="badge bg-warning text-dark">{premium_count} premium</span>
    <span class="text-muted fw-normal" style="font-size:.82rem"> — never used by any customer</span>
  </div>
  <div class="card-body p-0">
    <table class="table table-sm table-hover mb-0">
      <thead><tr>
        <th class="ps-3">Feature Code</th>
        <th>Feature Name</th>
        <th>Tier</th>
        <th>Status</th>
        <th class="text-center" title="Months since feature version was released">Age</th>
      </tr></thead>
      <tbody>{tbody}</tbody>
    </table>
  </div>
</div>"""


# ── Section F — Version Comparison ───────────────────────────────────────────

def section_f_versions(data: dict, product_id: str, version: str) -> str:
    d        = data["dashboard"]
    versions = d.get("by_version", [])

    if len(versions) <= 1:
        return ""

    rows = ""
    for v in versions:
        pct       = round(v["features_used"] / max(d["total_catalog_features"], 1) * 100, 1)
        highlight = 'class="table-primary"' if v["version"] == version else ""
        bar_col   = "#4F86C6" if v["version"] == version else "#adb5bd"
        rows += f"""
        <tr {highlight}>
          <td class="ps-3"><span class="badge bg-primary">{v['product_id']}</span></td>
          <td><strong>{v['version']}</strong></td>
          <td class="text-center">{v['customers']}</td>
          <td class="text-end">{v['total_events']:,}</td>
          <td style="min-width:160px">
            <div class="d-flex align-items-center gap-2">
              <div class="progress flex-grow-1" style="height:7px;border-radius:3px">
                <div class="progress-bar" style="width:{pct}%;background:{bar_col};border-radius:3px"></div>
              </div>
              <span style="font-size:.8rem;white-space:nowrap">{v['features_used']} / {d['total_catalog_features']} ({pct}%)</span>
            </div>
          </td>
        </tr>"""

    return f"""
<!-- ── F. VERSION COMPARISON ── -->
<div class="section-card mb-4">
  <div class="card-header">📦 Section F — Version Comparison</div>
  <div class="card-body p-0">
    <table class="table table-hover mb-0">
      <thead><tr>
        <th class="ps-3">Product</th><th>Version</th>
        <th class="text-center">Customers</th>
        <th class="text-end">Total Events</th>
        <th>Feature Coverage</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""


# ── Section G — Deprecation Decision Panel ───────────────────────────────────

def section_g_deprecation(data: dict) -> str:
    """
    Shows deprecated/experimental features and classifies each by customer impact:
      🟢 0 customers    → safe to remove
      🟡 1-2 customers  → migrate first
      🔴 3+ customers   → do not touch
    """
    coverage = data["coverage"]
    security_advisory = data["security_advisory"]

    # Collect deprecated + experimental (candidates for removal)
    candidates = [
        f for f in coverage
        if (f.get("status") or "").lower() in ("deprecated", "experimental")
    ]
    if not candidates:
        return """
<!-- ── G. DEPRECATION PANEL ── -->
<div class="section-card mb-4">
  <div class="card-header">🗑 Section G — Deprecation Decision Panel</div>
  <div class="card-body"><p class="text-muted mb-0">No deprecated or experimental features in this catalog version.</p></div>
</div>"""

    # Sort: 🔴 first (most risky), then 🟡, then 🟢; within each group by name
    def dep_sort_key(f):
        n = len(security_advisory.get(f["feature_code"], []))
        if n >= 3:
            return (0, f.get("feature_name", ""))
        elif n >= 1:
            return (1, f.get("feature_name", ""))
        return (2, f.get("feature_name", ""))

    sorted_cands = sorted(candidates, key=dep_sort_key)

    safe_count    = sum(1 for f in candidates if len(security_advisory.get(f["feature_code"], [])) == 0)
    migrate_count = sum(1 for f in candidates if 1 <= len(security_advisory.get(f["feature_code"], [])) <= 2)
    danger_count  = sum(1 for f in candidates if len(security_advisory.get(f["feature_code"], [])) >= 3)

    rows = ""
    for f in sorted_cands:
        cust_list = security_advisory.get(f["feature_code"], [])
        n = len(cust_list)
        if n >= 3:
            signal = '🔴'
            label  = '<span class="badge bg-danger">do not touch</span>'
        elif n >= 1:
            signal = '🟡'
            label  = '<span class="badge bg-warning text-dark">migrate first</span>'
        else:
            signal = '🟢'
            label  = '<span class="badge bg-success">safe to remove</span>'

        cust_badges = "".join(
            f'<span class="badge bg-light text-dark border me-1" style="font-size:.7rem">'
            f'{c["customer_name"]}</span>'
            for c in sorted(cust_list, key=lambda x: x["customer_name"])
        ) or '<span class="text-muted" style="font-size:.8rem">none</span>'

        t_badge = tier_badge(f.get("tier", ""))
        s_cls   = "bg-secondary" if (f.get("status") or "") == "deprecated" else "bg-info text-dark"
        s_badge = f'<span class="badge {s_cls}" style="font-size:.68rem">{f.get("status", "")}</span>'

        rows += f"""
        <tr>
          <td class="text-center" style="font-size:1.1rem">{signal}</td>
          <td class="ps-2"><code style="font-size:.78rem">{f['feature_code']}</code></td>
          <td style="font-size:.85rem">{f['feature_name']}</td>
          <td>{t_badge}</td>
          <td>{s_badge}</td>
          <td class="text-center">{n}</td>
          <td>{label}</td>
          <td>{cust_badges}</td>
        </tr>"""

    return f"""
<!-- ── G. DEPRECATION PANEL ── -->
<div class="section-card mb-4">
  <div class="card-header d-flex align-items-center gap-2 flex-wrap">
    🗑 Section G — Deprecation Decision Panel
    <span class="badge bg-success">🟢 {safe_count} safe</span>
    <span class="badge bg-warning text-dark">🟡 {migrate_count} migrate first</span>
    <span class="badge bg-danger">🔴 {danger_count} do not touch</span>
    <span class="text-muted fw-normal" style="font-size:.82rem"> — deprecated &amp; experimental features ranked by customer impact</span>
  </div>
  <div class="card-body p-0">
    <table class="table table-sm table-hover mb-0">
      <thead><tr>
        <th class="text-center" style="width:32px">Risk</th>
        <th class="ps-2">Feature Code</th>
        <th>Feature Name</th>
        <th>Tier</th>
        <th>Status</th>
        <th class="text-center">Customers Using</th>
        <th>Decision</th>
        <th>Affected Customers</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""


# ── Section H — Security Advisory Distribution ───────────────────────────────

def section_h_security_advisory(data: dict, version: str) -> str:
    """
    Interactive JS dropdown: select a feature → see which customers use it,
    with usage counts and tier badges. Useful for impact assessment when a
    security advisory affects a specific feature.
    """
    heatmap          = data["heatmap"]
    security_advisory = data["security_advisory"]
    coverage         = data["coverage"]

    features_with_users = [
        f for f in coverage
        if f["feature_code"] in security_advisory and security_advisory[f["feature_code"]]
    ]

    if not features_with_users:
        return """
<!-- ── H. SECURITY ADVISORY ── -->
<div class="section-card mb-4">
  <div class="card-header">🛡 Section H — Security Advisory Distribution</div>
  <div class="card-body"><p class="text-muted mb-0">No utilization data to build advisory mapping.</p></div>
</div>"""

    # Embed feature→customers map as JSON for client-side JS
    advisory_json = {}
    for f in features_with_users:
        code = f["feature_code"]
        advisory_json[code] = {
            "name":      f["feature_name"],
            "tier":      f.get("tier", ""),
            "status":    f.get("status", ""),
            "customers": sorted(security_advisory[code], key=lambda x: -x["total_count"]),
        }
    advisory_js = json.dumps(advisory_json)

    # Build option list sorted by feature name
    options = "".join(
        f'<option value="{f["feature_code"]}">{f["feature_name"]} ({f["feature_code"]})</option>'
        for f in sorted(features_with_users, key=lambda x: x.get("feature_name", ""))
    )

    tier_colors = {"enterprise": "#dc3545", "premium": "#ffc107", "core": "#6c757d"}

    return f"""
<!-- ── H. SECURITY ADVISORY ── -->
<div class="section-card mb-4">
  <div class="card-header d-flex align-items-center gap-2 flex-wrap">
    🛡 Section H — Security Advisory Distribution
    <span class="badge bg-primary">{len(features_with_users)} features</span>
    <span class="text-muted fw-normal" style="font-size:.82rem">
     — select a feature to see which customers would be affected by a security advisory
    </span>
  </div>
  <div class="card-body">
    <div class="mb-3 d-flex align-items-center gap-3 flex-wrap">
      <label class="fw-semibold" style="font-size:.88rem" for="advisorySelect">Affected Feature:</label>
      <select id="advisorySelect" class="form-select" style="max-width:480px;font-size:.85rem">
        <option value="">— select a feature —</option>
        {options}
      </select>
    </div>
    <div id="advisoryResult" style="display:none">
      <div class="d-flex align-items-center gap-2 mb-2 flex-wrap" id="advisoryHeader"></div>
      <table class="table table-sm table-hover" id="advisoryTable" style="max-width:600px">
        <thead><tr>
          <th>Customer</th>
          <th>Tier</th>
          <th class="text-end">Usage (events)</th>
        </tr></thead>
        <tbody id="advisoryTbody"></tbody>
      </table>
      <div class="text-muted" id="advisorySummary" style="font-size:.82rem"></div>
    </div>
  </div>
</div>
<script>
(function() {{
  const ADVISORY = {advisory_js};
  const TIER_COLORS = {json.dumps(tier_colors)};

  const sel    = document.getElementById('advisorySelect');
  const result = document.getElementById('advisoryResult');
  const header = document.getElementById('advisoryHeader');
  const tbody  = document.getElementById('advisoryTbody');
  const summary = document.getElementById('advisorySummary');

  sel.addEventListener('change', function() {{
    const code = this.value;
    if (!code || !ADVISORY[code]) {{ result.style.display = 'none'; return; }}

    const feat = ADVISORY[code];
    result.style.display = '';

    // Header
    const tierColor = TIER_COLORS[feat.tier] || '#6c757d';
    header.innerHTML =
      '<code style="font-size:.85rem">' + code + '</code>' +
      '<strong style="font-size:.95rem">' + feat.name + '</strong>' +
      '<span class="badge" style="background:' + tierColor + '">' + feat.tier + '</span>' +
      (feat.status ? '<span class="badge bg-secondary">' + feat.status + '</span>' : '');

    // Table rows
    let rows = '';
    let totalEvents = 0;
    feat.customers.forEach(function(c) {{
      const tc = TIER_COLORS[c.customer_tier] || '#6c757d';
      rows += '<tr>' +
        '<td>' + c.customer_name + '</td>' +
        '<td><span class="badge" style="background:' + tc + ';font-size:.7rem">' + c.customer_tier + '</span></td>' +
        '<td class="text-end">' + c.total_count.toLocaleString() + '</td>' +
        '</tr>';
      totalEvents += c.total_count;
    }});
    tbody.innerHTML = rows;

    summary.textContent =
      feat.customers.length + ' customer' + (feat.customers.length !== 1 ? 's' : '') +
      ' affected · ' + totalEvents.toLocaleString() + ' total events at risk';
  }});
}})();
</script>"""


# ── Section I — New Features Adoption Callout ────────────────────────────────

def section_i_new_features(data: dict, version: str) -> str:
    """
    Highlights features introduced in this version and shows their adoption rate.
    Skipped if more than 30% of features claim to be new (indicates backfill noise).
    """
    coverage = data["coverage"]
    security_advisory = data["security_advisory"]

    new_feats = [f for f in coverage if (f.get("introduced_in") or "") == version]

    # Guard: skip if more than 30% are flagged as new (backfill artifact)
    if len(new_feats) > len(coverage) * 0.30:
        return ""

    if not new_feats:
        return ""

    adopted  = [f for f in new_feats if f.get("utilized")]
    unadopted = [f for f in new_feats if not f.get("utilized")]
    adopt_pct = round(len(adopted) / len(new_feats) * 100) if new_feats else 0

    adopt_col = "#5AB08E" if adopt_pct >= 60 else ("#E8B84B" if adopt_pct >= 30 else "#E07B54")

    # Table of new features with adoption status
    rows = ""
    for f in sorted(new_feats, key=lambda x: (not x.get("utilized"), x.get("feature_name", ""))):
        used = f.get("utilized", False)
        cust_count = len(security_advisory.get(f["feature_code"], []))
        status_icon = (
            '<span class="badge bg-success">adopted</span>' if used
            else '<span class="badge bg-secondary">not yet used</span>'
        )
        t_badge = tier_badge(f.get("tier", ""))
        rows += (
            f'<tr>'
            f'<td class="ps-3"><code style="font-size:.78rem">{f["feature_code"]}</code></td>'
            f'<td style="font-size:.85rem">{f["feature_name"]}</td>'
            f'<td>{t_badge}</td>'
            f'<td>{status_icon}</td>'
            f'<td class="text-center text-muted" style="font-size:.85rem">'
            f'{cust_count if used else "—"}</td>'
            f'</tr>'
        )

    return f"""
<!-- ── I. NEW FEATURES ADOPTION ── -->
<div class="section-card mb-4">
  <div class="card-header d-flex align-items-center gap-2 flex-wrap">
    🆕 Section I — New Features Adoption (v{version})
    <span class="badge" style="background:{adopt_col}">{adopt_pct}% adopted</span>
    <span class="badge bg-success">{len(adopted)} in use</span>
    <span class="badge bg-secondary">{len(unadopted)} not yet used</span>
    <span class="text-muted fw-normal" style="font-size:.82rem">
     — features first introduced in v{version}
    </span>
  </div>
  <div class="card-body p-0">
    <table class="table table-sm table-hover mb-0">
      <thead><tr>
        <th class="ps-3">Feature Code</th>
        <th>Feature Name</th>
        <th>Tier</th>
        <th>Adoption</th>
        <th class="text-center">Customers Using</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""


# ── Assemble ──────────────────────────────────────────────────────────────────

def build_html(api_base: str, product_id: str, version: str) -> str:
    data = load_data(api_base, product_id, version)

    html_score = section_scorecard(data, product_id, version)
    html_a     = section_a_adoption_ranking(data)
    html_b     = section_b_heatmap(data)
    html_c     = section_c_dimensions(data)
    html_d     = section_d_staging_pipeline(data)
    html_e     = section_e_zero_adoption(data)
    html_f     = section_f_versions(data, product_id, version)
    html_g     = section_g_deprecation(data)
    html_h     = section_h_security_advisory(data, version)
    html_i     = section_i_new_features(data, version)

    d = data["dashboard"]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Product Team Report — {product_id} v{version}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f4f6f9; }}
    .page-header {{
      background: linear-gradient(135deg, #2a1a4a 0%, #4a2d7a 100%);
      color: white; padding: 2.5rem 0 2rem;
    }}
    .page-header .subtitle {{ opacity: .7; font-size: .95rem; }}
    .stat-card {{
      background: white; border-radius: 12px;
      padding: 1.2rem 1.4rem;
      box-shadow: 0 1px 4px rgba(0,0,0,.07); height: 100%;
    }}
    .stat-card .value  {{ font-size: 1.9rem; font-weight: 700; line-height: 1.1; }}
    .stat-card .label  {{ color: #6c757d; font-size: .76rem; text-transform: uppercase; letter-spacing: .05em; margin-top: .3rem; }}
    .stat-card .sub    {{ font-size: .78rem; color: #6c757d; margin-top: .3rem; }}
    .section-card {{
      background: white; border-radius: 12px;
      box-shadow: 0 1px 4px rgba(0,0,0,.07); margin-bottom: 1.5rem;
    }}
    .section-card .card-header {{
      background: none; border-bottom: 1px solid #e9ecef;
      padding: 1rem 1.4rem; font-weight: 600; font-size: .95rem;
    }}
    .section-card .card-body {{ padding: 1.4rem; }}
    table thead th {{
      background: #f8f9fa; font-size: .76rem; text-transform: uppercase;
      letter-spacing: .04em; color: #6c757d; border-bottom: 2px solid #dee2e6;
    }}
    table tbody td {{ vertical-align: middle; }}
    code {{ background: #f0f4ff; color: #4a2d7a; padding: .1em .35em; border-radius: 4px; }}
    .heatmap-table td, .heatmap-table th {{ padding: .2rem; }}
    .heatmap-legend {{ display: inline-flex; align-items: center; gap: 5px; font-size: .74rem; color: #6c757d; }}
    .dim-chart-box {{ background: #fafafa; border: 1px solid #eee; border-radius: 6px; padding: .6rem; }}
    .footer {{ color: #6c757d; font-size: .8rem; padding: 1.5rem 0 2rem; text-align: center; }}
  </style>
</head>
<body>

<div class="page-header">
  <div class="container">
    <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
      <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:.35rem .8rem;font-size:.78rem;letter-spacing:.06em">
        PRODUCT TEAM VIEW
      </div>
      <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:.35rem .8rem;font-size:.78rem">
        {product_id} v{version}
      </div>
    </div>
    <h1 class="mb-1" style="font-size:1.9rem;font-weight:700">Feature Utilization — Product Team Report</h1>
    <div class="subtitle">
      Generated {generated_at}
      &nbsp;·&nbsp; {d['total_customers']} customers
      &nbsp;·&nbsp; {d['utilized_features']} / {d['total_catalog_features']} features utilized
    </div>
  </div>
</div>

<div class="container py-4">

{html_score}
{html_a}
{html_b}
{html_c}
{html_d}
{html_e}
{html_f}
{html_g}
{html_h}
{html_i}

</div>

<div class="footer container">
  WSO2 Feature Utilization — Product Team Report
  &nbsp;·&nbsp; {product_id} v{version}
  &nbsp;·&nbsp; Generated {generated_at}
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate WSO2 Product Team HTML report (View 3)")
    parser.add_argument("--api",     default="http://127.0.0.1:8001", help="API base URL")
    parser.add_argument("--product", default="identity-server",       help="Product ID")
    parser.add_argument("--version", default="7.2.0",                 help="Product version")
    parser.add_argument("--out",     default=None,                    help="Output file path")
    args = parser.parse_args()

    html    = build_html(args.api, args.product, args.version)
    outfile = args.out or f"report_product_team_{args.version.replace('.', '')}.html"
    Path(outfile).write_text(html, encoding="utf-8")
    print(f"\nReport saved → {Path(outfile).resolve()}")
    print(f"Open in browser: open {outfile}")


if __name__ == "__main__":
    main()
