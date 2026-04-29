from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    TIMESTAMP,
)
from sqlalchemy.orm import relationship

from app.database import Base


class ProductRelease(Base):
    __tablename__ = "product_release"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    description = Column(Text)
    team_owner = Column(String)
    category = Column(String)
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(JSON)
    source_file = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)

    categories = relationship("CatalogCategory", back_populates="release", cascade="all, delete-orphan")
    features = relationship("CatalogFeature", back_populates="release", cascade="all, delete-orphan")
    deployments = relationship("Deployment", back_populates="release")


class CatalogCategory(Base):
    __tablename__ = "catalog_category"

    id = Column(Integer, primary_key=True, index=True)
    product_release_id = Column(Integer, ForeignKey("product_release.id", ondelete="CASCADE"), nullable=False)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    parent_category_id = Column(Integer, ForeignKey("catalog_category.id", ondelete="CASCADE"), nullable=True)

    release = relationship("ProductRelease", back_populates="categories")
    children = relationship("CatalogCategory")


class CatalogFeature(Base):
    __tablename__ = "catalog_feature"

    id = Column(Integer, primary_key=True, index=True)
    product_release_id = Column(Integer, ForeignKey("product_release.id", ondelete="CASCADE"), nullable=False)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    category_code = Column(String, nullable=False)
    tier = Column(String)                  # core | premium | enterprise
    status = Column(String)                # stable | beta | experimental | deprecated
    introduced_in = Column(String)         # version string e.g. "7.0.0"
    deprecated_in = Column(String)         # version string, null if still active
    event_name = Column(String, nullable=False)
    event_category = Column(String)
    platforms = Column(ARRAY(String))
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)

    release = relationship("ProductRelease", back_populates="features")
    dimensions = relationship("FeatureTrackingDimension", back_populates="feature", cascade="all, delete-orphan")
    aggregations = relationship("FeatureTrackingAggregation", back_populates="feature", cascade="all, delete-orphan")
    utilizations = relationship("FeatureUtilization", back_populates="catalog_feature")


class FeatureTrackingDimension(Base):
    __tablename__ = "feature_tracking_dimension"

    id = Column(Integer, primary_key=True, index=True)
    feature_id = Column(Integer, ForeignKey("catalog_feature.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    required = Column(Boolean, nullable=False, default=False)
    description = Column(Text)
    enum_values = Column(ARRAY(String))

    feature = relationship("CatalogFeature", back_populates="dimensions")


class FeatureTrackingAggregation(Base):
    __tablename__ = "feature_tracking_aggregation"

    id = Column(Integer, primary_key=True, index=True)
    feature_id = Column(Integer, ForeignKey("catalog_feature.id", ondelete="CASCADE"), nullable=False)
    type = Column(String, nullable=False)
    label = Column(String, nullable=False)
    dimension = Column(String)

    feature = relationship("CatalogFeature", back_populates="aggregations")


# ── CUSTOMER & DEPLOYMENT ─────────────────────────────────────────────────────

class Customer(Base):
    __tablename__ = "customer"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    region = Column(String)
    tier = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)

    deployments = relationship("Deployment", back_populates="customer")


class Deployment(Base):
    __tablename__ = "deployment"

    id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey("customer.id"), nullable=False)
    product_release_id = Column(Integer, ForeignKey("product_release.id"), nullable=False)
    environment = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)

    customer = relationship("Customer", back_populates="deployments")
    release = relationship("ProductRelease", back_populates="deployments")
    reports = relationship("UtilizationReport", back_populates="deployment", cascade="all, delete-orphan")


# ── UTILIZATION REPORTING ─────────────────────────────────────────────────────

class UtilizationReport(Base):
    __tablename__ = "utilization_report"

    id = Column(Integer, primary_key=True, index=True)
    deployment_id = Column(String, ForeignKey("deployment.id"), nullable=False)
    report_from = Column(TIMESTAMP(timezone=True), nullable=False)
    report_to = Column(TIMESTAMP(timezone=True), nullable=False)
    source_file = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)

    deployment = relationship("Deployment", back_populates="reports")
    feature_utilizations = relationship("FeatureUtilization", back_populates="report", cascade="all, delete-orphan")


class FeatureUtilization(Base):
    __tablename__ = "feature_utilization"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("utilization_report.id", ondelete="CASCADE"), nullable=False)
    catalog_feature_id = Column(Integer, ForeignKey("catalog_feature.id"), nullable=False)
    feature_code = Column(String, nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    total_count = Column(Integer, nullable=False, default=0)
    dimension_breakdown = Column(JSON)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)

    report = relationship("UtilizationReport", back_populates="feature_utilizations")
    catalog_feature = relationship("CatalogFeature", back_populates="utilizations")


# ── REAL-TIME USAGE EVENTS (future / streaming use case) ─────────────────────

class FeatureUsageEvent(Base):
    __tablename__ = "feature_usage_event"

    id = Column(Integer, primary_key=True, index=True)
    product_release_id = Column(Integer, ForeignKey("product_release.id", ondelete="RESTRICT"), nullable=False)
    feature_id = Column(Integer, ForeignKey("catalog_feature.id", ondelete="RESTRICT"), nullable=False)
    event_name = Column(String, nullable=False)
    platform = Column(String)
    event_timestamp = Column(TIMESTAMP(timezone=True), nullable=False)
    dimensions = Column(JSON)
    user_id = Column(String)
    tenant_id = Column(String)
    raw_payload = Column(JSON)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
