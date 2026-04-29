#!/usr/bin/env python3
"""
Generate a self-contained HTML schema diagram for the feature_tracking database.

Usage:
    python3 scripts/07_generate_schema_diagram.py
    python3 scripts/07_generate_schema_diagram.py --out db/schema_diagram.html
"""

import argparse
from pathlib import Path

SCHEMA = {
    "product_release": {
        "color": "#4F86C6",
        "group": "Catalog",
        "columns": [
            ("id",            "SERIAL",    "PK"),
            ("product_id",    "TEXT",      "NOT NULL"),
            ("name",          "TEXT",      "NOT NULL"),
            ("version",       "TEXT",      "NOT NULL"),
            ("description",   "TEXT",      ""),
            ("team_owner",    "TEXT",      ""),
            ("category",      "TEXT",      ""),
            ("is_active",     "BOOLEAN",   "NOT NULL"),
            ("metadata_json", "JSONB",     ""),
            ("source_file",   "TEXT",      ""),
            ("created_at",    "TIMESTAMPTZ","NOT NULL"),
        ],
    },
    "catalog_category": {
        "color": "#4F86C6",
        "group": "Catalog",
        "columns": [
            ("id",                 "SERIAL",  "PK"),
            ("product_release_id", "INTEGER", "FK → product_release"),
            ("code",               "TEXT",    "NOT NULL"),
            ("name",               "TEXT",    "NOT NULL"),
            ("description",        "TEXT",    ""),
            ("parent_category_id", "INTEGER", "FK → catalog_category (self)"),
        ],
    },
    "catalog_feature": {
        "color": "#4F86C6",
        "group": "Catalog",
        "columns": [
            ("id",                 "SERIAL",    "PK"),
            ("product_release_id", "INTEGER",   "FK → product_release"),
            ("code",               "TEXT",      "NOT NULL  UNIQUE"),
            ("name",               "TEXT",      "NOT NULL"),
            ("description",        "TEXT",      ""),
            ("category_code",      "TEXT",      "NOT NULL"),
            ("tier",               "TEXT",      "core | premium | enterprise"),
            ("status",             "TEXT",      "stable | beta | experimental"),
            ("introduced_in",      "TEXT",      ""),
            ("deprecated_in",      "TEXT",      ""),
            ("event_name",         "TEXT",      "NOT NULL"),
            ("event_category",     "TEXT",      ""),
            ("platforms",          "TEXT[]",    ""),
            ("created_at",         "TIMESTAMPTZ","NOT NULL"),
        ],
    },
    "feature_tracking_dimension": {
        "color": "#5AB08E",
        "group": "Tracking Config",
        "columns": [
            ("id",          "SERIAL",  "PK"),
            ("feature_id",  "INTEGER", "FK → catalog_feature"),
            ("name",        "TEXT",    "NOT NULL"),
            ("type",        "TEXT",    "enum | boolean | integer | string"),
            ("required",    "BOOLEAN", "NOT NULL"),
            ("description", "TEXT",    ""),
            ("enum_values", "TEXT[]",  ""),
        ],
    },
    "feature_tracking_aggregation": {
        "color": "#5AB08E",
        "group": "Tracking Config",
        "columns": [
            ("id",         "SERIAL",  "PK"),
            ("feature_id", "INTEGER", "FK → catalog_feature"),
            ("type",       "TEXT",    "count | count_distinct | sum | avg"),
            ("label",      "TEXT",    "NOT NULL"),
            ("dimension",  "TEXT",    ""),
        ],
    },
    "customer": {
        "color": "#E07B54",
        "group": "Customers & Deployments",
        "columns": [
            ("id",         "TEXT",      "PK"),
            ("name",       "TEXT",      "NOT NULL"),
            ("region",     "TEXT",      ""),
            ("tier",       "TEXT",      "core | premium | enterprise"),
            ("created_at", "TIMESTAMPTZ","NOT NULL"),
        ],
    },
    "deployment": {
        "color": "#E07B54",
        "group": "Customers & Deployments",
        "columns": [
            ("id",                 "TEXT",      "PK"),
            ("customer_id",        "TEXT",      "FK → customer"),
            ("product_release_id", "INTEGER",   "FK → product_release"),
            ("environment",        "TEXT",      "prod | staging | dev"),
            ("created_at",         "TIMESTAMPTZ","NOT NULL"),
        ],
    },
    "utilization_report": {
        "color": "#A06EC9",
        "group": "Utilization",
        "columns": [
            ("id",            "SERIAL",      "PK"),
            ("deployment_id", "TEXT",        "FK → deployment"),
            ("report_from",   "TIMESTAMPTZ", "NOT NULL"),
            ("report_to",     "TIMESTAMPTZ", "NOT NULL"),
            ("source_file",   "TEXT",        ""),
            ("created_at",    "TIMESTAMPTZ", "NOT NULL"),
        ],
    },
    "feature_utilization": {
        "color": "#A06EC9",
        "group": "Utilization",
        "columns": [
            ("id",                  "SERIAL",  "PK"),
            ("report_id",           "INTEGER", "FK → utilization_report"),
            ("catalog_feature_id",  "INTEGER", "FK → catalog_feature"),
            ("feature_code",        "TEXT",    "NOT NULL"),
            ("total_count",         "INTEGER", "NOT NULL"),
            ("dimension_breakdown", "JSONB",   ""),
            ("created_at",          "TIMESTAMPTZ","NOT NULL"),
        ],
    },
    "feature_usage_event": {
        "color": "#E8B84B",
        "group": "Real-time Events",
        "columns": [
            ("id",                 "SERIAL",      "PK"),
            ("product_release_id", "INTEGER",     "FK → product_release"),
            ("feature_id",         "INTEGER",     "FK → catalog_feature"),
            ("event_name",         "TEXT",        "NOT NULL"),
            ("platform",           "TEXT",        ""),
            ("event_timestamp",    "TIMESTAMPTZ", "NOT NULL"),
            ("dimensions",         "JSONB",       ""),
            ("user_id",            "TEXT",        ""),
            ("tenant_id",          "TEXT",        ""),
            ("raw_payload",        "JSONB",       ""),
            ("created_at",         "TIMESTAMPTZ", "NOT NULL"),
        ],
    },
}

RELATIONSHIPS = [
    ("catalog_category",           "product_release_id", "product_release",          "id",  "N:1", "Product Release"),
    ("catalog_category",           "parent_category_id", "catalog_category",          "id",  "N:1", "Parent Category (self)"),
    ("catalog_feature",            "product_release_id", "product_release",          "id",  "N:1", "Product Release"),
    ("feature_tracking_dimension", "feature_id",         "catalog_feature",          "id",  "N:1", "Feature"),
    ("feature_tracking_aggregation","feature_id",        "catalog_feature",          "id",  "N:1", "Feature"),
    ("deployment",                 "customer_id",        "customer",                 "id",  "N:1", "Customer"),
    ("deployment",                 "product_release_id", "product_release",          "id",  "N:1", "Product Release"),
    ("utilization_report",         "deployment_id",      "deployment",               "id",  "N:1", "Deployment"),
    ("feature_utilization",        "report_id",          "utilization_report",       "id",  "N:1", "Utilization Report"),
    ("feature_utilization",        "catalog_feature_id", "catalog_feature",          "id",  "N:1", "Catalog Feature"),
    ("feature_usage_event",        "product_release_id", "product_release",          "id",  "N:1", "Product Release"),
    ("feature_usage_event",        "feature_id",         "catalog_feature",          "id",  "N:1", "Catalog Feature"),
]

GROUPS = {
    "Catalog":                   {"color": "#4F86C6", "bg": "#EEF4FC"},
    "Tracking Config":           {"color": "#5AB08E", "bg": "#EEF8F3"},
    "Customers & Deployments":   {"color": "#E07B54", "bg": "#FDF3EE"},
    "Utilization":               {"color": "#A06EC9", "bg": "#F5EEF8"},
    "Real-time Events":          {"color": "#E8B84B", "bg": "#FDF8EE"},
}


def build_html(out_path: str):
    # ── table cards ───────────────────────────────────────────────────────────
    tables_by_group = {}
    for tname, tdef in SCHEMA.items():
        tables_by_group.setdefault(tdef["group"], []).append((tname, tdef))

    table_cards_html = ""
    for group, tables in tables_by_group.items():
        gcfg = GROUPS[group]
        cards_in_group = ""
        for tname, tdef in tables:
            col_rows = ""
            for col, dtype, note in tdef["columns"]:
                icon = "🔑" if note == "PK" else ("🔗" if "FK" in note else "")
                fk_note = f'<span class="fk-note">{note}</span>' if "FK" in note else ""
                pk_style = "font-weight:600;background:#fffbea" if note == "PK" else ""
                constraint = ""
                if "NOT NULL" in note and "FK" not in note and note != "PK":
                    constraint = '<span class="badge-nn">NN</span>'
                col_rows += f"""
                <tr style="{pk_style}">
                  <td class="col-icon">{icon}</td>
                  <td class="col-name">{col}</td>
                  <td class="col-type">{dtype}</td>
                  <td class="col-note">{fk_note}{constraint}</td>
                </tr>"""

            cards_in_group += f"""
            <div class="table-card" id="tbl-{tname}" draggable="true">
              <div class="table-header" style="background:{tdef['color']}">
                <span class="table-name">{tname}</span>
                <span class="table-group-badge">{group}</span>
              </div>
              <table class="col-table"><tbody>{col_rows}</tbody></table>
            </div>"""

        table_cards_html += f"""
        <div class="group-section">
          <div class="group-label" style="color:{gcfg['color']};border-left:3px solid {gcfg['color']}">
            {group}
          </div>
          <div class="group-cards">{cards_in_group}</div>
        </div>"""

    # ── relationships list ─────────────────────────────────────────────────────
    rel_rows = ""
    for src_tbl, src_col, tgt_tbl, tgt_col, cardinality, label in RELATIONSHIPS:
        src_color = SCHEMA[src_tbl]["color"]
        tgt_color = SCHEMA[tgt_tbl]["color"]
        rel_rows += f"""
        <tr>
          <td><span class="tbl-pill" style="background:{src_color}">{src_tbl}</span></td>
          <td><code class="small">{src_col}</code></td>
          <td class="text-center text-muted">→</td>
          <td><span class="tbl-pill" style="background:{tgt_color}">{tgt_tbl}</span></td>
          <td><code class="small">{tgt_col}</code></td>
          <td><span class="badge bg-light text-dark border">{cardinality}</span></td>
          <td class="text-muted small">{label}</td>
        </tr>"""

    # ── legend ─────────────────────────────────────────────────────────────────
    legend_html = ""
    for group, gcfg in GROUPS.items():
        legend_html += f"""
        <div class="legend-item">
          <span class="legend-dot" style="background:{gcfg['color']}"></span>
          {group}
        </div>"""

    group_counts_html = "".join(
        f'<div class="d-flex align-items-center gap-2 mb-1">'
        f'<span class="legend-dot" style="background:{gcfg["color"]}"></span>'
        f'<span>{g}</span>'
        f'<span class="ms-auto text-muted">{len(tables_by_group.get(g, []))} tables</span>'
        f'</div>'
        for g, gcfg in GROUPS.items()
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Feature Tracking — DB Schema</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f0f2f5; margin: 0; }}
    .page-header {{ background: linear-gradient(135deg,#1a2a4a,#2d4a7a); color:#fff; padding:1.6rem 2rem; }}
    .page-header h1 {{ font-size:1.5rem; font-weight:700; margin:0 0 .25rem; }}
    .page-header p  {{ margin:0; opacity:.7; font-size:.85rem; }}

    /* layout */
    .layout {{ display:flex; height:calc(100vh - 72px); overflow:hidden; }}
    .sidebar {{ width:300px; min-width:300px; background:#fff; border-right:1px solid #e0e0e0;
                overflow-y:auto; padding:1rem; }}
    .canvas  {{ flex:1; overflow:auto; padding:1.5rem; }}

    /* legend */
    .legend {{ display:flex; flex-wrap:wrap; gap:.6rem; margin-bottom:1rem; }}
    .legend-item {{ display:flex; align-items:center; gap:.4rem; font-size:.8rem; }}
    .legend-dot  {{ width:10px; height:10px; border-radius:50%; display:inline-block; flex-shrink:0; }}

    /* group */
    .group-section {{ margin-bottom:1.8rem; }}
    .group-label   {{ font-size:.75rem; font-weight:700; letter-spacing:.06em;
                      text-transform:uppercase; padding-left:.6rem; margin-bottom:.7rem; }}
    .group-cards   {{ display:flex; flex-wrap:wrap; gap:1rem; }}

    /* table card */
    .table-card {{
      background:#fff; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,.1);
      width:280px; overflow:hidden; transition:box-shadow .15s;
    }}
    .table-card:hover {{ box-shadow:0 4px 16px rgba(0,0,0,.18); }}
    .table-header {{
      display:flex; justify-content:space-between; align-items:center;
      padding:.55rem .75rem; color:#fff;
    }}
    .table-name  {{ font-weight:700; font-size:.85rem; letter-spacing:.02em; }}
    .table-group-badge {{ font-size:.65rem; opacity:.8; background:rgba(255,255,255,.2);
                          border-radius:4px; padding:.1rem .4rem; }}
    .col-table   {{ width:100%; border-collapse:collapse; font-size:.78rem; }}
    .col-table tr:hover {{ background:#f8f9fa; }}
    .col-table td {{ padding:.28rem .6rem; border-top:1px solid #f0f0f0; vertical-align:middle; }}
    .col-icon  {{ width:18px; text-align:center; }}
    .col-name  {{ font-family:monospace; color:#1a2a4a; }}
    .col-type  {{ color:#6c757d; font-size:.72rem; }}
    .col-note  {{ }}
    .fk-note   {{ font-size:.68rem; color:#888; display:block; }}
    .badge-nn  {{ font-size:.62rem; background:#fff3cd; color:#856404;
                  border-radius:3px; padding:.05rem .3rem; }}

    /* relationships table */
    .tbl-pill {{ color:#fff; border-radius:4px; padding:.1rem .45rem;
                 font-size:.72rem; font-weight:600; white-space:nowrap; }}

    /* sidebar tabs */
    .sidebar-tab {{ cursor:pointer; padding:.4rem .7rem; border-radius:6px;
                    font-size:.82rem; color:#444; }}
    .sidebar-tab.active {{ background:#eef4fc; color:#2d4a7a; font-weight:600; }}
    .sidebar-section {{ display:none; }}
    .sidebar-section.active {{ display:block; }}

    /* search */
    .search-box {{ width:100%; padding:.35rem .6rem; border:1px solid #ddd;
                   border-radius:6px; font-size:.82rem; margin-bottom:.8rem; }}
    .search-box:focus {{ outline:none; border-color:#4F86C6; }}
  </style>
</head>
<body>

<div class="page-header">
  <h1>Feature Tracking — Database Schema</h1>
  <p>WSO2 Feature Utilization Platform &nbsp;·&nbsp; 10 tables &nbsp;·&nbsp; {len(RELATIONSHIPS)} relationships</p>
</div>

<div class="layout">

  <!-- ── SIDEBAR ─────────────────────────────────────────────────────────── -->
  <div class="sidebar">
    <div class="d-flex gap-1 mb-3">
      <div class="sidebar-tab active" onclick="switchTab('overview')">Overview</div>
      <div class="sidebar-tab"        onclick="switchTab('relations')">Relations</div>
      <div class="sidebar-tab"        onclick="switchTab('search')">Search</div>
    </div>

    <!-- Overview tab -->
    <div class="sidebar-section active" id="tab-overview">
      <div class="legend">{legend_html}</div>
      <hr>
      <div style="font-size:.8rem;color:#555;line-height:1.7">
        <div><strong>🔑</strong> Primary key</div>
        <div><strong>🔗</strong> Foreign key</div>
        <div><span class="badge-nn">NN</span> NOT NULL constraint</div>
      </div>
      <hr>
      <div style="font-size:.8rem">
        <div class="mb-1"><strong>Tables by group</strong></div>
        {group_counts_html}
      </div>
      <hr>
      <div style="font-size:.78rem;color:#777">
        <div><strong>Data flow</strong></div>
        <div class="mt-1" style="line-height:2">
          Taxonomy YAML<br>
          ↓ <code style="font-size:.72rem">product_release</code><br>
          ↓ <code style="font-size:.72rem">catalog_category</code><br>
          ↓ <code style="font-size:.72rem">catalog_feature</code><br>
          &nbsp;&nbsp;↳ dimensions / aggregations<br>
          <br>
          Utilization YAML<br>
          ↓ <code style="font-size:.72rem">utilization_report</code><br>
          ↓ <code style="font-size:.72rem">feature_utilization</code><br>
          &nbsp;&nbsp;↳ FK → catalog_feature
        </div>
      </div>
    </div>

    <!-- Relations tab -->
    <div class="sidebar-section" id="tab-relations">
      <div style="font-size:.78rem">
        <table class="table table-sm">
          <thead><tr>
            <th>From</th><th>Column</th><th></th><th>To</th><th>Column</th><th>Card.</th>
          </tr></thead>
          <tbody>{rel_rows}</tbody>
        </table>
      </div>
    </div>

    <!-- Search tab -->
    <div class="sidebar-section" id="tab-search">
      <input class="search-box" id="searchInput" placeholder="Search tables or columns…" oninput="doSearch(this.value)">
      <div id="searchResults" style="font-size:.8rem"></div>
    </div>
  </div>

  <!-- ── CANVAS ──────────────────────────────────────────────────────────── -->
  <div class="canvas" id="canvas">
    {table_cards_html}
  </div>

</div><!-- /layout -->

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
function switchTab(name) {{
  document.querySelectorAll('.sidebar-tab').forEach((t,i) => {{
    const names = ['overview','relations','search'];
    t.classList.toggle('active', names[i] === name);
  }});
  document.querySelectorAll('.sidebar-section').forEach(s => s.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
}}

// Column search
const SCHEMA_JS = {{}};
{chr(10).join(
    f'SCHEMA_JS["{tname}"] = {[col for col,_,_ in tdef["columns"]]};'
    for tname, tdef in SCHEMA.items()
)}

function doSearch(q) {{
  const res = document.getElementById('searchResults');
  if (!q.trim()) {{ res.innerHTML = ''; return; }}
  q = q.toLowerCase();
  let html = '';
  for (const [tbl, cols] of Object.entries(SCHEMA_JS)) {{
    const matched = cols.filter(c => c.toLowerCase().includes(q) || tbl.toLowerCase().includes(q));
    if (matched.length) {{
      const el = document.querySelector('#tbl-' + tbl + ' .table-header');
      const color = el ? el.style.background : '#888';
      html += '<div class="mb-2">'
        + '<span class="tbl-pill" style="background:' + color + ';cursor:pointer"'
        + ' onclick="document.getElementById(\'tbl-' + tbl + '\').scrollIntoView({{behavior:\'smooth\',block:\'center\'}})">' + tbl + '</span>'
        + '<div class="ms-1 mt-1">' + matched.map(c => '<code style="font-size:.72rem">' + c + '</code>').join(' ') + '</div>'
        + '</div>';
    }}
  }}
  res.innerHTML = html || '<div class="text-muted">No matches</div>';
}}
</script>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(description="Generate DB schema diagram")
    parser.add_argument("--out", default="db/schema_diagram.html", help="Output file path")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(args.out), encoding="utf-8")
    print(f"Schema diagram saved → {out.resolve()}")
    print(f"Open in browser: open {out}")


if __name__ == "__main__":
    main()
