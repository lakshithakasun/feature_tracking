# WSO2 Feature Utilization — Stakeholder Views
**Document version:** 2.0  
**Status:** For review and sign-off before implementation

---

## Purpose

This document defines what each stakeholder view should display, how existing data should be visualized for each audience, and what practical data additions would make each view more useful. All data comes from this system — no external CRM or data source integration is needed.

---

## Data Available in the System (Reference)

| Table | Key fields |
|---|---|
| `customer` | id, name, region, tier |
| `deployment` | id, customer_id, environment, product_release_id |
| `product_release` | product_id, version, name, is_active |
| `catalog_category` | code, name, parent_category_code |
| `catalog_feature` | code, name, category_code, tier, status, introduced_in |
| `utilization_report` | deployment_id, report_from, report_to |
| `feature_utilization` | feature_code, total_count, dimension_breakdown |

---

## View 1 — Account Manager / Technical Owner View

**Audience:** The WSO2 account manager responsible for a customer, and the customer's own technical owner.

**Purpose:** Show the full picture of one customer's deployments, what they are using, and how they are using it — so the account manager can have an informed conversation about the customer's usage patterns.

---

### Section 1.1 — Customer Header

Display from `customer` table:
- Customer name and ID
- Tier (`customer.tier` — core / premium / enterprise)
- Region (`customer.region`)

Display from `deployment` + `product_release` joined:
- List of all deployments: deployment ID, environment label (prod / staging / dev), product version, report period covered (report_from – report_to)

---

### Section 1.2 — Feature Usage Summary Table

For each feature the customer has reported usage on, across all their deployments and report periods:

| Column | Source |
|---|---|
| Feature name | `catalog_feature.name` |
| Category | `catalog_category.name` via `catalog_feature.category_code` |
| Total events | `feature_utilization.total_count` |
| Deployment | `deployment.environment` |
| Product version | `product_release.version` |
| Report period | `utilization_report.report_from` – `report_to` |

Sort by total events descending. Group by category so the table is navigable.

**Dimension breakdown sub-row:** For each feature row, expand to show `dimension_breakdown` key-value pairs (e.g. for `is.mfa.totp`: enroll: 270, verify: 5900, verify-failed: 30). This tells the account manager and technical owner exactly HOW the feature is being used.

---

### Section 1.3 — Category Usage Bar Chart

Bar chart showing total event volume per feature category for this customer.
- Data: sum of `feature_utilization.total_count` grouped by `catalog_category.name`
- Purpose: quick visual of which capability areas the customer is most active in

---

### Section 1.4 — Deployment Comparison (if multiple deployments exist)

If the customer has more than one deployment (e.g. prod + staging):
- Side-by-side table: feature code as rows, deployments as columns, total_count as cell value
- Empty cell means that feature has no usage in that deployment
- This surfaces features the customer is testing in staging but has not yet activated in prod

---

### Section 1.5 — Features Not Yet Used

List of features available in the product version the customer is running that have **zero usage** reported by this customer, grouped by category.
- Data: `catalog_feature` for the customer's product version, left-joined against `feature_utilization` — features with no matching utilization rows
- This is an enablement signal for the account manager: things the customer has access to but hasn't activated

---

### Practical Data Gaps for This View

| Gap | Impact | Effort |
|---|---|---|
| `deployment.label` — a human-readable name for the deployment (e.g. "Production — US East") rather than just an ID | Makes the deployment comparison section readable for non-technical stakeholders | Low — add one column to `deployment` |
| Multiple report periods stored per deployment | Currently data is a single snapshot per deployment. Storing multiple periods would let this view show usage over time | Medium — supported by schema, needs multiple ingestion runs |

---

## View 2 — Regional GM View

**Audience:** The General Manager responsible for a geographic region (e.g. US, EU, APAC). Used for regional business reviews and QBRs.

**Purpose:** Give the GM a rolled-up view of all customers in their region — what they are running, what they are using, and how the region compares to others.

---

### Section 2.1 — Regional Scorecard (Summary Cards)

Display top-line numbers for the region:
- Total customers in this region — count of `customer` where `customer.region` = selected region
- Breakdown by tier — count of customers per `customer.tier`
- Total deployments in region
- Total feature events across all regional customers in the latest report period
- Number of distinct product versions in use across the region

---

### Section 2.2 — Customer List Table

One row per customer in the selected region:

| Column | Source |
|---|---|
| Customer name | `customer.name` |
| Tier | `customer.tier` |
| Deployments | count of `deployment` rows for this customer |
| Product version(s) | `product_release.version` for each deployment |
| Total feature events | sum of `feature_utilization.total_count` for this customer |
| Report period | `utilization_report.report_from` – `report_to` |
| Link | → drill into Account Manager view for this customer |

Sort by total events descending. Flag customers who have no utilization report (no data submitted).

---

### Section 2.3 — Top Feature Categories in Region

Bar chart of total events per feature category, aggregated across all customers in the region.
- Shows what the region's customer base is predominantly using

---

### Section 2.4 — Product Version Distribution

Pie or bar chart showing how customers in the region are distributed across product versions.
- Data: group by `product_release.version` across all regional deployments
- Helps GM understand the region's version currency — are customers on the latest release or behind?

---

### Section 2.5 — Cross-Region Comparison

Summary table with one row per region:

| Column | Source |
|---|---|
| Region | `customer.region` |
| Customer count | count of customers |
| Total feature events | sum of all utilization for that region |
| Tier breakdown | count per tier |
| Versions in use | distinct versions |

This lets the GM benchmark their region against others at a glance.

---

### Practical Data Gaps for This View

| Gap | Impact | Effort |
|---|---|---|
| `customer.region` should be a controlled enum (e.g. us-east, us-west, eu-west, eu-central, ap-southeast) rather than a free text string | Without consistent values, cross-region grouping and comparison breaks | Low — enforce at API input level and update existing records |
| Customers with no report submitted in the current period should be flagged explicitly | Without this, the GM cannot tell whether a customer is inactive or simply hasn't been ingested yet | Low — derive from absence of `utilization_report` rows for current period |

---

## View 3 — Product Development Team View

**Audience:** Product managers, engineering leads, and feature owners within the WSO2 Identity Server team.

**Purpose:** Show the product team which features are being adopted across the customer base, how each feature is actually being used (via dimension breakdowns), and what the uptake of new features looks like.

> This view builds on the existing report. The additions here are dimension-level detail and version comparison.

---

### Section 3.1 — Feature × Customer Heatmap

Grid visualization:
- Rows: features (grouped by category)
- Columns: customers
- Cell value: `feature_utilization.total_count` for that feature + customer combination
- Empty cell: no usage reported
- Color intensity: higher count = darker cell

This immediately shows the product team which features are universally adopted, which are niche, and which are completely unused.

---

### Section 3.2 — Dimension Breakdown per Feature

For each feature in the catalog, show a breakdown of how its dimensions are being used across all customers:
- Data: aggregate `feature_utilization.dimension_breakdown` across all customers for each feature
- Display as stacked bar or grouped bar per dimension key

Examples:
- `is.sso.oidc` → grant_type breakdown: authorization-code vs client-credentials vs device-code
- `is.mfa.totp` → action breakdown: enroll vs verify vs verify-failed
- `is.adaptive-auth.conditional-auth` → template used: role-based vs ip-based vs new-device-based

This tells the product team HOW features are being used, not just that they are used.

---

### Section 3.3 — New Features in Latest Version

Table showing features marked as `introduced_in = current version` (e.g. v7.3.0):
- Feature name and category
- How many customers are running this version (denominator)
- How many of those customers have submitted usage for this feature (numerator)
- Total event count

This directly measures post-release feature traction.

---

### Section 3.4 — Features with Zero Usage

List all features in the catalog that have no `feature_utilization` rows across any customer:
- Grouped by category
- Includes `tier` and `status` from `catalog_feature`
- Helps the product team distinguish features that are genuinely unused from those that are enterprise-only or beta

---

### Section 3.5 — Version Comparison Table

If data exists for multiple versions (e.g. v7.2.0 and v7.3.0):
- Side-by-side table of features that exist in both versions
- Total events and customer count per version
- Features new in v7.3.0 are highlighted separately

---

### Practical Data Gaps for This View

| Gap | Impact | Effort |
|---|---|---|
| `introduced_in` not populated in taxonomy YAML | The "new features in latest version" section (3.3) relies on this field — currently empty for all features in taxonomy-7.2.yaml | Medium — need to backfill YAML and re-ingest, or populate DB directly |
| No explicit marking of which dimension values represent failures or errors | The dimension breakdown (3.2) mixes normal and failure outcomes. The product team has to manually identify verify-failed, auth-failed, login-failed, etc. | Low — can be addressed in taxonomy (see taxonomy improvement suggestions below) |

---

## View 4 — Customer Success Team Management View

**Audience:** Management within the Customer Success team — the team responsible for the support operations of customers.

**Purpose:** Give CS management an operational view of the customer base: who is using what, which deployments are active, and where the team's attention should be focused based on what the data shows.

---

### Section 4.1 — Customer Base Overview

Summary cards:
- Total customers managed
- Total active deployments (deployments with at least one utilization report)
- Total feature events in the latest report period
- Customers with no report in the latest period (silent deployments)

---

### Section 4.2 — Customer Portfolio Table

Master table of all customers:

| Column | Source |
|---|---|
| Customer name | `customer.name` |
| Tier | `customer.tier` |
| Region | `customer.region` |
| Deployments | count of `deployment` rows |
| Product version | `product_release.version` for each deployment |
| Features used | count of distinct features with total_count > 0 |
| Total events | sum of `feature_utilization.total_count` |
| Last report | `utilization_report.report_to` (most recent) |
| Link | → drill into customer detail (Account Manager view) |

Sortable by all columns. Flag customers with no recent report.

---

### Section 4.3 — Feature-Level Usage with Failure Dimensions

For customers who have reported dimension values indicating failed or errored interactions (e.g. verify-failed, auth-failed, login-failed, expired), surface these explicitly:

- Table: customer, feature, dimension key, failure dimension value, count
- Derived from `feature_utilization.dimension_breakdown` by identifying known failure dimension values
- This gives CS management an operational signal — which customers are experiencing friction with specific features

> This is not a "failure rate" metric — it is simply surfacing the raw failure-dimension counts that are already in the data, so CS management can prioritise conversations with those customers.

---

### Section 4.4 — Version Posture per Customer

Table showing all customers and their deployment versions:
- Customer name, deployment, environment, product version
- Whether this is the latest available version in the catalog (derived from `product_release.is_active`)
- Customers on older versions highlighted — CS team can follow up on upgrade planning

---

### Section 4.5 — Category-Level Usage Heatmap (CS View)

Simplified heatmap:
- Rows: feature categories
- Columns: customers
- Cell: has usage (colored) / no usage (grey)
- Purpose: gives CS management a quick scan of which capability areas each customer is actually using — useful context before a support call or review meeting

---

### Practical Data Gaps for This View

| Gap | Impact | Effort |
|---|---|---|
| No assignment of a CS team owner to a customer | CS management can see all customers but cannot filter to their own team's portfolio | Low — add `cs_owner` field to `customer` table |
| Failure dimension values are not tagged in the taxonomy | Section 4.3 requires knowing which dimension values are failures — currently this list would need to be hardcoded (verify-failed, auth-failed, login-failed, etc.) | Low — addressed by taxonomy improvement (see below) |

---

## Taxonomy Improvement Suggestions

The following changes to the taxonomy YAML format would directly improve the quality of data available for all four views. These are practical additions that do not change the existing structure.

---

### T1 — Populate `introduced_in` per Feature

**Current state:** The field exists in the DB schema (`catalog_feature.introduced_in`) but is not included in `taxonomy-7.2.yaml` or `taxonomy-7.3.0.yaml`.

**Proposed addition** — add to each feature entry:
```yaml
availability:
  introduced_in: "7.2.0"
```

For the 3 new features in v7.3.0, set `introduced_in: "7.3.0"`. For all existing features, set `introduced_in: "7.2.0"` (or earlier if known).

**Why it matters:** Required for View 3 section 3.3 (new feature traction) and version comparison. Without it, the system cannot distinguish features added in v7.3.0 from features that existed in v7.2.0.

---

### T2 — Add `tier` and `status` Consistently on All Features

**Current state:** `tier` and `status` are stored in the DB but are inconsistently present in the YAML — some features have them, most do not.

**Proposed addition** — every feature entry should include:
```yaml
tier: "core"          # core | premium | enterprise
status: "stable"      # stable | beta | deprecated
```

**Why it matters:** Views 1, 2 and 4 filter and group by tier. Without consistent tier data, the "features available at this tier" grouping is unreliable.

---

### T3 — Mark Failure Dimension Values in Tracking Config

**Current state:** Dimension values like `verify-failed`, `auth-failed`, `login-failed`, `expired`, `access-denied` are defined in the `values` list of a dimension but are not distinguished from success values.

**Proposed addition** — add a `failure_values` list to applicable dimensions:
```yaml
dimensions:
  - name: "action"
    type: "enum"
    values: ["enroll", "verify", "verify-failed"]
    failure_values: ["verify-failed"]
    required: true
```

**Why it matters:** Views 3 and 4 need to surface failure-dimension counts. With this tagging in the taxonomy, the system can derive this automatically from the data rather than relying on a hardcoded list of known failure keywords.

---

## Summary of Practical Data Additions

| Addition | Views affected | Priority |
|---|---|---|
| `introduced_in` populated in taxonomy YAML | Product (3.3), cross-version comparison | High |
| `tier` and `status` consistently set on all features | All views | High |
| `failure_values` tag on dimensions in taxonomy | Product (3.2), CS (4.3) | Medium |
| `customer.region` as controlled enum | GM (all sections) | Medium |
| `deployment.label` — human-readable deployment name | AM (1.4), CS (4.4) | Low |
| `customer.cs_owner` — CS team owner assignment | CS (4.2, filtering) | Low |
| Multiple report periods stored (run ingestion each period) | AM (trend), CS (recency) | Ongoing |

---

## Navigation Between Views

- GM View (View 2) → click on a customer → Account Manager View (View 1)
- CS Portfolio (View 4, section 4.2) → click on a customer → Account Manager View (View 1)
- Product Heatmap (View 3, section 3.1) → click on a feature → feature detail with dimension breakdown (section 3.2)
- Product Heatmap (View 3, section 3.1) → click on a customer cell → Account Manager View (View 1)
