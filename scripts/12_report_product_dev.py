#!/usr/bin/env python3
"""
WSO2 Feature Utilization — Product Development Team Report

Sections:
  1. Feature Adoption Overview       — adoption % per feature, tier (High/Med/Low/Zero), trend
  2. Feature Usage Depth             — explicitly enabled vs actively-used
  3. Feature Drop-Off / Abandonment  — features losing adoption across versions
  4. Adoption by Version             — per-version feature adoption comparison matrix
  5. Category-Level Insights         — taxonomy category adoption summary
  6. Zero-Usage Features             — never-adopted catalog entries
  7. Top Feature Combinations        — feature co-occurrence across customer deployments

Usage:
    python3 scripts/12_report_product_dev.py
    python3 scripts/12_report_product_dev.py --product identity-server
    python3 scripts/12_report_product_dev.py --out reports/product_dev.html
    python3 scripts/12_report_product_dev.py --api http://127.0.0.1:8001
"""

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path


# ── Constants ─────────────────────────────────────────────────────────────────

# Predefined interesting feature combinations (use prefix patterns for portability)
PREDEFINED_COMBOS = [
    {
        "label": "Core Auth Trio",
        "desc": "OIDC SSO + any Governance feature + Session Management",
        "patterns": ["is.sso.oidc", "is.governance."],
        "min_match": 2,
    },
    {
        "label": "SAML + OIDC Federation",
        "desc": "SAML 2.0 SSO + OIDC SSO (dual-protocol deployment)",
        "patterns": ["is.sso.oidc", "is.sso.saml"],
        "min_match": 2,
    },
    {
        "label": "MFA Standard Pack",
        "desc": "TOTP + Email OTP (two MFA factors active)",
        "patterns": ["is.mfa.totp", "is.mfa.email-otp"],
        "min_match": 2,
    },
    {
        "label": "MFA + Adaptive Auth",
        "desc": "Any MFA factor + Adaptive / Conditional Authentication",
        "patterns": ["is.mfa.", "is.mfa.adaptive", "is.adaptive-auth."],
        "min_match": 2,
    },
    {
        "label": "Social + Enterprise Federation",
        "desc": "Social Login (any provider) + Enterprise IdP (SAML or OIDC)",
        "patterns": ["is.federation.", "is.social-login."],
        "min_match": 2,
    },
    {
        "label": "B2B Platform Bundle",
        "desc": "B2B Org Management + any Provisioning feature",
        "patterns": ["is.org", "is.user-management."],
        "min_match": 2,
    },
    {
        "label": "Passwordless Combo",
        "desc": "Passkeys / FIDO2 + Magic Link (full passwordless path)",
        "patterns": ["is.mfa.passkey", "is.mfa.magic-link"],
        "min_match": 2,
    },
    {
        "label": "Self-Service Suite",
        "desc": "My Account Portal + Account Recovery",
        "patterns": ["is.user-management.self-registration", "is.user."],
        "min_match": 2,
    },
]

# Combo visual colours (cycled)
COMBO_COLORS = [
    ("#166534", "#dcfce7"), ("#1d4ed8", "#dbeafe"), ("#6d28d9", "#ede9fe"),
    ("#b45309", "#fef3c7"), ("#0369a1", "#e0f2fe"), ("#047857", "#ecfdf5"),
    ("#9f1239", "#fff1f2"), ("#374151", "#f9fafb"),
]


# ── HTTP helper ───────────────────────────────────────────────────────────────

def fetch(api_base: str, path: str):
    url = f"{api_base}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  WARN: {url} → {e}", file=sys.stderr)
        return None


# ── Data loading ──────────────────────────────────────────────────────────────

def load_data(api_base: str, product_id: str, version_filter: str | None = None) -> dict:
    print(f"Loading product-dev report data for {product_id}…")

    dashboard_all = fetch(api_base, f"/reports/dashboard?product_id={product_id}")
    if not dashboard_all:
        sys.exit("Could not reach API — is the server running?")

    # The dashboard response includes a global by-version table, so filter it
    # explicitly to avoid pulling versions that belong to other products.
    versions = sorted({
        v["version"]
        for v in dashboard_all.get("by_version", [])
        if v.get("product_id") == product_id
    })
    if not versions:
        sys.exit("No utilization data found for this product.")
    if version_filter:
        if version_filter not in versions:
            available = ", ".join(versions)
            sys.exit(f"Version '{version_filter}' not found for product '{product_id}'. Available versions: {available}")
        versions = [version_filter]
    print(f"  Versions with data: {versions}")

    version_data: dict = {}
    for v in versions:
        print(f"  Fetching data for v{v}…")
        version_data[v] = {
            "dashboard":   fetch(api_base, f"/reports/dashboard?product_id={product_id}&version={v}"),
            "summary":     fetch(api_base, f"/reports/features/summary?product_id={product_id}&version={v}") or [],
            "coverage":    fetch(api_base, f"/reports/catalog/coverage?product_id={product_id}&version={v}") or [],
            "heatmap":     fetch(api_base, f"/reports/features/heatmap?product_id={product_id}&version={v}") or {},
            "by_category": fetch(api_base, f"/reports/features/by-category?product_id={product_id}&version={v}") or [],
        }

    return {
        "dashboard_all": dashboard_all,
        "versions":      versions,
        "version_data":  version_data,
        "selected_version": version_filter,
    }


# ── Computation helpers ────────────────────────────────────────────────────────

def _version_feature_states(version_data: dict) -> tuple[dict, dict, dict]:
    """
    Returns:
      version_customers    : version -> total unique customer count
      version_feat_enabled : version -> {feature_code -> set(customer_id)}
      version_feat_used    : version -> {feature_code -> set(customer_id)}
    """
    v_customers: dict = {}
    v_feat_enabled: dict = {}
    v_feat_used: dict = {}
    for v, vd in version_data.items():
        hm = vd["heatmap"]
        v_customers[v] = len(hm.get("customers", []))
        v_feat_enabled[v] = defaultdict(set)
        v_feat_used[v] = defaultdict(set)
        for row in hm.get("matrix", []):
            if row.get("is_enabled"):
                v_feat_enabled[v][row["feature_code"]].add(row["customer_id"])
            if row.get("total_count", 0) > 0:
                v_feat_used[v][row["feature_code"]].add(row["customer_id"])
    return v_customers, v_feat_enabled, v_feat_used


def _all_product_customers(version_data: dict) -> set[str]:
    """Return the unique customers that appear in this product's heatmaps."""
    customers: set[str] = set()
    for vd in version_data.values():
        for customer in vd["heatmap"].get("customers", []):
            if customer.get("id"):
                customers.add(customer["id"])
    return customers


def _feature_info_map(version_data: dict) -> dict:
    """Build feature_code -> {name, category, tier, status} from coverage data."""
    info: dict = {}
    for vd in version_data.values():
        for f in vd["coverage"]:
            code = f["feature_code"]
            if code not in info:
                info[code] = {
                    "name":     f["feature_name"],
                    "category": f["category"],
                    "tier":     f.get("tier") or "",
                    "status":   f.get("status") or "",
                }
    return info


def _suggested_action(feature: dict) -> str:
    tier   = (feature.get("tier")   or "").lower()
    status = (feature.get("status") or "").lower()
    if status in ("experimental", "beta"):
        return "Publish case studies + guided setup before GA push"
    if tier == "enterprise":
        return "Re-evaluate positioning; build quickstart / solution template"
    if tier == "premium":
        return "Improve documentation and add a setup wizard"
    return "Review docs clarity; promote in release notes and in-product tips"


# ── Section computations ──────────────────────────────────────────────────────

def compute_adoption(data: dict) -> list:
    """Section 1: cross-version adoption % per feature, sorted high→low."""
    version_data   = data["version_data"]
    versions       = data["versions"]
    total_customers = len(_all_product_customers(version_data)) or 1

    v_customers, _, v_feat_used = _version_feature_states(version_data)
    feat_info = _feature_info_map(version_data)

    # Unique customers per feature across all versions
    feature_all_customers: dict = defaultdict(set)
    for v_fc in v_feat_used.values():
        for code, custs in v_fc.items():
            feature_all_customers[code].update(custs)

    def _trend_pp(code: str) -> int:
        if len(versions) < 2:
            return 0
        prev_v, curr_v = versions[-2], versions[-1]
        prev_n = len(v_feat_used[prev_v].get(code, set()))
        curr_n = len(v_feat_used[curr_v].get(code, set()))
        prev_t = v_customers.get(prev_v, 1) or 1
        curr_t = v_customers.get(curr_v, 1) or 1
        return round(curr_n / curr_t * 100) - round(prev_n / prev_t * 100)

    result = []
    for code, info in feat_info.items():
        cust_count = len(feature_all_customers.get(code, set()))
        pct        = round(cust_count / total_customers * 100)
        result.append({
            "code":            code,
            "name":            info["name"],
            "cat":             info["category"],
            "ft":              info["tier"],
            "status":          info.get("status", ""),
            "pct":             pct,
            "customers":       cust_count,
            "trend_pp":        _trend_pp(code),
        })

    return sorted(result, key=lambda x: (-x["pct"], x["name"]))


def compute_depth(data: dict, adoption: list) -> list:
    """
    Section 2: actual enabled % vs active-usage % per feature.
    Enabled means the feature appeared in the utilization report.
    Active use means the reported total_count is greater than zero.
    """
    version_data = data["version_data"]
    total_customers = len(_all_product_customers(version_data)) or 1
    _, v_feat_enabled, v_feat_used = _version_feature_states(version_data)

    enabled_by_feature: dict = defaultdict(set)
    used_by_feature: dict = defaultdict(set)
    for version, feature_map in v_feat_enabled.items():
        for code, customers in feature_map.items():
            enabled_by_feature[code].update(customers)
    for version, feature_map in v_feat_used.items():
        for code, customers in feature_map.items():
            used_by_feature[code].update(customers)

    rows = []
    for f in adoption:
        enabled_count = len(enabled_by_feature.get(f["code"], set()))
        used_count = len(used_by_feature.get(f["code"], set()))
        if enabled_count == 0 and used_count == 0:
            continue
        enabled_pct = round(enabled_count / total_customers * 100)
        active_pct  = round(used_count / total_customers * 100)
        gap         = enabled_pct - active_pct
        rows.append({
            "code":        f["code"],
            "name":        f["name"],
            "enabled_pct": enabled_pct,
            "used_pct":    active_pct,
            "gap_pct":     gap,
            "enabled_count": enabled_count,
            "used_count": used_count,
        })

    rows = sorted(rows, key=lambda x: (-x["gap_pct"], -x["enabled_pct"]))
    nonzero_rows = [r for r in rows if r["gap_pct"] > 0]
    if nonzero_rows:
        return nonzero_rows[:14]
    return rows[:14]


def compute_dropoff(data: dict, adoption: list) -> list:
    """
    Section 3: features whose adoption peak (across versions) exceeds their
    latest-version adoption by ≥10 percentage points.
    """
    version_data  = data["version_data"]
    versions      = data["versions"]
    if len(versions) < 2:
        return []

    v_customers, _, v_feat_used = _version_feature_states(version_data)
    feat_info = _feature_info_map(version_data)

    # Per-feature per-version adoption %
    feat_ver_pct: dict = defaultdict(dict)
    for v in versions:
        t = v_customers.get(v, 1) or 1
        for code, custs in v_feat_used[v].items():
            feat_ver_pct[code][v] = round(len(custs) / t * 100)

    latest_v = versions[-1]
    rows = []
    for code, ver_pcts in feat_ver_pct.items():
        if len(ver_pcts) < 2:
            continue
        peak    = max(ver_pcts.values())
        current = ver_pcts.get(latest_v, 0)
        if peak <= 0 or (peak - current) < 8:
            continue
        drop_rate  = round((peak - current) / peak * 100)
        peak_v     = max(ver_pcts, key=ver_pcts.get)
        info       = feat_info.get(code, {})
        rows.append({
            "code":        code,
            "name":        info.get("name", code),
            "cat":         info.get("category", ""),
            "init_pct":    peak,
            "curr_pct":    current,
            "drop_rate":   drop_rate,
            "peak_ver":    peak_v,
            "latest_ver":  latest_v,
        })

    return sorted(rows, key=lambda x: -x["drop_rate"])


def compute_version_matrix(data: dict) -> tuple[list, list]:
    """
    Section 4: features × versions adoption matrix.
    Returns (versions_list, rows) where each row has {name, code, v_pcts: {v: pct}}.
    Limits to features that appear in at least one version and have non-zero adoption.
    """
    version_data  = data["version_data"]
    versions      = data["versions"]
    v_customers, _, v_feat_used = _version_feature_states(version_data)
    feat_info = _feature_info_map(version_data)

    # All feature codes that appear in any version's heatmap
    all_codes = set()
    for v_fc in v_feat_used.values():
        all_codes.update(v_fc.keys())

    rows = []
    for code in all_codes:
        v_pcts = {}
        for v in versions:
            t = v_customers.get(v, 1) or 1
            n = len(v_feat_used[v].get(code, set()))
            v_pcts[v] = round(n / t * 100)

        # Only include features with at least some adoption in some version
        if max(v_pcts.values(), default=0) == 0:
            continue

        info = feat_info.get(code, {})
        rows.append({
            "code":   code,
            "name":   info.get("name", code),
            "v_pcts": v_pcts,
        })

    # Sort by latest-version adoption descending, then by name
    latest_v = versions[-1]
    rows.sort(key=lambda r: (-r["v_pcts"].get(latest_v, 0), r["name"]))
    return versions, rows


def compute_categories(adoption: list) -> list:
    """Section 5: per-taxonomy-category adoption summary."""
    cat_pcts: dict = defaultdict(list)
    for f in adoption:
        cat_pcts[f["cat"]].append(f["pct"])

    rows = []
    for cat, pcts in cat_pcts.items():
        avg     = round(sum(pcts) / len(pcts))
        nonzero = sum(1 for p in pcts if p > 0)
        rows.append({
            "name":    cat,
            "feats":   len(pcts),
            "avg":     avg,
            "nonzero": nonzero,
        })

    return sorted(rows, key=lambda x: -x["avg"])


def compute_zero_usage(data: dict) -> list:
    """Section 6: catalog features with 0 adoption across all versions."""
    version_data = data["version_data"]
    versions     = data["versions"]

    _, _, v_feat_used = _version_feature_states(version_data)
    all_used_codes = set()
    for v_fc in v_feat_used.values():
        all_used_codes.update(v_fc.keys())

    coverage_by_code: dict = {}
    for version in versions:
        for feature in version_data[version]["coverage"]:
            code = feature["feature_code"]
            coverage_by_code.setdefault(code, {**feature, "catalog_version": version})

    rows = []
    for f in coverage_by_code.values():
        if f["feature_code"] in all_used_codes:
            continue
        rows.append({
            "code":    f["feature_code"],
            "name":    f["feature_name"],
            "cat":     f["category"],
            "tier":    f.get("tier") or "",
            "status":  f.get("status") or "",
            "version": f["catalog_version"],
            "action":  _suggested_action(f),
        })

    return sorted(rows, key=lambda x: (x["tier"], x["name"]))


def compute_combos(data: dict) -> list:
    """
    Section 7: adoption % for predefined feature combinations.
    A customer matches a combo if they have at least one feature matching
    each pattern in the combo's pattern list (min_match satisfied).
    """
    version_data    = data["version_data"]
    total_customers = len(_all_product_customers(version_data)) or 1

    # All features per customer (union across all versions)
    customer_features: dict = defaultdict(set)
    for vd in version_data.values():
        for row in vd["heatmap"].get("matrix", []):
            if row.get("total_count", 0) > 0:
                customer_features[row["customer_id"]].add(row["feature_code"])

    def matches_pattern(feat_set: set, patterns: list, min_match: int) -> bool:
        matched = sum(
            1 for p in patterns
            if any(f == p or f.startswith(p) for f in feat_set)
        )
        return matched >= min_match

    result = []
    for i, combo in enumerate(PREDEFINED_COMBOS):
        count = sum(
            1 for feats in customer_features.values()
            if matches_pattern(feats, combo["patterns"], combo["min_match"])
        )
        pct  = round(count / total_customers * 100)
        col, bg = COMBO_COLORS[i % len(COMBO_COLORS)]
        result.append({
            "label": combo["label"],
            "desc":  combo["desc"],
            "pct":   pct,
            "count": count,
            "color": col,
            "bg":    bg,
        })

    return sorted(result, key=lambda x: -x["pct"])


def compute_feature_customers_map(data: dict) -> dict:
    """
    Build feature_code → [{id, name, tier, total_count}] sorted by usage desc.
    Used by the customer-detail expand in Section 1 and the explorer in Section 8.
    """
    version_data = data["version_data"]
    feat_cust: dict = {}

    for vd in version_data.values():
        hm        = vd["heatmap"]
        cust_map  = {c["id"]: c for c in hm.get("customers", [])}
        for row in hm.get("matrix", []):
            if row.get("total_count", 0) <= 0:
                continue
            cid  = row["customer_id"]
            code = row["feature_code"]
            ci   = cust_map.get(cid, {"id": cid, "name": cid, "tier": ""})
            if code not in feat_cust:
                feat_cust[code] = {}
            if cid not in feat_cust[code]:
                feat_cust[code][cid] = {
                    "id":          cid,
                    "name":        ci.get("name", cid),
                    "tier":        ci.get("tier", ""),
                    "total_count": 0,
                }
            feat_cust[code][cid]["total_count"] += row["total_count"]

    return {
        code: sorted(custs.values(), key=lambda x: -x["total_count"])
        for code, custs in feat_cust.items()
    }


def compute_feature_customers_map_by_version(data: dict) -> dict:
    """
    Build version -> feature_code -> [{id, name, tier, total_count}] so the UI
    stays accurate when the version filter changes.
    """
    version_maps: dict = {}

    for version, vd in data["version_data"].items():
        feat_cust: dict = {}
        hm       = vd["heatmap"]
        cust_map = {c["id"]: c for c in hm.get("customers", [])}
        for row in hm.get("matrix", []):
            if row.get("total_count", 0) <= 0:
                continue
            cid  = row["customer_id"]
            code = row["feature_code"]
            ci   = cust_map.get(cid, {"id": cid, "name": cid, "tier": ""})
            feat_cust.setdefault(code, {})
            feat_cust[code].setdefault(cid, {
                "id": cid,
                "name": ci.get("name", cid),
                "tier": ci.get("tier", ""),
                "total_count": 0,
            })
            feat_cust[code][cid]["total_count"] += row["total_count"]

        version_maps[version] = {
            code: sorted(custs.values(), key=lambda x: -x["total_count"])
            for code, custs in feat_cust.items()
        }

    return version_maps


def compute_customer_features_map(data: dict) -> dict:
    """
    Build customer_id → {name, tier, features: [{code, name, cat, total_count}]}
    sorted by usage desc. Used by the explorer dropdown in Section 8.
    """
    version_data = data["version_data"]
    feat_info    = _feature_info_map(version_data)
    cust_data: dict = {}

    for vd in version_data.values():
        hm       = vd["heatmap"]
        cust_map = {c["id"]: c for c in hm.get("customers", [])}
        for row in hm.get("matrix", []):
            if row.get("total_count", 0) <= 0:
                continue
            cid  = row["customer_id"]
            code = row["feature_code"]
            ci   = cust_map.get(cid, {})
            if cid not in cust_data:
                cust_data[cid] = {
                    "name":     ci.get("name", cid),
                    "tier":     ci.get("tier", ""),
                    "features": {},
                }
            fi = feat_info.get(code, {})
            if code not in cust_data[cid]["features"]:
                cust_data[cid]["features"][code] = {
                    "code":        code,
                    "name":        fi.get("name", code),
                    "cat":         fi.get("category", ""),
                    "total_count": 0,
                }
            cust_data[cid]["features"][code]["total_count"] += row["total_count"]

    return {
        cid: {
            "name":     cd["name"],
            "tier":     cd["tier"],
            "features": sorted(cd["features"].values(), key=lambda x: -x["total_count"]),
        }
        for cid, cd in cust_data.items()
    }


def compute_customer_features_map_by_version(data: dict) -> dict:
    """
    Build version -> customer_id -> {name, tier, features:[...]} for the
    version-aware customer explorer.
    """
    version_maps: dict = {}
    feat_info = _feature_info_map(data["version_data"])

    for version, vd in data["version_data"].items():
        cust_data: dict = {}
        hm       = vd["heatmap"]
        cust_map = {c["id"]: c for c in hm.get("customers", [])}
        for row in hm.get("matrix", []):
            if row.get("total_count", 0) <= 0:
                continue
            cid  = row["customer_id"]
            code = row["feature_code"]
            ci   = cust_map.get(cid, {})
            cust_data.setdefault(cid, {
                "name": ci.get("name", cid),
                "tier": ci.get("tier", ""),
                "features": {},
            })
            fi = feat_info.get(code, {})
            cust_data[cid]["features"].setdefault(code, {
                "code": code,
                "name": fi.get("name", code),
                "cat": fi.get("category", ""),
                "total_count": 0,
            })
            cust_data[cid]["features"][code]["total_count"] += row["total_count"]

        version_maps[version] = {
            cid: {
                "name": cd["name"],
                "tier": cd["tier"],
                "features": sorted(cd["features"].values(), key=lambda x: -x["total_count"]),
            }
            for cid, cd in cust_data.items()
        }

    return version_maps


def compute_version_customers(data: dict) -> dict:
    """Return {version: total_customer_count} from heatmap data."""
    return {
        v: len(vd["heatmap"].get("customers", []))
        for v, vd in data["version_data"].items()
    }


# ── HTML generation ───────────────────────────────────────────────────────────

def _scorecard(data: dict, adoption: list, zero: list) -> tuple:
    """Return (total_customers, high, mid, low, zero_count) for the scorecard."""
    total      = len(_all_product_customers(data["version_data"]))
    high_cnt   = sum(1 for f in adoption if f["pct"] > 70)
    mid_cnt    = sum(1 for f in adoption if 30 <= f["pct"] <= 70)
    low_cnt    = sum(1 for f in adoption if 0 < f["pct"] < 30)
    zero_cnt   = len(zero)
    return total, high_cnt, mid_cnt, low_cnt, zero_cnt


def build_html(data: dict, product_id: str) -> str:
    adoption  = compute_adoption(data)
    depth     = compute_depth(data, adoption)
    dropoff   = compute_dropoff(data, adoption)
    vers, ver_matrix = compute_version_matrix(data)
    categories = compute_categories(adoption)
    zero      = compute_zero_usage(data)
    combos    = compute_combos(data)

    total_customers, high_cnt, mid_cnt, low_cnt, zero_cnt = _scorecard(data, adoption, zero)
    total_features  = len(adoption)
    versions_label  = " · ".join(f"v{v}" for v in data["versions"])
    generated_at    = datetime.now().strftime("%Y-%m-%d %H:%M")

    feat_customers  = compute_feature_customers_map(data)
    feat_customers_by_version = compute_feature_customers_map_by_version(data)
    cust_features   = compute_customer_features_map(data)
    cust_features_by_version = compute_customer_features_map_by_version(data)
    ver_total_custs = compute_version_customers(data)
    selected_version = data.get("selected_version")
    version_mode = selected_version is not None
    title_suffix = f" — v{selected_version}" if version_mode else ""
    view_tag = f"VERSION-SPECIFIC VIEW · v{selected_version}" if version_mode else "PRODUCT DEVELOPMENT VIEW"
    objective_note = (
        f"Focused release view for v{selected_version}"
        if version_mode else
        "Objective: what to build, improve, or deprecate"
    )
    version_scope_note = (
        f'<div class="insight-box" style="margin-top:0;margin-bottom:1.5rem"><strong>Version focus:</strong> This report is scoped to <strong>v{selected_version}</strong>, so adoption, enabled-vs-used, categories, zero-adoption features, combinations, and explorer results all reflect that release only.</div>'
        if version_mode else
        ""
    )
    version_filter_html = (
        f"""<div class="ver-filter-bar" id="versionBar">
  <span style="font-size:.8rem;color:#6c757d;font-weight:600;white-space:nowrap">📦 Version:</span>
  <button class="ver-btn active" onclick="setVersion(this,'all')">All Versions</button>
  {ver_buttons_html}
  <span id="verFilterNote" style="font-size:.76rem;color:#9ca3af;margin-left:.25rem">Showing combined view across all deployed versions</span>
</div>"""
        if not version_mode else ""
    )

    # Serialise computed data as JSON for embedding in the HTML
    features_js        = json.dumps(adoption,        ensure_ascii=False)
    depth_js           = json.dumps(depth,           ensure_ascii=False)
    dropoff_js         = json.dumps(dropoff,         ensure_ascii=False)
    ver_matrix_js      = json.dumps(ver_matrix,      ensure_ascii=False)
    versions_js        = json.dumps(vers,            ensure_ascii=False)
    categories_js      = json.dumps(categories,      ensure_ascii=False)
    zero_js            = json.dumps(zero,            ensure_ascii=False)
    combos_js          = json.dumps(combos,          ensure_ascii=False)
    feat_customers_js  = json.dumps(feat_customers,  ensure_ascii=False)
    feat_customers_by_version_js = json.dumps(feat_customers_by_version, ensure_ascii=False)
    cust_features_js   = json.dumps(cust_features,   ensure_ascii=False)
    cust_features_by_version_js = json.dumps(cust_features_by_version, ensure_ascii=False)
    ver_total_custs_js = json.dumps(ver_total_custs, ensure_ascii=False)

    ver_buttons_html = "\n  ".join(
        f'<button class="ver-btn" onclick="setVersion(this,\'{v}\')">v{v}</button>'
        for v in vers
    )

    # Keep the adoption chart readable without creating excessive vertical gaps
    # before the table and the next section.
    adoption_chart_height = min(920, max(420, total_features * 10))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Product Development Dashboard — {product_id}{title_suffix}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --brand-dark:  #2a1a4a;
      --brand-mid:   #4a2d7a;
      --high-text:   #166534; --high-bg: #dcfce7; --high-border: #86efac;
      --mid-text:    #92400e; --mid-bg:  #fef3c7; --mid-border:  #fcd34d;
      --low-text:    #991b1b; --low-bg:  #fee2e2; --low-border:  #fca5a5;
      --zero-text:   #374151; --zero-bg: #f3f4f6; --zero-border: #d1d5db;
    }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f4f6f9; color: #1f2937; }}
    .page-header {{
      background: linear-gradient(135deg, var(--brand-dark) 0%, var(--brand-mid) 100%);
      color: white; padding: 2.5rem 0 2rem;
    }}
    .page-header .subtitle {{ opacity: .72; font-size: .92rem; }}
    .tag-pill {{ background: rgba(255,255,255,.15); border-radius: 6px; padding: .3rem .75rem; font-size: .75rem; letter-spacing: .05em; }}
    .stat-card {{ background: white; border-radius: 12px; padding: 1.2rem 1.4rem; box-shadow: 0 1px 4px rgba(0,0,0,.07); height: 100%; }}
    .stat-card .value {{ font-size: 2rem; font-weight: 700; line-height: 1.1; }}
    .stat-card .label {{ color: #6c757d; font-size: .73rem; text-transform: uppercase; letter-spacing: .05em; margin-top: .3rem; }}
    .stat-card .sub   {{ font-size: .77rem; color: #6c757d; margin-top: .35rem; }}
    .section-card {{ background: white; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.07); margin-bottom: 1.75rem; }}
    .section-card .card-header {{ background: none; border-bottom: 1px solid #e9ecef; padding: 1rem 1.4rem; font-weight: 600; font-size: .95rem; display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }}
    .section-card .card-body {{ padding: 1.4rem; }}
    table thead th {{ background: #f8f9fa; font-size: .73rem; text-transform: uppercase; letter-spacing: .04em; color: #6c757d; border-bottom: 2px solid #dee2e6; white-space: nowrap; }}
    table tbody td {{ vertical-align: middle; }}
    code {{ background: #f0f4ff; color: var(--brand-mid); padding: .1em .35em; border-radius: 4px; font-size: .78em; }}
    .tier-high  {{ background: var(--high-bg); color: var(--high-text); border: 1px solid var(--high-border); padding: .2rem .55rem; border-radius: 20px; font-size: .74rem; font-weight: 600; white-space: nowrap; }}
    .tier-mid   {{ background: var(--mid-bg);  color: var(--mid-text);  border: 1px solid var(--mid-border);  padding: .2rem .55rem; border-radius: 20px; font-size: .74rem; font-weight: 600; white-space: nowrap; }}
    .tier-low   {{ background: var(--low-bg);  color: var(--low-text);  border: 1px solid var(--low-border);  padding: .2rem .55rem; border-radius: 20px; font-size: .74rem; font-weight: 600; white-space: nowrap; }}
    .tier-zero  {{ background: var(--zero-bg); color: var(--zero-text); border: 1px solid var(--zero-border); padding: .2rem .55rem; border-radius: 20px; font-size: .74rem; font-weight: 600; white-space: nowrap; }}
    .ft-core       {{ background: #e5e7eb; color: #374151; border-radius: 4px; padding: .1rem .4rem; font-size: .7rem; }}
    .ft-premium    {{ background: #fef3c7; color: #92400e; border-radius: 4px; padding: .1rem .4rem; font-size: .7rem; }}
    .ft-enterprise {{ background: #fee2e2; color: #991b1b; border-radius: 4px; padding: .1rem .4rem; font-size: .7rem; }}
    .pbar {{ background: #e5e7eb; border-radius: 3px; height: 6px; overflow: hidden; }}
    .pbar-fill {{ height: 100%; border-radius: 3px; }}
    .insight-box {{ background: #f0f4ff; border-left: 3px solid var(--brand-mid); border-radius: 0 8px 8px 0; padding: .7rem 1rem; font-size: .82rem; color: #374151; margin-top: 1rem; }}
    .insight-box strong {{ color: var(--brand-mid); }}
    .vm-cell {{ border-radius: 5px; padding: .25rem .4rem; font-weight: 600; min-width: 46px; display: inline-block; font-size: .78rem; }}
    .ver-matrix td, .ver-matrix th {{ padding: .35rem .5rem; text-align: center; }}
    .ver-matrix th {{ background: #f8f9fa; font-size: .73rem; }}
    .combo-row {{ display: flex; align-items: center; gap: .75rem; padding: .7rem 1rem; border-bottom: 1px solid #f3f4f6; }}
    .combo-row:last-child {{ border-bottom: none; }}
    .combo-pct {{ font-size: 1.25rem; font-weight: 700; min-width: 52px; }}
    .filter-btn {{ font-size: .78rem; padding: .3rem .75rem; border-radius: 20px; border: 1px solid #dee2e6; background: white; color: #6c757d; cursor: pointer; transition: all .15s; }}
    .filter-btn.active, .filter-btn:hover {{ border-color: var(--brand-mid); color: var(--brand-mid); background: #f0f4ff; }}
    .filter-btn.f-high.active  {{ border-color: var(--high-border); color: var(--high-text); background: var(--high-bg); }}
    .filter-btn.f-mid.active   {{ border-color: var(--mid-border);  color: var(--mid-text);  background: var(--mid-bg); }}
    .filter-btn.f-low.active   {{ border-color: var(--low-border);  color: var(--low-text);  background: var(--low-bg); }}
    .filter-btn.f-zero.active  {{ border-color: var(--zero-border); color: var(--zero-text); background: var(--zero-bg); }}
    tr.drop-critical td {{ background: #fff5f5; }}
    tr.drop-warn td     {{ background: #fffbeb; }}
    .footer {{ color: #9ca3af; font-size: .78rem; padding: 1.5rem 0 2rem; text-align: center; }}
    .ver-filter-bar {{ background: white; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.07); padding: .65rem 1rem; display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; margin-bottom: 1.5rem; }}
    .ver-btn {{ font-size: .8rem; padding: .3rem .9rem; border-radius: 20px; border: 1px solid #dee2e6; background: white; color: #6c757d; cursor: pointer; transition: all .15s; font-weight: 500; }}
    .ver-btn.active {{ border-color: var(--brand-mid); color: var(--brand-mid); background: #f0f4ff; font-weight: 600; }}
    .cust-expand-btn {{ background: none; border: none; padding: 0 0 0 .3rem; font-size: .71rem; color: #6366f1; cursor: pointer; white-space: nowrap; }}
    .cust-expand-btn:hover {{ text-decoration: underline; }}
    .cust-names-row {{ background: #f8f9ff !important; }}
    .cust-names-list {{ display: flex; flex-wrap: wrap; gap: .35rem; padding: .5rem .75rem; }}
    .cust-chip {{ background: #e0e7ff; color: #3730a3; border-radius: 12px; padding: .15rem .55rem; font-size: .71rem; font-weight: 500; }}
    .status-stable       {{ background: #dcfce7; color: #166534; border-radius: 4px; padding: .1rem .45rem; font-size: .7rem; font-weight: 600; }}
    .status-experimental {{ background: #fef9c3; color: #854d0e; border-radius: 4px; padding: .1rem .45rem; font-size: .7rem; font-weight: 600; }}
    .status-deprecated   {{ background: #fee2e2; color: #991b1b; border-radius: 4px; padding: .1rem .45rem; font-size: .7rem; font-weight: 600; text-decoration: line-through; }}
    .status-unknown      {{ background: #f3f4f6; color: #6b7280; border-radius: 4px; padding: .1rem .45rem; font-size: .7rem; }}
    .status-beta         {{ background: #e0f2fe; color: #0369a1; border-radius: 4px; padding: .1rem .45rem; font-size: .7rem; font-weight: 600; }}
  </style>
</head>
<body>

<!-- ─── HEADER ─────────────────────────────────────────────────────────────── -->
<div class="page-header">
  <div class="container">
    <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
      <span class="tag-pill" style="letter-spacing:.08em">{view_tag}</span>
      <span class="tag-pill">{product_id}</span>
      <span class="tag-pill">{'v' + selected_version if version_mode else versions_label}</span>
    </div>
    <h1 class="mb-1" style="font-size:1.85rem;font-weight:700">Feature Adoption &amp; Usage Intelligence{title_suffix}</h1>
    <div class="subtitle">
      Generated {generated_at}
      &nbsp;·&nbsp; {total_customers} customers
      &nbsp;·&nbsp; {total_features} features tracked
      &nbsp;·&nbsp; {objective_note}
    </div>
  </div>
</div>

<div class="container py-4">

<!-- ─── VERSION FILTER ────────────────────────────────────────────────────── -->
{version_scope_note}
{version_filter_html}

<!-- ─── SCORECARD ──────────────────────────────────────────────────────────── -->
<div class="row g-3 mb-4">
  <div class="col-6 col-md-3 col-lg">
    <div class="stat-card">
      <div class="value text-primary" id="sc-customers">{total_customers}</div>
      <div class="label">Customers</div>
      <div class="sub" id="sc-ver-label">{versions_label}</div>
    </div>
  </div>
  <div class="col-6 col-md-3 col-lg">
    <div class="stat-card">
      <div class="value" style="color:#166534" id="sc-high">{high_cnt}</div>
      <div class="label">High Adoption</div>
      <div class="sub">&gt;70% customer reach</div>
    </div>
  </div>
  <div class="col-6 col-md-3 col-lg">
    <div class="stat-card">
      <div class="value" style="color:#92400e" id="sc-mid">{mid_cnt}</div>
      <div class="label">Medium Adoption</div>
      <div class="sub">30–70% customer reach</div>
    </div>
  </div>
  <div class="col-6 col-md-3 col-lg">
    <div class="stat-card">
      <div class="value" style="color:#991b1b" id="sc-low">{low_cnt}</div>
      <div class="label">Low Adoption</div>
      <div class="sub">&lt;30% customer reach</div>
    </div>
  </div>
  <div class="col-6 col-md-3 col-lg">
    <div class="stat-card">
      <div class="value" style="color:#6b7280" id="sc-zero">{zero_cnt}</div>
      <div class="label">Zero Adoption</div>
      <div class="sub">0% — no customer using</div>
    </div>
  </div>
  <div class="col-12 col-md-6 col-lg-4">
    <div class="section-card h-100" style="margin-bottom:0">
      <div class="card-header" style="padding:.65rem 1rem;font-size:.82rem">Adoption Tier Distribution</div>
      <div class="card-body" style="padding:.8rem 1rem">
        <div style="position:relative;height:130px"><canvas id="donutChart"></canvas></div>
      </div>
    </div>
  </div>
</div>


<!-- ─── SECTION 1: FEATURE ADOPTION OVERVIEW ──────────────────────────────── -->
<div class="section-card" id="sec1">
  <div class="card-header">
    📊 Section 1 — Feature Adoption Overview
    <span class="text-muted fw-normal" style="font-size:.8rem">— % of customers using each feature, traffic-light tiered</span>
  </div>
  <div class="card-body">
    <div class="d-flex align-items-center gap-2 mb-3 flex-wrap">
      <span style="font-size:.8rem;color:#6c757d">Filter:</span>
      <button class="filter-btn active" id="filterAll" onclick="filterTable(this,'all')">All ({total_features})</button>
      <button class="filter-btn f-high"  onclick="filterTable(this,'high')">🟢 High &gt;70%</button>
      <button class="filter-btn f-mid"   onclick="filterTable(this,'mid')">🟡 Medium 30–70%</button>
      <button class="filter-btn f-low"   onclick="filterTable(this,'low')">🔴 Low &lt;30%</button>
      <button class="filter-btn f-zero"  onclick="filterTable(this,'zero')">⬜ Zero 0%</button>
    </div>
    <div style="position:relative;height:{adoption_chart_height}px;margin-bottom:1.5rem"><canvas id="adoptionChart"></canvas></div>
    <div class="insight-box" style="margin-top:0;margin-bottom:1rem;background:#f8f9ff">
      <strong>How to read the table below:</strong>
      Customer Breadth shows how many customers use a feature out of the total customers in the current view, for example 4/10.
      Trend shows whether adoption went up or down between the latest two product versions by comparing adoption percentages, not raw event counts.
      Example: if a feature was used by 2 of 10 customers in v7.2.0 (20%) and 5 of 10 customers in v7.3.0 (50%), the trend is +30 percentage points.
      Feature Status is the lifecycle state from the catalog, such as stable, beta, experimental, or deprecated.
      Adoption is the traffic-light label based on customer reach: High &gt; 70%, Medium 30–70%, Low 1–29%, Zero = 0%.
    </div>
    <div style="overflow-x:auto">
      <table class="table table-sm table-hover mb-0">
        <thead>
          <tr>
            <th class="ps-3" style="width:24px">#</th>
            <th>Feature</th><th>Category</th><th>Tier</th>
            <th class="text-end" style="min-width:70px">Adopt %</th>
            <th style="min-width:145px">Customer Breadth</th>
            <th class="text-center" style="min-width:90px">Trend</th>
            <th class="text-center">Feature Status</th>
            <th class="text-center">Adoption</th>
          </tr>
        </thead>
        <tbody id="adoptionTbody"></tbody>
      </table>
    </div>
    <div class="insight-box">
      <strong>Decisions Enabled:</strong>
      Invest more in 🟢 high-adoption + growing features.
      Promote or simplify 🟡 medium-adoption features.
      Investigate or deprecate 🔴 low / ⬜ zero-adoption features.
    </div>
  </div>
</div>


<!-- ─── SECTION 2: USAGE DEPTH ─────────────────────────────────────────────── -->
<div class="section-card" id="sec2">
  <div class="card-header">
    🧠 Section 2 — Feature Usage Depth (Enabled vs Actively Used)
    <span class="text-muted fw-normal" style="font-size:.8rem">— enabled comes from feature presence in reports; active use comes from non-zero usage</span>
  </div>
  <div class="card-body">
    <div style="position:relative;height:380px;margin-bottom:1.5rem"><canvas id="depthChart"></canvas></div>
    <div class="insight-box" style="margin-top:0;margin-bottom:1rem;background:#f8f9ff">
      <strong>How this is calculated:</strong>
      Enabled % counts customers whose utilization report listed the feature under <code>features</code>.
      Actively Used % counts customers where that same feature had <code>total_count &gt; 0</code>.
      The gap shows customers who appear to have enabled the feature but did not generate usage during the reporting period.
    </div>
    <div class="text-muted mb-3" style="font-size:.8rem">
      This section focuses on features with a non-zero enablement gap so the report highlights underused enabled capabilities instead of listing many zero-gap rows.
    </div>
    <div style="overflow-x:auto">
      <table class="table table-sm table-hover mb-0">
        <thead>
          <tr>
            <th class="ps-3">Feature</th>
            <th class="text-center" style="min-width:90px">Enabled %</th>
            <th class="text-center" style="min-width:90px">Actively Used %</th>
            <th style="min-width:140px">Enablement Gap</th>
          </tr>
        </thead>
        <tbody id="depthTbody"></tbody>
      </table>
    </div>
    <div class="insight-box">
      <strong>Decisions Enabled:</strong>
      Features with large enablement gaps signal capabilities that customers turned on
      but are not yet using in practice. Prioritise onboarding improvements,
      discoverability, and rollout guidance for gaps above 15 percentage points.
    </div>
  </div>
</div>


<!-- ─── SECTION 3: DROP-OFF / ABANDONMENT ────────────────────────────────── -->
<div class="section-card" id="sec3">
  <div class="card-header">
    ⚠️ Section 3 — Feature Drop-Off &amp; Abandonment
    <span class="text-muted fw-normal" style="font-size:.8rem">— features whose adoption declined across product versions</span>
  </div>
  <div class="card-body p-0" id="dropoffBody">
    <table class="table table-sm table-hover mb-0" id="dropoffTable" style="display:none">
      <thead>
        <tr>
          <th class="ps-3">Feature</th>
          <th class="text-center">Peak Adopt</th>
          <th class="text-center">Latest Adopt</th>
          <th style="min-width:140px">Drop Rate</th>
          <th>Risk</th>
          <th>Peak Version</th>
        </tr>
      </thead>
      <tbody id="dropoffTbody"></tbody>
    </table>
    <div id="dropoffEmpty" class="p-4 text-muted" style="display:none">
      No significant drop-off detected across the available versions.
    </div>
    <div class="px-3 pb-3">
      <div class="insight-box">
        <strong>Decisions Enabled:</strong>
        Features with critical drop-off are failing after onboarding — investigate
        complexity, integration overhead, and end-user friction. These are candidates
        for simplification sprints before being considered for deprecation.
      </div>
    </div>
  </div>
</div>


<!-- ─── SECTION 4: ADOPTION BY VERSION ───────────────────────────────────── -->
<div class="section-card" id="sec4">
  <div class="card-header">
    🌍 Section 4 — Adoption by Product Version
    <span class="text-muted fw-normal" style="font-size:.8rem">— per-version feature adoption comparison matrix</span>
  </div>
  <div class="card-body">
    <div class="d-flex align-items-center gap-3 mb-3 flex-wrap" style="font-size:.78rem;color:#6c757d">
      <span>Color scale:</span>
      <span style="display:inline-flex;align-items:center;gap:4px"><span style="width:14px;height:14px;background:#dcfce7;border:1px solid #86efac;border-radius:3px;display:inline-block"></span> &gt;70%</span>
      <span style="display:inline-flex;align-items:center;gap:4px"><span style="width:14px;height:14px;background:#fef3c7;border:1px solid #fcd34d;border-radius:3px;display:inline-block"></span> 30–70%</span>
      <span style="display:inline-flex;align-items:center;gap:4px"><span style="width:14px;height:14px;background:#fee2e2;border:1px solid #fca5a5;border-radius:3px;display:inline-block"></span> &lt;30%</span>
      <span style="display:inline-flex;align-items:center;gap:4px"><span style="width:14px;height:14px;background:#f3f4f6;border:1px solid #d1d5db;border-radius:3px;display:inline-block"></span> 0%</span>
    </div>
    <div style="overflow-x:auto">
      <table class="table table-sm mb-0 ver-matrix">
        <thead><tr id="verMatrixHead"></tr></thead>
        <tbody id="verMatrixBody"></tbody>
      </table>
    </div>
    <div class="insight-box">
      <strong>Decisions Enabled:</strong>
      Compare feature growth across releases to validate new-feature ROI and
      identify migration blockers. Declining features signal customers are
      moving away — investigate and decide whether to simplify or sunset.
    </div>
  </div>
</div>


<!-- ─── SECTION 5: CATEGORY-LEVEL INSIGHTS ───────────────────────────────── -->
<div class="section-card" id="sec5">
  <div class="card-header">
    🔍 Section 5 — Feature Usage by Category (Taxonomy-Based)
    <span class="text-muted fw-normal" style="font-size:.8rem">— aggregated avg adoption % per taxonomy category</span>
  </div>
  <div class="card-body">
    <div class="row g-3">
      <div class="col-md-7">
        <div style="position:relative;height:320px"><canvas id="categoryChart"></canvas></div>
      </div>
      <div class="col-md-5">
        <table class="table table-sm mb-0">
          <thead>
            <tr>
              <th class="ps-2">Category</th>
              <th class="text-center">Features</th>
              <th class="text-center">Avg Adoption</th>
              <th class="text-center">Active</th>
            </tr>
          </thead>
          <tbody id="categoryTbody"></tbody>
        </table>
      </div>
    </div>
    <div class="insight-box">
      <strong>Decisions Enabled:</strong>
      Spot under-invested product areas where adoption is low despite roadmap investment.
      Align the next planning cycle with real customer usage patterns rather than
      assumed demand.
    </div>
  </div>
</div>


<!-- ─── SECTION 6: ZERO-USAGE FEATURES ───────────────────────────────────── -->
<div class="section-card" id="sec6" style="border:1.5px solid #fca5a5">
  <div class="card-header" style="border-bottom-color:#fca5a5">
    🚨 Section 6 — Zero-Usage Features
    <span class="badge bg-danger ms-1" id="zeroCntBadge"></span>
    <span class="text-muted fw-normal" style="font-size:.8rem">— released but not used by any customer</span>
  </div>
  <div class="card-body p-0">
    <div id="zeroContent">
      <table class="table table-sm table-hover mb-0" id="zeroTable" style="display:none">
        <thead>
          <tr>
            <th class="ps-3">Feature Code</th>
            <th>Feature Name</th>
            <th>Category</th>
            <th>Tier</th>
            <th>Version</th>
            <th>Suggested Action</th>
          </tr>
        </thead>
        <tbody id="zeroTbody"></tbody>
      </table>
      <p id="zeroEmpty" class="p-4 text-muted mb-0" style="display:none">
        All catalog features have been used by at least one customer. 🎉
      </p>
    </div>
    <div class="px-3 pb-3">
      <div class="insight-box" style="border-left-color:#dc2626;background:#fff5f5">
        <strong style="color:#dc2626">Immediate candidates for review:</strong>
        Zero-adoption features represent shipped work with no customer value yet.
        Prioritise documentation, guided setup, or deprecation in the next sprint.
      </div>
    </div>
  </div>
</div>


<!-- ─── SECTION 7: FEATURE COMBINATIONS ──────────────────────────────────── -->
<div class="section-card" id="sec7">
  <div class="card-header">
    💡 Section 7 — Top Feature Combinations
    <span class="text-muted fw-normal" style="font-size:.8rem">— feature bundles used together (% of {total_customers} customers)</span>
  </div>
  <div class="card-body p-0" id="combosContainer"></div>
  <div class="px-3 pb-3">
    <div class="insight-box">
      <strong>Decisions Enabled:</strong>
      High-adoption combos are strong candidates for packaged solutions, quickstart
      templates, and solution briefs. Low-adoption combos with high product-team intent
      signal missing integration flows or poor discoverability.
    </div>
  </div>
</div>


<!-- ─── SECTION 8: FEATURE ↔ CUSTOMER EXPLORER ───────────────────────────── -->
<div class="section-card" id="sec8">
  <div class="card-header">
    🔎 Section 8 — Feature ↔ Customer Explorer
    <span class="text-muted fw-normal" style="font-size:.8rem">— identify who uses which features, and what a customer uses</span>
  </div>
  <div class="card-body">
    <div class="row g-4">
      <!-- Panel A: Feature → Customers -->
      <div class="col-md-6">
        <div class="p-3 rounded-3" style="background:#f8f9fa;height:100%">
          <div class="fw-semibold mb-2" style="font-size:.88rem;color:#4a2d7a">🏷️ Who uses this feature?</div>
          <select class="form-select form-select-sm mb-3" id="featSelect" onchange="renderFeatCustomers()">
            <option value="">— select a feature —</option>
          </select>
          <div id="featCustResult" style="font-size:.82rem;color:#6c757d">Select a feature above to see which customers use it.</div>
        </div>
      </div>
      <!-- Panel B: Customer → Features -->
      <div class="col-md-6">
        <div class="p-3 rounded-3" style="background:#f8f9fa;height:100%">
          <div class="fw-semibold mb-2" style="font-size:.88rem;color:#4a2d7a">👤 What does this customer use?</div>
          <select class="form-select form-select-sm mb-3" id="custSelect" onchange="renderCustFeatures()">
            <option value="">— select a customer —</option>
          </select>
          <div id="custFeatResult" style="font-size:.82rem;color:#6c757d">Select a customer above to see their feature usage.</div>
        </div>
      </div>
    </div>
  </div>
</div>


</div><!-- /container -->

<div class="footer container">
  WSO2 Feature Utilization — Product Development Dashboard
  &nbsp;·&nbsp; {product_id}
  &nbsp;·&nbsp; {'v' + selected_version if version_mode else versions_label}
  &nbsp;·&nbsp; Generated {generated_at}
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
// ─── LIVE DATA (generated by 12_report_product_dev.py) ───────────────────────
const TOTAL_CUSTOMERS     = {total_customers};
const FEATURES            = {features_js};
const DEPTH               = {depth_js};
const DROPOFF             = {dropoff_js};
const VER_MATRIX          = {ver_matrix_js};
const VERSIONS            = {versions_js};
const CATEGORIES          = {categories_js};
const ZERO_FEATS          = {zero_js};
const COMBOS              = {combos_js};
const FEAT_CUSTOMERS      = {feat_customers_js};
const FEAT_CUSTOMERS_BY_VERSION = {feat_customers_by_version_js};
const CUST_FEATURES       = {cust_features_js};
const CUST_FEATURES_BY_VERSION = {cust_features_by_version_js};
const VER_TOTAL_CUSTOMERS = {ver_total_custs_js};

// ─── HELPERS ─────────────────────────────────────────────────────────────────
function tierLabel(pct) {{
  if (pct > 70)  return '<span class="tier-high">🟢 High</span>';
  if (pct >= 30) return '<span class="tier-mid">🟡 Medium</span>';
  if (pct > 0)   return '<span class="tier-low">🔴 Low</span>';
  return '<span class="tier-zero">⬜ Zero</span>';
}}
function tierClass(pct) {{
  if (pct > 70)  return 'high';
  if (pct >= 30) return 'mid';
  if (pct > 0)   return 'low';
  return 'zero';
}}
function ftBadge(ft) {{
  const m = {{ core:'ft-core', premium:'ft-premium', enterprise:'ft-enterprise' }};
  return '<span class="' + (m[ft] || 'ft-core') + '">' + ft + '</span>';
}}
function trendIcon(t) {{
  if (t === 'up')   return '<span style="color:#16a34a">⬆</span>';
  if (t === 'down') return '<span style="color:#dc2626">⬇</span>';
  return '<span style="color:#9ca3af">➡</span>';
}}
function barColor(pct) {{
  if (pct > 70)  return '#22c55e';
  if (pct >= 30) return '#f59e0b';
  if (pct > 0)   return '#ef4444';
  return '#d1d5db';
}}
function pbarHtml(pct, color) {{
  return '<div class="pbar flex-grow-1"><div class="pbar-fill" style="width:'+pct+'%;background:'+color+'"></div></div>';
}}
function vmCell(v) {{
  const bg  = v > 70 ? '#dcfce7' : v >= 30 ? '#fef3c7' : v > 0 ? '#fee2e2' : '#f3f4f6';
  const col = v > 70 ? '#166534' : v >= 30 ? '#92400e' : v > 0 ? '#991b1b' : '#9ca3af';
  const brd = v > 70 ? '#86efac' : v >= 30 ? '#fcd34d' : v > 0 ? '#fca5a5' : '#d1d5db';
  return '<td><span class="vm-cell" style="background:'+bg+';color:'+col+';border:1px solid '+brd+'">'+(v === 0 ? '—' : v+'%')+'</span></td>';
}}
function vTrendHtml(v_pcts) {{
  const vals = VERSIONS.map(v => v_pcts[v] || 0);
  if (vals.length < 2) return '';
  const d = vals[vals.length-1] - vals[0];
  if (d > 10)  return '<span style="color:#16a34a;font-size:.85rem">⬆ +'+d+'pp</span>';
  if (d < -5)  return '<span style="color:#dc2626;font-size:.85rem">⬇ '+d+'pp</span>';
  return '<span style="color:#9ca3af;font-size:.85rem">➡ '+(d>0?'+':'')+d+'pp</span>';
}}
function gapBadge(gap) {{
  if (gap >= 20) return '<span class="badge bg-danger">'+gap+'% gap</span>';
  if (gap >= 10) return '<span class="badge bg-warning text-dark">'+gap+'% gap</span>';
  return '<span class="badge bg-success">'+gap+'% gap</span>';
}}
function dropBadge(rate) {{
  if (rate >= 40) return '<span class="badge bg-danger">'+rate+'% drop</span>';
  if (rate >= 20) return '<span class="badge bg-warning text-dark">'+rate+'% drop</span>';
  return '<span class="badge bg-secondary">'+rate+'% drop</span>';
}}

// ─── VERSION-AWARE STATE ─────────────────────────────────────────────────────
let _curVer          = 'all';
let _curVerTotal     = TOTAL_CUSTOMERS;
let _activeTierFilter = 'all';

function trendPpHtml(pp) {{
  if (pp > 0)  return '<span style="color:#16a34a;font-size:.8rem">⬆ +'+pp+'pp</span>';
  if (pp < 0)  return '<span style="color:#dc2626;font-size:.8rem">⬇ '+pp+'pp</span>';
  return '<span style="color:#9ca3af;font-size:.8rem">➡ 0pp</span>';
}}
function currentFeatCustomers(code) {{
  if (_curVer === 'all') return FEAT_CUSTOMERS[code] || [];
  return (FEAT_CUSTOMERS_BY_VERSION[_curVer] || {{}})[code] || [];
}}
function currentCustFeaturesMap() {{
  if (_curVer === 'all') return CUST_FEATURES;
  return CUST_FEATURES_BY_VERSION[_curVer] || {{}};
}}
function statusBadge(st) {{
  if (!st) return '<span class="status-unknown">—</span>';
  const cls = 'status-' + st.toLowerCase();
  return '<span class="'+cls+'">'+st.charAt(0).toUpperCase()+st.slice(1)+'</span>';
}}
window.toggleCustNames = function(rowId, code) {{
  const detailRow = document.getElementById('cust-'+rowId);
  if (detailRow) {{ detailRow.remove(); return; }}
  const custList  = currentFeatCustomers(code).slice(0, 25);
  const chips     = custList.map(c =>
    '<span class="cust-chip" title="'+c.name+' · '+c.tier+' · '+c.total_count+' events">'+c.name+'</span>'
  ).join('');
  document.getElementById('row-'+rowId).insertAdjacentHTML('afterend',
    '<tr id="cust-'+rowId+'" class="cust-names-row"><td colspan="9" class="p-0"><div class="cust-names-list">'+chips+'</div></td></tr>'
  );
}};

// ─── SECTION 1 ───────────────────────────────────────────────────────────────
function renderAdoptionTable(filter) {{
  _activeTierFilter = filter;
  let src = FEATURES;
  if (_curVer !== 'all') {{
    src = VER_MATRIX.map(r => {{
      const base = FEATURES.find(f => f.code === r.code);
      if (!base) return null;
      const pct = r.v_pcts[_curVer] || 0;
      return Object.assign({{}}, base, {{ pct, customers: Math.round(pct / 100 * _curVerTotal) }});
    }}).filter(Boolean);
  }}
  const list = filter === 'all' ? src : src.filter(f => tierClass(f.pct) === filter);
  document.getElementById('adoptionTbody').innerHTML = list.map((f, i) => {{
    const col      = barColor(f.pct);
    const rowId    = 'r' + i;
    const custCount = currentFeatCustomers(f.code).length;
    const expandBtn = custCount > 0
      ? '<button class="cust-expand-btn" onclick="toggleCustNames(&apos;'+rowId+'&apos;,&apos;'+f.code+'&apos;)">▾ '+custCount+' names</button>'
      : '';
    return '<tr id="row-'+rowId+'" data-tier="'+tierClass(f.pct)+'">'
      + '<td class="ps-3 text-muted" style="font-size:.78rem">'+(i+1)+'</td>'
      + '<td><strong style="font-size:.85rem">'+f.name+'</strong><div><code>'+f.code+'</code></div></td>'
      + '<td><span style="font-size:.78rem;color:#6c757d">'+f.cat+'</span></td>'
      + '<td>'+ftBadge(f.ft)+'</td>'
      + '<td class="text-end fw-bold" style="color:'+col+'">'+f.pct+'%</td>'
      + '<td style="min-width:145px"><div class="d-flex align-items-center gap-2">'
        +pbarHtml(f.pct,col)+'<span style="font-size:.75rem;white-space:nowrap">'+f.customers+'/'+_curVerTotal+'</span>'
        +'</div>'+expandBtn+'</td>'
      + '<td class="text-center">'+trendPpHtml(f.trend_pp || 0)+'</td>'
      + '<td class="text-center">'+statusBadge(f.status)+'</td>'
      + '<td class="text-center">'+tierLabel(f.pct)+'</td>'
      + '</tr>';
  }}).join('');
}}
window.filterTable = function(btn, filter) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderAdoptionTable(filter);
}};
renderAdoptionTable('all');

// ─── VERSION FILTER ───────────────────────────────────────────────────────────
window.setVersion = function(btn, ver) {{
  document.querySelectorAll('.ver-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _curVer      = ver;
  _curVerTotal = ver === 'all' ? TOTAL_CUSTOMERS : (VER_TOTAL_CUSTOMERS[ver] || TOTAL_CUSTOMERS);

  // Derive current feature list for this version
  let curFeats = FEATURES;
  if (ver !== 'all') {{
    curFeats = VER_MATRIX.map(r => {{
      const base = FEATURES.find(f => f.code === r.code);
      if (!base) return null;
      const pct = r.v_pcts[ver] || 0;
      return Object.assign({{}}, base, {{ pct, customers: Math.round(pct / 100 * _curVerTotal) }});
    }}).filter(Boolean);
  }}

  // Update version note
  const note = document.getElementById('verFilterNote');
  if (note) note.textContent = ver === 'all'
    ? 'Showing combined view across all deployed versions'
    : 'Showing data for v'+ver+' ('+_curVerTotal+' customers)';

  // Update scorecard
  document.getElementById('sc-customers').textContent = _curVerTotal;
  document.getElementById('sc-ver-label').textContent = ver === 'all' ? '{versions_label}' : 'v'+ver;
  document.getElementById('sc-high').textContent = curFeats.filter(f=>f.pct>70).length;
  document.getElementById('sc-mid').textContent  = curFeats.filter(f=>f.pct>=30&&f.pct<=70).length;
  document.getElementById('sc-low').textContent  = curFeats.filter(f=>f.pct>0&&f.pct<30).length;
  document.getElementById('sc-zero').textContent = curFeats.filter(f=>f.pct===0).length;

  // Update filter-all button count
  const allBtn = document.getElementById('filterAll');
  if (allBtn) allBtn.textContent = 'All ('+curFeats.length+')';

  // Update donut chart
  const counts = tierCounts(curFeats);
  donutChart.data.datasets[0].data = counts;
  donutChart.update();

  // Update adoption bar chart
  const sorted = [...curFeats].sort((a,b)=>b.pct-a.pct);
  adoptionChart.data.labels              = sorted.map(f=>f.name);
  adoptionChart.data.datasets[0].data           = sorted.map(f=>f.pct);
  adoptionChart.data.datasets[0].backgroundColor = sorted.map(f=>barColor(f.pct));
  adoptionChart.update();

  // Re-render table
  renderAdoptionTable(_activeTierFilter);
  refreshExplorerOptions();
  renderFeatCustomers();
  renderCustFeatures();
}};

// ─── SECTION 2 ───────────────────────────────────────────────────────────────
document.getElementById('depthTbody').innerHTML = DEPTH.map(d => {{
  const gap = d.gap_pct;
  return '<tr>'
    + '<td class="ps-3"><strong style="font-size:.85rem">'+d.name+'</strong><div><code>'+d.code+'</code></div></td>'
    + '<td class="text-center fw-semibold">'+d.enabled_pct+'%</td>'
    + '<td class="text-center fw-semibold" style="color:'+barColor(d.used_pct)+'">'+d.used_pct+'%</td>'
    + '<td><div class="d-flex align-items-center gap-2"><div style="position:relative;height:20px;width:100px"><div style="position:absolute;top:7px;left:0;right:0;height:6px;background:#e5e7eb;border-radius:3px"></div><div style="position:absolute;top:7px;left:0;height:6px;width:'+d.enabled_pct+'%;background:#93c5fd;border-radius:3px"></div><div style="position:absolute;top:7px;left:0;height:6px;width:'+d.used_pct+'%;background:#3b82f6;border-radius:3px"></div></div>'+gapBadge(gap)+'</div></td>'
    + '</tr>';
}}).join('');

// ─── SECTION 3 ───────────────────────────────────────────────────────────────
(function() {{
  const tbody = document.getElementById('dropoffTbody');
  const table = document.getElementById('dropoffTable');
  const empty = document.getElementById('dropoffEmpty');
  if (DROPOFF.length === 0) {{
    empty.style.display = '';
  }} else {{
    table.style.display = '';
    tbody.innerHTML = DROPOFF.map(d => {{
      const rowCls = d.drop_rate >= 40 ? 'drop-critical' : d.drop_rate >= 20 ? 'drop-warn' : '';
      const risk = d.drop_rate >= 40
        ? '<span class="badge bg-danger">Critical</span>'
        : d.drop_rate >= 20 ? '<span class="badge bg-warning text-dark">Moderate</span>'
        : '<span class="badge bg-secondary">Low</span>';
      return '<tr class="'+rowCls+'">'
        + '<td class="ps-3"><strong style="font-size:.85rem">'+d.name+'</strong><div style="font-size:.73rem;color:#6c757d">'+d.cat+'</div></td>'
        + '<td class="text-center fw-semibold">'+d.init_pct+'%</td>'
        + '<td class="text-center fw-semibold" style="color:'+barColor(d.curr_pct)+'">'+d.curr_pct+'%</td>'
        + '<td><div class="d-flex align-items-center gap-2">'+pbarHtml(d.drop_rate, d.drop_rate>=40?'#dc2626':d.drop_rate>=20?'#f59e0b':'#9ca3af')+dropBadge(d.drop_rate)+'</div></td>'
        + '<td>'+risk+'</td>'
        + '<td style="font-size:.78rem;color:#6c757d">v'+d.peak_ver+'</td>'
        + '</tr>';
    }}).join('');
  }}
}})();

// ─── SECTION 4 ───────────────────────────────────────────────────────────────
(function() {{
  const head = document.getElementById('verMatrixHead');
  head.innerHTML = '<th class="text-start ps-2" style="min-width:180px">Feature</th>'
    + VERSIONS.map(v => '<th>v'+v+'</th>').join('')
    + '<th class="text-start ps-3" style="min-width:100px;font-size:.7rem">Trend</th>';

  document.getElementById('verMatrixBody').innerHTML = VER_MATRIX.map(r => {{
    return '<tr>'
      + '<td class="text-start ps-2 fw-semibold" style="font-size:.82rem">'+r.name+'</td>'
      + VERSIONS.map(v => vmCell(r.v_pcts[v] || 0)).join('')
      + '<td class="text-start ps-3">'+vTrendHtml(r.v_pcts)+'</td>'
      + '</tr>';
  }}).join('');
}})();

// ─── SECTION 5 ───────────────────────────────────────────────────────────────
document.getElementById('categoryTbody').innerHTML = CATEGORIES.map(c => {{
  return '<tr>'
    + '<td class="ps-2 fw-semibold" style="font-size:.82rem">'+c.name+'</td>'
    + '<td class="text-center text-muted" style="font-size:.8rem">'+c.feats+'</td>'
    + '<td class="text-center"><span class="fw-bold" style="color:'+barColor(c.avg)+'">'+c.avg+'%</span></td>'
    + '<td class="text-center text-muted" style="font-size:.8rem">'+c.nonzero+'/'+c.feats+'</td>'
    + '</tr>';
}}).join('');

// ─── SECTION 6 ───────────────────────────────────────────────────────────────
(function() {{
  const badge = document.getElementById('zeroCntBadge');
  const table = document.getElementById('zeroTable');
  const empty = document.getElementById('zeroEmpty');
  badge.textContent = ZERO_FEATS.length + ' feature' + (ZERO_FEATS.length !== 1 ? 's' : '');
  if (ZERO_FEATS.length === 0) {{
    empty.style.display = ''; badge.className = 'badge bg-success ms-1';
  }} else {{
    table.style.display = '';
    document.getElementById('zeroTbody').innerHTML = ZERO_FEATS.map(f => {{
      return '<tr>'
        + '<td class="ps-3"><code>'+f.code+'</code></td>'
        + '<td style="font-size:.85rem">'+f.name+'</td>'
        + '<td style="font-size:.78rem;color:#6c757d">'+f.cat+'</td>'
        + '<td>'+ftBadge(f.tier)+'</td>'
        + '<td style="font-size:.78rem;color:#6c757d">v'+f.version+'</td>'
        + '<td style="font-size:.78rem;color:#374151">'+f.action+'</td>'
        + '</tr>';
    }}).join('');
  }}
}})();

// ─── SECTION 7 ───────────────────────────────────────────────────────────────
document.getElementById('combosContainer').innerHTML = COMBOS.map(c => {{
  return '<div class="combo-row">'
    + '<div class="combo-pct" style="color:'+c.color+'">'+c.pct+'%</div>'
    + '<div style="flex:0 0 6px;height:40px;background:'+c.color+';border-radius:3px;opacity:.4"></div>'
    + '<div><div class="fw-semibold" style="font-size:.9rem">'+c.label+'</div><div style="font-size:.78rem;color:#6c757d">'+c.desc+'</div></div>'
    + '<div class="ms-auto"><div class="pbar" style="width:120px"><div class="pbar-fill" style="width:'+c.pct+'%;background:'+c.color+'"></div></div><div style="font-size:.7rem;color:#9ca3af;text-align:right;margin-top:2px">'+c.count+' of '+TOTAL_CUSTOMERS+' customers</div></div>'
    + '</div>';
}}).join('');

// ─── CHARTS ──────────────────────────────────────────────────────────────────
function tierCounts(src) {{
  return [
    src.filter(f=>f.pct>70).length,
    src.filter(f=>f.pct>=30&&f.pct<=70).length,
    src.filter(f=>f.pct>0&&f.pct<30).length,
    src.filter(f=>f.pct===0).length,
  ];
}}

const donutChart = new Chart(document.getElementById('donutChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['High >70%','Medium 30-70%','Low <30%','Zero 0%'],
    datasets: [{{
      data: tierCounts(FEATURES),
      backgroundColor: ['#22c55e','#f59e0b','#ef4444','#d1d5db'],
      borderWidth: 2, borderColor: '#fff',
    }}]
  }},
  options: {{
    cutout: '62%',
    plugins: {{
      legend: {{ position:'right', labels:{{ font:{{size:11}}, boxWidth:12, padding:8 }} }},
      tooltip: {{ callbacks: {{ label: ctx => ' '+ctx.label+': '+ctx.parsed+' features' }} }}
    }}
  }}
}});

const sortedByAdopt = [...FEATURES].sort((a,b)=>b.pct-a.pct);
const adoptionChart = new Chart(document.getElementById('adoptionChart'), {{
  type: 'bar',
  data: {{
    labels: sortedByAdopt.map(f=>f.name),
    datasets: [{{ label:'Adoption %', data: sortedByAdopt.map(f=>f.pct), backgroundColor: sortedByAdopt.map(f=>barColor(f.pct)), borderRadius:3 }}]
  }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend:{{display:false}}, tooltip:{{ callbacks:{{ label: ctx=>' '+ctx.parsed.x+'% of customers' }} }} }},
    scales: {{
      x: {{ max:100, grid:{{color:'#f0f0f0'}}, ticks:{{font:{{size:10}},callback:v=>v+'%'}} }},
      y: {{ ticks:{{font:{{size:10}}}} }}
    }}
  }}
}});

new Chart(document.getElementById('depthChart'), {{
  type: 'bar',
  data: {{
    labels: DEPTH.map(d=>d.name),
    datasets: [
      {{ label:'Enabled %',       data:DEPTH.map(d=>d.enabled_pct), backgroundColor:'rgba(99,102,241,.25)', borderColor:'rgba(99,102,241,.6)', borderWidth:1.5, borderRadius:3 }},
      {{ label:'Actively Used %', data:DEPTH.map(d=>d.used_pct),    backgroundColor:'rgba(34,197,94,.35)',  borderColor:'rgba(22,163,74,.7)',   borderWidth:1.5, borderRadius:3 }},
    ]
  }},
  options: {{
    plugins: {{ legend:{{position:'top',labels:{{font:{{size:11}}}}}}, tooltip:{{ callbacks:{{ label: ctx=>' '+ctx.dataset.label+': '+ctx.parsed.y+'%' }} }} }},
    scales: {{
      x: {{ ticks:{{font:{{size:9}},maxRotation:35}} }},
      y: {{ max:100, grid:{{color:'#f0f0f0'}}, ticks:{{font:{{size:10}},callback:v=>v+'%'}} }}
    }}
  }}
}});

// ─── SECTION 8 ───────────────────────────────────────────────────────────────
(function() {{
  const featSel = document.getElementById('featSelect');
  [...FEATURES].sort((a,b)=>a.name.localeCompare(b.name)).forEach(f => {{
    const o = document.createElement('option');
    o.value = f.code; o.textContent = f.name + ' (' + f.code + ')';
    featSel.appendChild(o);
  }});
  const custSel = document.getElementById('custSelect');
  Object.entries(CUST_FEATURES).sort((a,b)=>a[1].name.localeCompare(b[1].name)).forEach(([cid,cd]) => {{
    const o = document.createElement('option');
    o.value = cid; o.textContent = cd.name + (cd.tier ? ' ['+cd.tier+']' : '');
    custSel.appendChild(o);
  }});
}})();
function refreshExplorerOptions() {{
  const featSel = document.getElementById('featSelect');
  const custSel = document.getElementById('custSelect');
  const currentCustomerMap = currentCustFeaturesMap();
  const prevFeat = featSel.value;
  const prevCust = custSel.value;

  featSel.innerHTML = '<option value="">— select a feature —</option>';
  [...FEATURES].sort((a,b)=>a.name.localeCompare(b.name)).forEach(f => {{
    const o = document.createElement('option');
    o.value = f.code; o.textContent = f.name + ' (' + f.code + ')';
    featSel.appendChild(o);
  }});

  custSel.innerHTML = '<option value="">— select a customer —</option>';
  Object.entries(currentCustomerMap).sort((a,b)=>a[1].name.localeCompare(b[1].name)).forEach(([cid,cd]) => {{
    const o = document.createElement('option');
    o.value = cid; o.textContent = cd.name + (cd.tier ? ' ['+cd.tier+']' : '');
    custSel.appendChild(o);
  }});

  if (prevFeat) featSel.value = prevFeat;
  if (prevCust && currentCustomerMap[prevCust]) {{
    custSel.value = prevCust;
  }} else {{
    custSel.value = '';
  }}
}}

window.renderFeatCustomers = function() {{
  const code = document.getElementById('featSelect').value;
  const out  = document.getElementById('featCustResult');
  if (!code) {{ out.innerHTML = '<span style="color:#6c757d">Select a feature above.</span>'; return; }}
  const list = currentFeatCustomers(code);
  if (!list.length) {{
    out.innerHTML = '<span style="color:#9ca3af">No customers recorded for this feature.</span>';
    return;
  }}
  out.innerHTML = '<div class="mb-1 text-muted" style="font-size:.74rem">'+list.length+' customer'+(list.length!==1?'s':'')+' · sorted by usage</div>'
    + '<table class="table table-sm mb-0"><thead><tr><th>Customer</th><th>Tier</th><th class="text-end">Events</th></tr></thead><tbody>'
    + list.map(c =>
        '<tr><td class="fw-semibold" style="font-size:.82rem">'+c.name+'</td><td>'+ftBadge(c.tier)+'</td>'
        +'<td class="text-end text-muted" style="font-size:.8rem">'+c.total_count.toLocaleString()+'</td></tr>'
      ).join('')
    + '</tbody></table>';
}};

window.renderCustFeatures = function() {{
  const cid = document.getElementById('custSelect').value;
  const out  = document.getElementById('custFeatResult');
  const currentCustomerMap = currentCustFeaturesMap();
  if (!cid) {{ out.innerHTML = '<span style="color:#6c757d">Select a customer above.</span>'; return; }}
  const cd = currentCustomerMap[cid];
  if (!cd || !cd.features || !cd.features.length) {{
    out.innerHTML = '<span style="color:#9ca3af">No feature usage data for this customer.</span>';
    return;
  }}
  out.innerHTML = '<div class="mb-1 text-muted" style="font-size:.74rem">'+cd.features.length+' feature'+(cd.features.length!==1?'s':'')+' used · sorted by usage</div>'
    + '<table class="table table-sm mb-0"><thead><tr><th>Feature</th><th>Category</th><th class="text-end">Events</th></tr></thead><tbody>'
    + cd.features.map(f =>
        '<tr><td><strong style="font-size:.82rem">'+f.name+'</strong><div><code>'+f.code+'</code></div></td>'
        +'<td style="font-size:.78rem;color:#6c757d">'+f.cat+'</td>'
        +'<td class="text-end text-muted" style="font-size:.8rem">'+f.total_count.toLocaleString()+'</td></tr>'
      ).join('')
    + '</tbody></table>';
}};

const catsSorted = [...CATEGORIES].sort((a,b)=>b.avg-a.avg);
new Chart(document.getElementById('categoryChart'), {{
  type: 'bar',
  data: {{
    labels: catsSorted.map(c=>c.name),
    datasets: [{{ label:'Avg Adoption %', data:catsSorted.map(c=>c.avg), backgroundColor:catsSorted.map(c=>barColor(c.avg)), borderRadius:4 }}]
  }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend:{{display:false}}, tooltip:{{ callbacks:{{ label: ctx=>' '+ctx.parsed.x+'% avg adoption' }} }} }},
    scales: {{
      x: {{ max:100, grid:{{color:'#f0f0f0'}}, ticks:{{font:{{size:10}},callback:v=>v+'%'}} }},
      y: {{ ticks:{{font:{{size:11}}}} }}
    }}
  }}
}});
</script>
</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate WSO2 Product Development Team HTML report"
    )
    parser.add_argument("--api",     default="http://127.0.0.1:8001",   help="API base URL")
    parser.add_argument("--product", default="identity-server",          help="Product ID")
    parser.add_argument("--version", default=None,                       help="Generate a version-specific report, e.g. 7.3.0")
    parser.add_argument("--out",     default=None,                       help="Output file path")
    args = parser.parse_args()

    data     = load_data(args.api, args.product, version_filter=args.version)
    html     = build_html(data, args.product)
    outfile  = args.out or (f"reports/product_dev_{args.version.replace('.', '_')}.html" if args.version else "reports/product_dev.html")

    Path(outfile).parent.mkdir(parents=True, exist_ok=True)
    Path(outfile).write_text(html, encoding="utf-8")
    print(f"\nReport saved → {Path(outfile).resolve()}")
    print(f"Open in browser: open {outfile}")


if __name__ == "__main__":
    main()
