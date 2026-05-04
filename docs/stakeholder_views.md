# WSO2 Feature Utilization — Stakeholder Views
**Document version:** 3.0  
**Status:** Current implementation reference

---

## Purpose

This document describes the views that are currently available in the repository, how they are intended to be used, and where the current implementation still has known limitations.

This is now an implementation-aligned reference, not a speculative design document.

---

## Navigation Model

The repository exposes one primary UI entry point:

- Primary feature explorer: `/views/feature-utilization`

Recommended flow:

1. Start in the feature explorer for product, version, customer, region, and customer-tier filtering
2. Drill into feature-level detail where needed
3. Open stakeholder-specific summary views from the explorer when you need a narrative or audience-specific framing

---

## Data Available in the System

| Table | Key fields |
|---|---|
| `customer` | id, name, region, tier |
| `deployment` | id, customer_id, environment, product_release_id |
| `product_release` | product_id, version, name, is_active |
| `catalog_category` | code, name, parent_category_code |
| `catalog_feature` | code, name, category_code, tier, status, introduced_in |
| `utilization_report` | deployment_id, report_from, report_to |
| `feature_utilization` | feature_code, total_count, is_enabled, dimension_breakdown |
| `feature_usage_event` | event_name, event_timestamp, dimensions |

---

## View 1 — Feature Utilization Explorer

**Route:** `/views/feature-utilization`

**Audience:** Shared landing experience for Product, CSM, Regional, and Technical users

**Current focus:**
- Product filter, including `All Products`
- Version filter
- Customer filter
- Region filter
- Customer Tier filter
- Summary cards for adoption tiers and enablement signals
- Decision-signal cards such as deprecation-review candidates and enablement-gap priorities
- Clickable feature table
- Feature detail page at `/views/feature-utilization/detail`

**What it is best for:**
- fast filtering
- cross-product exploration
- version-specific feature inspection
- customer-scoped feature analysis
- navigating into stakeholder views from a filtered starting point

**Important implementation notes:**
- This is the primary landing page for the app
- It is dynamically generated from the live database state
- It is not backed by a static HTML artifact in the repository

---

## View 2 — Technical Owner

**Route:** `/views/technical-owner?customer_id=...&product_id=...`

**Audience:** Technical Owner / Solutions Architect / Technical Account Manager

**Current focus:**
- feature status matrix
- configured vs actively used signals
- capability / category health
- technical posture indicators
- unused or redundant configurations
- optimization recommendations
- version and feature alignment

**What it is best for:**
- reviewing one customer and one product at a time
- spotting enabled-but-unused configurations
- identifying rollout, cleanup, and reliability concerns

**Current limitations:**
- the view is account-specific, not a full deployment-by-deployment operations console
- it is more product-agnostic than the earlier Identity-Server-only design, so some explicitly security-flavored metrics were intentionally generalized

---

## View 3 — Customer Success

**Route:** `/views/customer-success`

**Audience:** Customer Success Team

**Current focus:**
- customer adoption score
- feature coverage vs available capability
- underutilized features
- usage trend over time
- risk indicators
- expansion opportunities
- maturity segmentation

**What it is best for:**
- health-style portfolio review
- churn-risk conversations
- identifying adoption and upsell opportunities

**Current limitations:**
- the view still contains product-specific assumptions in some of its deeper recommendations and expansion heuristics
- the current implementation is now scope-aware for product, version, region, and customer tier, but some deeper logic still reflects Identity Server-oriented feature families

---

## View 4 — Regional Managers

**Route:** `/views/regional`  
**Focused route:** `/views/regional?region=eu-west`

**Audience:** Regional Managers / Commercial Leaders

**Current focus:**
- regional adoption overview
- capability adoption by region
- expansion opportunity index
- regional risk heatmap
- adoption trends
- maturity distribution
- focused single-region operating view

**What it is best for:**
- comparing regions
- identifying stronger and weaker markets
- spotting regional opportunity and risk patterns

**Current limitations:**
- the all-regions view is intentionally category/capability-led rather than raw feature-led
- some underlying coverage logic is still product-specific and currently favors `identity-server`

---

## View 5 — Product Development

**Route:** `/views/product-dev?product_id=...`  
**Version-focused route:** `/views/product-dev?product_id=...&version=...`

**Audience:** Product Managers and Engineering Leadership

**Current focus:**
- high / medium / low / zero feature adoption
- enabled vs active usage gap
- adoption drop-off
- version comparison
- category-level usage patterns
- feature combinations
- zero-adoption features

**What it is best for:**
- roadmap prioritization
- version-specific release review
- deprecation-review candidates
- identifying weak or under-adopted product areas

**Current limitations:**
- the live report is product-aware, but much of the historical framing was originally built around Identity Server
- the “overall trend over time” signal is still stronger at feature/version level than as one compact top-level product trend metric

---

## Entry Route Behavior

**Routes:** `/views` and `/views/feature-utilization`

Important behavior:
- `/views/feature-utilization` is the real landing page
- `/views` now redirects to `/views/feature-utilization` for backward compatibility
- stakeholder-specific links live inside the explorer itself

---

## Dynamic vs Generated HTML

The live `/views/...` pages are generated dynamically from the current application state and database contents.

They are not served from pre-generated HTML files in the repository.

Generated HTML reports can still be created locally through the report scripts, but those are demo artifacts only and are not the source of truth for the running app.

---

## Known Gaps

These are the main documentation-relevant gaps between the current implementation and the broader intended product direction:

- Customer Success is scope-aware, but some deeper heuristics remain product-flavored
- Regional Managers is not yet fully product-aware end to end
- Some taxonomy fields described elsewhere remain partially populated or inconsistently used across products
- Some historical scripts and naming still reflect older Identity Server-first assumptions

---

## Recommended Reading Order

For someone new to the project:

1. `README.md` for setup and app entry points
2. this document for current view behavior
3. `docs/event_capture_taxonomy.md` for the intended tracking and taxonomy model
