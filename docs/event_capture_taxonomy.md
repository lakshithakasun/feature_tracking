# WSO2 Feature Utilization — Event Capture Taxonomy Specification
**Document version:** 1.1  
**Status:** Reference guidance for the current repository and taxonomy structure

---

## Purpose

This document defines the standard structure and vocabulary for the `tracking` block in product taxonomy YAML files. It establishes what each field means, what values are allowed, and how the product should capture and report utilization data for each feature.

The taxonomy YAML already contains the `tracking` block on every feature. However, the fields within it are currently applied inconsistently. This document serves as the agreed reference before any further taxonomy updates or tooling is built against this format.

Although the original examples were Identity Server oriented, the repository now also includes APIM sample taxonomies and demo data. The same structural guidance applies across products.

---

## Scope

This specification applies to the `tracking` block within each feature entry in the taxonomy YAML. It does not define the utilization report format (that is a separate agreed format), but it does define what data the product is expected to collect and report via that format.

---

## Full Structure Reference

The complete `tracking` block for a feature looks like this:

```yaml
tracking:
  event_name: "is.sso.oidc"
  event_category: "runtime"
  capture_mode: "batch_report"
  platforms: ["web", "api", "mobile-ios", "mobile-android"]

  dimensions:
    - name: "grant_type"
      display_name: "OAuth Grant Type"
      description: "The OAuth 2.0 grant type used in this authorization request."
      type: "enum"
      values: ["authorization-code", "client-credentials", "device-code"]
      failure_values: []
      required: true
      pii: false

    - name: "pkce_enabled"
      display_name: "PKCE Used"
      description: "Whether PKCE was used to protect the authorization code flow."
      type: "boolean"
      required: false
      pii: false

  aggregations:
    - type: "count"
      label: "OIDC SSO Logins"

    - type: "count_distinct"
      dimension: "grant_type"
      label: "Grant Types in Use"
```

---

## Field Reference

### `event_name`

**Type:** string  
**Required:** yes

The canonical identifier for the event emitted when this feature is used. This is the key used in the utilization report YAML to associate reported counts back to this feature in the catalog.

**Convention:** `is.<category-id>.<action>`  
**Examples:** `is.sso.oidc`, `is.mfa.totp`, `is.provisioning.outbound`

The event name must be unique across all features in all versions of the taxonomy. It must not change between versions — if a feature is renamed, the event_name stays the same to preserve historical continuity.

---

### `event_category`

**Type:** enum  
**Required:** yes  
**Allowed values:** `runtime` | `enrollment` | `lifecycle` | `configuration`

Classifies the nature of events this feature produces. This is used by the product team to group features by usage type and understand where usage is coming from.

| Value | Meaning | Typical features |
|---|---|---|
| `runtime` | Events triggered during active user authentication or authorization flows. Occur at high frequency in production. | SSO logins, MFA verifications, token exchanges, adaptive auth evaluations, federation logins |
| `enrollment` | Events where a user or admin sets up a feature for the first time — enabling it for ongoing use. Occur at low frequency, signal adoption uptake. | Passkey enroll, TOTP enroll, MFA device registration, self-registration, JIT provisioning |
| `lifecycle` | Administrative events managing entities — users, groups, applications, roles. Driven by IT admin operations. | User create/update/delete, group management, app registration, role assignment |
| `configuration` | One-time or infrequent system-level setup events. Occur at very low frequency and indicate how the deployment is configured. | User store setup, external IdP connection, password policy configuration, webhook registration |

**Note on the current taxonomy:** The current taxonomy uses `engagement`, `adoption`, and `lifecycle` inconsistently. These will be migrated to the four categories above. The mapping is: `engagement` → `runtime`, `adoption` → `enrollment` or `runtime` depending on the feature, `lifecycle` stays as `lifecycle`.

---

### `capture_mode`

**Type:** enum  
**Required:** yes  
**Allowed values:** `batch_report` | `real_time_event` | `both`

Defines how the product emits data for this feature.

| Value | Meaning |
|---|---|
| `batch_report` | The product aggregates counts for this feature over the reporting period and includes them in the periodic utilization report YAML. This is the standard mode for all features. |
| `real_time_event` | The product emits an individual event record at the time the action occurs. Used for features where immediate visibility matters (e.g. account lockout, session revocation). |
| `both` | The product both emits real-time events AND includes the aggregated count in the batch report. |

**Default for most features:** `batch_report`

Real-time events are stored in the `feature_usage_event` table. Batch report data is stored in `feature_utilization`. When `capture_mode` is `both`, both tables receive data.

---

### `platforms`

**Type:** list of enum  
**Required:** yes  
**Allowed values:** `web` | `api` | `mobile-ios` | `mobile-android` | `desktop` | `cli`

Lists the platform contexts in which this feature can generate events. This documents where the product is capable of capturing usage for this feature.

| Value | Meaning |
|---|---|
| `web` | Browser-based flows — login pages, My Account portal, admin console |
| `api` | Direct API calls — management APIs, SCIM, token endpoints called without a browser |
| `mobile-ios` | iOS native application using the WSO2 iOS SDK |
| `mobile-android` | Android native application using the WSO2 Android SDK |
| `desktop` | Desktop application or Electron app |
| `cli` | Command-line tooling (e.g. asgardeo-cli, admin scripts) |

**Important:** The `platforms` field documents which platforms CAN generate events. It does not mean all those platforms will appear in every customer's reported data. A customer who only has web applications will only have `web` events even if the feature supports `mobile-ios`.

**Suggestion:** Platform should also be captured as an implicit dimension in the utilization report's `dimension_breakdown`. If a feature is used across multiple platforms, the report should break down counts by platform. See the Implicit Dimensions section below.

---

## Dimensions

The `dimensions` block defines the contextual attributes that accompany each event. In the utilization report, these appear in the `dimension_breakdown` map — for each dimension, the report includes a count per value seen in the reporting period.

Each dimension has the following fields:

---

### `name`

**Type:** string  
**Required:** yes

The machine-readable key for this dimension. Used as the key in the `dimension_breakdown` JSON in the utilization report.

**Convention:** lowercase with underscores — `grant_type`, `recovery_method`, `store_type`

---

### `display_name`

**Type:** string  
**Required:** yes

A human-readable label for this dimension. Shown in report UIs and charts where the raw `name` would be unclear to non-technical viewers.

**Example:** `name: "grant_type"` → `display_name: "OAuth Grant Type"`

---

### `description`

**Type:** string  
**Required:** yes

A plain English explanation of what this dimension captures and why it is useful. This is the documentation for the product engineering team implementing the tracking instrumentation.

---

### `type`

**Type:** enum  
**Required:** yes  
**Allowed values:** `enum` | `boolean` | `integer` | `string`

The data type of this dimension's values.

| Type | How it appears in dimension_breakdown | When to use |
|---|---|---|
| `enum` | `{ "value_a": 1500, "value_b": 300 }` — count per value | When the set of possible values is known and bounded. Always prefer `enum` over `string`. |
| `boolean` | `{ "true": 1200, "false": 800 }` — count per true/false | For on/off flags (PKCE enabled, encryption on). |
| `integer` | `{ "total": 4500 }` — sum of values | For numeric counts or sizes (e.g. number of users in a bulk import). Aggregated as a sum, not a per-value breakdown. |
| `string` | Not recommended for dimension_breakdown | Free-text strings should be avoided as dimensions — high cardinality breaks aggregation. Only use if absolutely necessary and document why. |

---

### `values`

**Type:** list of string  
**Required:** yes, when `type` is `enum`  
**Not applicable for:** `boolean`, `integer`, `string`

The complete list of allowed values for an `enum` dimension. The product must not emit values outside this list. If a new value is needed, it must be added to the taxonomy first.

Having a closed `values` list serves two purposes:
1. The product engineering team knows exactly what to instrument
2. The reporting system can validate incoming data and flag unexpected values

---

### `failure_values`

**Type:** list of string  
**Required:** yes, when `type` is `enum` and any values represent a failed or errored outcome  
**Default:** `[]` (empty list — no failure values)

A subset of `values` that represent a failed, errored, or denied outcome for this event. Used by the reporting layer to identify operational issues without hardcoding failure keyword lists.

**Examples:**
```yaml
# For is.mfa.totp
dimensions:
  - name: "action"
    values: ["enroll", "verify", "verify-failed"]
    failure_values: ["verify-failed"]

# For is.mfa.email-otp
dimensions:
  - name: "action"
    values: ["sent", "verified", "verify-failed", "expired"]
    failure_values: ["verify-failed", "expired"]

# For is.sso.oidc (grant_type has no failure values — failures are a separate event)
dimensions:
  - name: "grant_type"
    values: ["authorization-code", "client-credentials", "device-code"]
    failure_values: []
```

---

### `required`

**Type:** boolean  
**Required:** yes

Whether the product must always include this dimension in the utilization report for this feature. If `required: true`, a report that includes this feature but omits this dimension is considered incomplete.

Set `required: false` for dimensions that are only relevant in certain deployment configurations (e.g. `sms_provider` is only relevant when SMS OTP is configured with a specific provider).

---

### `pii`

**Type:** boolean  
**Required:** yes  
**Default:** `false`

Whether this dimension could contain or be derived from personally identifiable information.

**Currently all dimensions in the taxonomy are `pii: false`** — the taxonomy is designed to capture aggregate counts and dimension distributions, never individual user identifiers, IP addresses, email addresses, or similar. If a proposed dimension would require PII to compute, it should not be included.

Mark `pii: true` to flag a dimension for review — such dimensions require explicit approval before being added.

---

## Aggregations

The `aggregations` block defines higher-level computations that the reporting layer should produce for this feature, beyond the raw dimension breakdown counts. These are the metrics that appear in report summaries, dashboards, and the product team view.

Note: The per-value counts in `dimension_breakdown` are automatic for every `enum` and `boolean` dimension. Aggregations are additional rollups defined explicitly per feature.

Each aggregation has the following fields:

---

### `type: "count"`

Total number of events for this feature in the reporting period.

```yaml
aggregations:
  - type: "count"
    label: "OIDC SSO Logins"
```

Every feature must have at least one `count` aggregation. This is the primary metric for feature utilization.

---

### `type: "count_distinct"`

The number of distinct values seen for a specific dimension during the reporting period. Used to understand the breadth of a feature's usage.

```yaml
aggregations:
  - type: "count_distinct"
    dimension: "grant_type"
    label: "Grant Types in Use"
```

**`dimension`** (required): The dimension name to count distinct values for.

**When to use:** When it is useful to know not just how many events occurred, but how many different ways the feature was used. For example, a customer using three different grant types (authorization-code, client-credentials, device-code) indicates deeper OIDC adoption than a customer only using one.

---

### `type: "sum"`

The sum of values for an `integer` dimension across all events in the reporting period.

```yaml
aggregations:
  - type: "sum"
    dimension: "user_count"
    label: "Total Users Imported"
```

**`dimension`** (required): Must be an `integer` type dimension.

**When to use:** When a single event represents a batch operation with a volume (e.g. a bulk import event that includes the number of users imported). The sum gives the total volume across all batches in the period.

---

### `type: "ratio"`

The proportion of events where a specific dimension has specific values, expressed as a fraction of total events for this feature.

```yaml
aggregations:
  - type: "ratio"
    label: "PKCE Usage Rate"
    dimension: "pkce_enabled"
    numerator_values: [true]
```

**`dimension`** (required): The dimension to evaluate.  
**`numerator_values`** (required): The dimension values that form the numerator.  

The denominator is always the total event count for the feature.

**When to use:** When a dimension represents adoption of a best practice or sub-variant, and the product team wants to track how broadly it is being used. For example, tracking what fraction of OIDC flows use PKCE, or what fraction of SAML assertions are encrypted.

---

## Implicit Dimensions

Beyond the explicitly declared dimensions, the following fields are expected on every event and are not declared per-feature because they apply universally:

| Implicit dimension | Source | Notes |
|---|---|---|
| `platform` | The platform context of the event (`web`, `api`, `mobile-ios`, etc.) | Should be included in `dimension_breakdown` for features with more than one platform |
| `report_period` | `report.from` and `report.to` in the utilization YAML | Not a dimension on individual events but the period context for all counts |

The product should include `platform` in `dimension_breakdown` for any feature that is used across multiple platforms. For features that only ever run on one platform (e.g. `web`-only features), platform breakdown is not required.

---

## Naming Conventions

| Field | Convention | Example |
|---|---|---|
| `event_name` | `is.<category-id>.<action>`, lowercase, hyphen-separated words | `is.mfa.totp`, `is.social-login.google` |
| `dimension.name` | lowercase, underscore-separated | `grant_type`, `recovery_method` |
| `dimension.values` | lowercase, hyphen-separated | `authorization-code`, `verify-failed`, `http-post` |
| `aggregation.label` | Title Case, describing what is being counted | `"OIDC SSO Logins"`, `"Grant Types in Use"` |

---

## Issues in the Current Taxonomy

The following inconsistencies exist in `taxonomy-7.2.yaml` and `taxonomy-7.3.0.yaml` and need to be resolved during the next taxonomy update:

| Issue | Scope | Resolution |
|---|---|---|
| `event_category` uses `engagement`, `adoption`, `lifecycle` — not the four categories defined above | All features | Migrate: `engagement` → `runtime`; `adoption` → `enrollment` or `runtime` (case by case); `lifecycle` stays; add `configuration` where applicable |
| `capture_mode` field is absent from all features | All features | Add `capture_mode: "batch_report"` to all existing features; mark real-time candidates (e.g. `is.governance.account-lock`) |
| `display_name` missing from all dimensions | All features | Add to each dimension during next taxonomy revision |
| `description` missing from most dimensions | Most features | Add to all required dimensions; optional for self-evident dimensions |
| `failure_values` field absent | All features | Add to all enum dimensions that contain failure-outcome values |
| `pii: false` not declared | All dimensions | Add to all dimensions explicitly |
| `introduced_in` not set in `availability` block | All features in v7.2.0 taxonomy | Backfill with `introduced_in: "7.2.0"` (or earlier version if known) |
| `tier` and `status` not set on all features | Most features | Add to all features — required for tier-based filtering across stakeholder views |

---

## Annotated Complete Example

The following is a complete, correctly structured feature entry showing all fields in use:

```yaml
- code: "is.mfa.totp"
  name: "TOTP (Authenticator App)"
  description: "Time-based one-time password authentication using apps like Google Authenticator."
  category: "mfa"
  tier: "core"
  status: "stable"
  availability:
    introduced_in: "7.2.0"

  tracking:
    event_name: "is.mfa.totp"
    event_category: "runtime"       # Verification events occur at runtime during login
    capture_mode: "batch_report"    # Aggregated counts sent in periodic report
    platforms: ["web", "mobile-ios", "mobile-android"]

    dimensions:
      - name: "action"
        display_name: "TOTP Action"
        description: "Whether this event was an enroll (first setup) or a verification attempt."
        type: "enum"
        values: ["enroll", "verify", "verify-failed"]
        failure_values: ["verify-failed"]   # verify-failed indicates a failed verification
        required: true
        pii: false

    aggregations:
      - type: "count"
        label: "TOTP Authentications"

      - type: "ratio"
        label: "TOTP Failure Rate"
        dimension: "action"
        numerator_values: ["verify-failed"]
        # Proportion of TOTP attempts that failed — useful for product quality monitoring
```

---

## Open Questions for Sign-Off

Before the taxonomy is updated to this format, the following questions need answers from the Identity Server Engineering Team:

1. **`capture_mode` for security events** — Should `is.governance.account-lock`, `is.governance.session-management`, and similar governance features be `real_time_event` or `batch_report`? Real-time enables immediate alerting but adds product-side complexity.

2. **Platform as an implicit dimension** — Should the product explicitly include platform in `dimension_breakdown` for multi-platform features, or is the `platforms` list (stating what COULD be captured) sufficient for now?

3. **`introduced_in` source of truth** — Should `introduced_in` be filled in as part of the release process (product team updates the YAML before each release), or should it be derived from when a feature first appears in the taxonomy?

4. **`failure_values` validation** — Should the ingestion system reject a utilization report that contains a value in a `failure_values` list? Or are failure values valid data that should be stored and surfaced in reporting?

5. **Integer dimension aggregation in the report** — For `integer` type dimensions (e.g. `user_count` in bulk import), should the utilization report send the raw sum, or should it send the full distribution? Current `dimension_breakdown` format stores per-value counts, which does not work for integer dimensions.
