#!/usr/bin/env python3
"""
WSO2 Feature Utilization — Management Report Generator

Fetches live data from the API and produces a self-contained HTML report.

Usage:
    python3 scripts/06_generate_html_report.py
    python3 scripts/06_generate_html_report.py --api http://127.0.0.1:8001 --out report.html
    python3 scripts/06_generate_html_report.py --product identity-server --version 7.2.0
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


def fetch(api_base: str, path: str):
    url = f"{api_base}{path}"
    try:
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
        return None


def color_for_index(i: int) -> str:
    palette = [
        "#4F86C6", "#E07B54", "#5AB08E", "#A06EC9",
        "#E8B84B", "#4BC0C0", "#E66A9A", "#7B9E3C",
        "#C76B6B", "#6B8EC7",
    ]
    return palette[i % len(palette)]


def build_html(api_base: str, product_id: str, version: str) -> str:
    print("Fetching data from API...")

    dashboard   = fetch(api_base, f"/reports/dashboard?product_id={product_id}&version={version}")
    summary     = fetch(api_base, f"/reports/features/summary?product_id={product_id}&version={version}")
    by_category = fetch(api_base, f"/reports/features/by-category?product_id={product_id}&version={version}")
    coverage    = fetch(api_base, f"/reports/catalog/coverage?product_id={product_id}&version={version}")
    taxonomy    = fetch(api_base, f"/reports/catalog/taxonomy?product_id={product_id}&version={version}")

    if not dashboard:
        sys.exit("Could not reach API. Is the server running?")

    top10 = (summary or [])[:10]

    # ── chart data ────────────────────────────────────────────────────────────
    cat_labels  = json.dumps([r["category_name"] for r in (by_category or [])])
    cat_data    = json.dumps([r["total_usage"]   for r in (by_category or [])])
    cat_colors  = json.dumps([color_for_index(i) for i in range(len(by_category or []))])

    feat_labels = json.dumps([r["feature_code"].split(".")[-1] for r in top10])
    feat_data   = json.dumps([r["total_usage"] for r in top10])
    feat_colors = json.dumps([color_for_index(i) for i in range(len(top10))])

    utilized_count   = dashboard["utilized_features"]
    unutilized_count = dashboard["total_catalog_features"] - utilized_count
    coverage_colors  = json.dumps(["#5AB08E", "#E8E8E8"])
    coverage_data    = json.dumps([utilized_count, unutilized_count])

    # ── version comparison table ───────────────────────────────────────────────
    version_rows = ""
    for v in dashboard.get("by_version", []):
        cat_pct = round(v["features_used"] / max(dashboard["total_catalog_features"], 1) * 100, 1)
        version_rows += f"""
        <tr>
          <td><span class="badge bg-primary">{v['product_id']}</span></td>
          <td><strong>{v['version']}</strong></td>
          <td>{v['customers']}</td>
          <td>{v['total_events']:,}</td>
          <td>
            <div class="d-flex align-items-center gap-2">
              <div class="progress flex-grow-1" style="height:8px">
                <div class="progress-bar" style="width:{cat_pct}%;background:#4F86C6"></div>
              </div>
              <small>{v['features_used']} / {dashboard['total_catalog_features']}</small>
            </div>
          </td>
        </tr>"""

    # ── top features table ─────────────────────────────────────────────────────
    feat_rows = ""
    max_usage = max((r["total_usage"] for r in top10), default=1)
    for i, r in enumerate(top10):
        pct = round(r["total_usage"] / max_usage * 100)
        tier_badge = f'<span class="badge bg-secondary">{r["tier"]}</span>' if r.get("tier") else ""
        feat_rows += f"""
        <tr>
          <td class="text-muted small">{i+1}</td>
          <td><code class="small">{r['feature_code']}</code></td>
          <td>{r['feature_name']}</td>
          <td><span class="badge" style="background:{color_for_index(i)};font-size:.7rem">{r['category']}</span></td>
          <td>{tier_badge}</td>
          <td>
            <div class="d-flex align-items-center gap-2">
              <div class="progress flex-grow-1" style="height:8px">
                <div class="progress-bar" style="width:{pct}%;background:{color_for_index(i)}"></div>
              </div>
              <small class="text-nowrap">{r['total_usage']:,}</small>
            </div>
          </td>
          <td class="text-center">{r['customer_count']}</td>
        </tr>"""

    # ── coverage table ─────────────────────────────────────────────────────────
    used_rows = ""
    unused_rows = ""
    for r in (coverage or []):
        cat_badge = f'<span class="badge bg-light text-dark border">{r["category"]}</span>'
        tier_badge = f'<span class="badge bg-secondary">{r["tier"]}</span>' if r.get("tier") else '<span class="text-muted">—</span>'
        if r["utilized"]:
            used_rows += f"""
            <tr>
              <td><code class="small">{r['feature_code']}</code></td>
              <td>{r['feature_name']}</td>
              <td>{cat_badge}</td>
              <td>{tier_badge}</td>
              <td class="text-end"><strong>{r['total_usage']:,}</strong></td>
              <td class="text-center text-success">✓</td>
            </tr>"""
        else:
            unused_rows += f"""
            <tr class="text-muted">
              <td><code class="small">{r['feature_code']}</code></td>
              <td>{r['feature_name']}</td>
              <td>{cat_badge}</td>
              <td>{tier_badge}</td>
              <td class="text-end">0</td>
              <td class="text-center text-danger">✗</td>
            </tr>"""

    # ── taxonomy tree ──────────────────────────────────────────────────────────
    def render_features(features):
        if not features:
            return '<p class="text-muted small ms-3">No features</p>'
        rows = ""
        for f in features:
            utilized_icon = '🟢' if f['utilized'] else '⚪'
            platform_badges = "".join(
                f'<span class="badge bg-light text-dark border me-1" style="font-size:.65rem">{p}</span>'
                for p in f.get("platforms", [])
            )
            rows += f"""
            <tr>
              <td class="ps-4">{utilized_icon} <code class="small">{f['code']}</code></td>
              <td>{f['name']}</td>
              <td>{platform_badges}</td>
              <td class="text-end"><strong>{f['total_usage']:,}</strong></td>
            </tr>"""
        return f'<table class="table table-sm mb-0 small">{rows}</table>'

    def render_category(cat, depth=0):
        bg = "f8f9fa" if depth == 0 else "ffffff"
        sub_html = "".join(render_category(s, depth + 1) for s in cat.get("sub_categories", []))
        feat_count = len(cat.get("features", []))
        utilized_count_cat = sum(1 for f in cat.get("features", []) if f["utilized"])
        badge = (f'<span class="badge bg-success">{utilized_count_cat}/{feat_count} utilized</span>'
                 if feat_count else "")
        return f"""
        <div class="border rounded mb-2" style="background:#{bg}">
          <div class="d-flex align-items-center gap-2 px-3 py-2 border-bottom"
               style="cursor:pointer" data-bs-toggle="collapse"
               data-bs-target="#cat-{cat['id']}">
            <strong>{'&nbsp;&nbsp;&nbsp;&nbsp;' * depth}{'└ ' if depth > 0 else ''}
              {cat['name']}</strong>
            {badge}
            <span class="ms-auto text-muted small">{cat.get('description','')[:80]}</span>
          </div>
          <div id="cat-{cat['id']}" class="collapse">
            <div class="p-2">{render_features(cat['features'])}</div>
            {sub_html}
          </div>
        </div>"""

    taxonomy_html = ""
    if taxonomy:
        for cat in taxonomy.get("categories", []):
            taxonomy_html += render_category(cat)

    # ── assemble HTML ──────────────────────────────────────────────────────────
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    top_feature_name = dashboard["top_feature"]["name"] if dashboard.get("top_feature") else "—"
    top_feature_total = f"{dashboard['top_feature']['total']:,}" if dashboard.get("top_feature") else "0"
    top_category_name = dashboard["top_category"]["name"] if dashboard.get("top_category") else "—"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WSO2 Feature Utilization Report — {product_id} v{version}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f4f6f9; }}
    .page-header {{ background: linear-gradient(135deg, #1a2a4a 0%, #2d4a7a 100%); color: white; padding: 2.5rem 0 2rem; }}
    .page-header .subtitle {{ opacity: .7; font-size: .95rem; }}
    .stat-card {{ background: white; border-radius: 12px; padding: 1.4rem 1.6rem; box-shadow: 0 1px 4px rgba(0,0,0,.07); }}
    .stat-card .value {{ font-size: 2rem; font-weight: 700; line-height: 1; }}
    .stat-card .label {{ color: #6c757d; font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; margin-top: .3rem; }}
    .stat-card .sub {{ font-size: .8rem; color: #6c757d; margin-top: .4rem; }}
    .section-card {{ background: white; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.07); margin-bottom: 1.5rem; }}
    .section-card .card-header {{ background: none; border-bottom: 1px solid #e9ecef; padding: 1rem 1.4rem; font-weight: 600; font-size: .95rem; }}
    .section-card .card-body {{ padding: 1.4rem; }}
    table thead th {{ background: #f8f9fa; font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; color: #6c757d; border-bottom: 2px solid #dee2e6; }}
    code {{ background: #f0f4ff; color: #2d4a7a; padding: .1em .35em; border-radius: 4px; }}
    .chart-container {{ position: relative; height: 280px; }}
    .utilized-dot {{ width: 10px; height: 10px; border-radius: 50%; background: #5AB08E; display: inline-block; }}
    .footer {{ color: #6c757d; font-size: .8rem; padding: 1.5rem 0 2rem; text-align: center; }}
  </style>
</head>
<body>

<!-- ── HEADER ──────────────────────────────────────────────────────────── -->
<div class="page-header">
  <div class="container">
    <div class="d-flex align-items-center gap-3 mb-2">
      <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:.4rem .8rem;font-size:.8rem;letter-spacing:.06em">
        WSO2 IDENTITY SERVER
      </div>
      <span style="opacity:.5">•</span>
      <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:.4rem .8rem;font-size:.8rem">
        v{version}
      </div>
    </div>
    <h1 class="mb-1" style="font-size:1.9rem;font-weight:700">Feature Utilization Report</h1>
    <div class="subtitle">Generated {generated_at} &nbsp;·&nbsp; All customers &nbsp;·&nbsp; March 2026</div>
  </div>
</div>

<div class="container py-4">

<!-- ── EXECUTIVE SUMMARY ───────────────────────────────────────────────── -->
<div class="row g-3 mb-4">
  <div class="col-6 col-md-3">
    <div class="stat-card">
      <div class="value text-primary">{dashboard['total_customers']}</div>
      <div class="label">Customers</div>
      <div class="sub">{dashboard['total_deployments']} deployments</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="stat-card">
      <div class="value" style="color:#E07B54">{dashboard['total_events']:,}</div>
      <div class="label">Total Feature Events</div>
      <div class="sub">{dashboard['total_reports']} utilization reports</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="stat-card">
      <div class="value" style="color:#5AB08E">{dashboard['utilization_rate_pct']}%</div>
      <div class="label">Feature Adoption Rate</div>
      <div class="sub">{dashboard['utilized_features']} of {dashboard['total_catalog_features']} catalog features used</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="stat-card">
      <div class="value" style="color:#A06EC9;font-size:1.2rem;padding-top:.4rem">{top_feature_name[:28]}</div>
      <div class="label">Top Feature</div>
      <div class="sub">{top_feature_total} events &nbsp;·&nbsp; {top_category_name}</div>
    </div>
  </div>
</div>

<!-- ── VERSION COMPARISON ──────────────────────────────────────────────── -->
<div class="section-card mb-4">
  <div class="card-header">📦 Version Comparison</div>
  <div class="card-body p-0">
    <table class="table table-hover mb-0">
      <thead><tr>
        <th class="ps-4">Product</th><th>Version</th><th>Customers</th>
        <th>Total Events</th><th>Feature Coverage</th>
      </tr></thead>
      <tbody>{version_rows}</tbody>
    </table>
  </div>
</div>

<!-- ── CHARTS ROW ───────────────────────────────────────────────────────── -->
<div class="row g-3 mb-4">

  <div class="col-md-5">
    <div class="section-card h-100">
      <div class="card-header">🍩 Events by Category</div>
      <div class="card-body">
        <div class="chart-container"><canvas id="catChart"></canvas></div>
      </div>
    </div>
  </div>

  <div class="col-md-5">
    <div class="section-card h-100">
      <div class="card-header">📊 Top 10 Features by Usage</div>
      <div class="card-body">
        <div class="chart-container"><canvas id="featChart"></canvas></div>
      </div>
    </div>
  </div>

  <div class="col-md-2">
    <div class="section-card h-100">
      <div class="card-header">🔦 Coverage</div>
      <div class="card-body d-flex flex-column align-items-center justify-content-center">
        <div class="chart-container" style="height:160px;width:160px">
          <canvas id="covChart"></canvas>
        </div>
        <div class="mt-3 text-center">
          <div><span class="utilized-dot"></span> <small>{utilized_count} utilized</small></div>
          <div><span style="width:10px;height:10px;border-radius:50%;background:#E8E8E8;display:inline-block"></span>
               <small>{unutilized_count} unused</small></div>
        </div>
      </div>
    </div>
  </div>

</div>

<!-- ── TOP FEATURES TABLE ───────────────────────────────────────────────── -->
<div class="section-card mb-4">
  <div class="card-header">🏆 Top Features by Usage — {product_id} v{version}</div>
  <div class="card-body p-0">
    <table class="table table-hover mb-0">
      <thead><tr>
        <th class="ps-3">#</th><th>Code</th><th>Feature</th><th>Category</th>
        <th>Tier</th><th>Usage</th><th class="text-center">Customers</th>
      </tr></thead>
      <tbody>{feat_rows}</tbody>
    </table>
  </div>
</div>

<!-- ── CATALOG COVERAGE ──────────────────────────────────────────────────── -->
<div class="section-card mb-4">
  <div class="card-header">📋 Catalog Coverage — {product_id} v{version}</div>
  <div class="card-body p-0">
    <ul class="nav nav-tabs px-3 pt-2" id="covTab" role="tablist">
      <li class="nav-item">
        <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tabUsed">
          ✅ Utilized ({utilized_count})
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabUnused">
          ⬜ Unused ({unutilized_count})
        </button>
      </li>
    </ul>
    <div class="tab-content">
      <div class="tab-pane fade show active" id="tabUsed">
        <table class="table table-sm table-hover mb-0">
          <thead><tr><th class="ps-3">Code</th><th>Feature</th><th>Category</th><th>Tier</th><th class="text-end pe-3">Events</th><th class="text-center">Used</th></tr></thead>
          <tbody>{used_rows}</tbody>
        </table>
      </div>
      <div class="tab-pane fade" id="tabUnused">
        <table class="table table-sm table-hover mb-0">
          <thead><tr><th class="ps-3">Code</th><th>Feature</th><th>Category</th><th>Tier</th><th class="text-end pe-3">Events</th><th class="text-center">Used</th></tr></thead>
          <tbody>{unused_rows}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ── TAXONOMY BROWSER ──────────────────────────────────────────────────── -->
<div class="section-card mb-4">
  <div class="card-header">🗂️ Product Taxonomy — {product_id} v{version}
    <small class="text-muted ms-2 fw-normal">Click a category to expand features</small>
  </div>
  <div class="card-body">
    <div class="mb-2 d-flex gap-2">
      <span><span class="utilized-dot"></span> <small>Utilized</small></span>
      <span><span style="width:10px;height:10px;border-radius:50%;background:#adb5bd;display:inline-block"></span> <small>Not utilized</small></span>
    </div>
    {taxonomy_html}
  </div>
</div>

</div><!-- /container -->

<div class="footer container">
  WSO2 Feature Utilization Report &nbsp;·&nbsp; Generated {generated_at}
  &nbsp;·&nbsp; <code style="font-size:.8rem">{product_id} v{version}</code>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
// Category donut
new Chart(document.getElementById('catChart'), {{
  type: 'doughnut',
  data: {{ labels: {cat_labels}, datasets: [{{ data: {cat_data}, backgroundColor: {cat_colors}, borderWidth: 2 }}] }},
  options: {{ plugins: {{ legend: {{ position: 'bottom', labels: {{ font: {{ size: 11 }}, boxWidth: 12 }} }} }}, cutout: '60%' }}
}});

// Top features bar
new Chart(document.getElementById('featChart'), {{
  type: 'bar',
  data: {{ labels: {feat_labels}, datasets: [{{ data: {feat_data}, backgroundColor: {feat_colors}, borderRadius: 4 }}] }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: '#f0f0f0' }}, ticks: {{ font: {{ size: 10 }} }} }},
      y: {{ ticks: {{ font: {{ size: 10 }} }} }}
    }}
  }}
}});

// Coverage donut
new Chart(document.getElementById('covChart'), {{
  type: 'doughnut',
  data: {{ labels: ['Utilized', 'Unused'], datasets: [{{ data: {coverage_data}, backgroundColor: {coverage_colors}, borderWidth: 0 }}] }},
  options: {{ plugins: {{ legend: {{ display: false }} }}, cutout: '65%' }}
}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate WSO2 management HTML report")
    parser.add_argument("--api",     default="http://127.0.0.1:8001", help="API base URL")
    parser.add_argument("--product", default="identity-server",       help="Product ID")
    parser.add_argument("--version", default="7.2.0",                 help="Product version")
    parser.add_argument("--out",     default="report.html",           help="Output file")
    args = parser.parse_args()

    html = build_html(args.api, args.product, args.version)
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"\nReport saved → {out.resolve()}")
    print("Open in browser: open report.html")


if __name__ == "__main__":
    main()
