-- PostgreSQL schema for feature catalog and usage tracking

CREATE TABLE product_release (
    id SERIAL PRIMARY KEY,
    product_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT,
    team_owner TEXT,
    category TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    metadata_json JSONB,
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, version)
);

CREATE TABLE catalog_category (
    id SERIAL PRIMARY KEY,
    product_release_id INTEGER NOT NULL REFERENCES product_release(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    parent_category_id INTEGER REFERENCES catalog_category(id) ON DELETE CASCADE,
    UNIQUE (product_release_id, code)
);

CREATE TABLE catalog_feature (
    id SERIAL PRIMARY KEY,
    product_release_id INTEGER NOT NULL REFERENCES product_release(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    category_code TEXT NOT NULL,
    event_name TEXT NOT NULL,
    event_category TEXT,
    platforms TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_release_id, code)
);

CREATE TABLE feature_tracking_dimension (
    id SERIAL PRIMARY KEY,
    feature_id INTEGER NOT NULL REFERENCES catalog_feature(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    required BOOLEAN NOT NULL DEFAULT false,
    description TEXT,
    enum_values TEXT[]
);

CREATE TABLE feature_tracking_aggregation (
    id SERIAL PRIMARY KEY,
    feature_id INTEGER NOT NULL REFERENCES catalog_feature(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    dimension TEXT
);

-- ── CATALOG FEATURE ENHANCEMENTS ──────────────────────────────────────────
-- Add tier/status/availability fields per the full taxonomy schema spec

ALTER TABLE catalog_feature ADD COLUMN IF NOT EXISTS tier TEXT;
ALTER TABLE catalog_feature ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE catalog_feature ADD COLUMN IF NOT EXISTS introduced_in TEXT;
ALTER TABLE catalog_feature ADD COLUMN IF NOT EXISTS deprecated_in TEXT;

-- ── CUSTOMER & DEPLOYMENT ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS customer (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT,
    tier TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS deployment (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customer(id),
    product_release_id INTEGER NOT NULL REFERENCES product_release(id),
    environment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── UTILIZATION REPORTING ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS utilization_report (
    id SERIAL PRIMARY KEY,
    deployment_id TEXT NOT NULL REFERENCES deployment(id),
    report_from TIMESTAMPTZ NOT NULL,
    report_to TIMESTAMPTZ NOT NULL,
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feature_utilization (
    id SERIAL PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES utilization_report(id) ON DELETE CASCADE,
    catalog_feature_id INTEGER NOT NULL REFERENCES catalog_feature(id),
    feature_code TEXT NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    total_count INTEGER NOT NULL DEFAULT 0,
    dimension_breakdown JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feature_utilization_report ON feature_utilization(report_id);
CREATE INDEX IF NOT EXISTS idx_feature_utilization_feature ON feature_utilization(catalog_feature_id);
CREATE INDEX IF NOT EXISTS idx_utilization_report_deployment ON utilization_report(deployment_id);

CREATE TABLE IF NOT EXISTS feature_usage_event (
    id SERIAL PRIMARY KEY,
    product_release_id INTEGER NOT NULL REFERENCES product_release(id) ON DELETE RESTRICT,
    feature_id INTEGER NOT NULL REFERENCES catalog_feature(id) ON DELETE RESTRICT,
    event_name TEXT NOT NULL,
    platform TEXT,
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dimensions JSONB,
    user_id TEXT,
    tenant_id TEXT,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_feature_usage_event_feature ON feature_usage_event(feature_id);
CREATE INDEX idx_feature_usage_event_release ON feature_usage_event(product_release_id);
CREATE INDEX idx_feature_usage_event_event_name ON feature_usage_event(event_name);
