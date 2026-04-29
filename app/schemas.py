from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── TAXONOMY / CATALOG ────────────────────────────────────────────────────────

class DimensionDef(BaseModel):
    name: str
    type: str
    required: bool = False
    description: Optional[str] = None
    values: Optional[List[str]] = None


class AggregationDef(BaseModel):
    type: str
    label: str
    dimension: Optional[str] = None


class AvailabilityDef(BaseModel):
    introduced_in: Optional[str] = None
    deprecated_in: Optional[str] = None
    version_tier_override: Optional[str] = None


class FeatureDef(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    category: str
    tier: Optional[str] = None
    status: Optional[str] = None
    availability: Optional[AvailabilityDef] = None
    tracking: Dict[str, Any]


class CategoryDef(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    sub_categories: List["CategoryDef"] = Field(default_factory=list)


CategoryDef.update_forward_refs()


class ProductMeta(BaseModel):
    id: str
    name: str
    version: str
    description: Optional[str] = None
    team_owner: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = True


class TaxonomySchema(BaseModel):
    schema: Dict[str, Any]
    product: ProductMeta
    categories: List[CategoryDef]
    features: List[FeatureDef]


class CatalogReleaseResponse(BaseModel):
    product_id: str
    version: str
    name: str
    description: Optional[str]
    team_owner: Optional[str]
    category: Optional[str]
    is_active: bool


# ── CUSTOMER ──────────────────────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    id: str = Field(..., description="Unique slug for this customer, e.g. 'acme-corp'")
    name: str
    region: Optional[str] = None
    tier: Optional[str] = None


class CustomerResponse(BaseModel):
    id: str
    name: str
    region: Optional[str]
    tier: Optional[str]


# ── DEPLOYMENT ────────────────────────────────────────────────────────────────

class DeploymentCreate(BaseModel):
    id: str = Field(..., description="Unique deployment ID, e.g. 'acme-corp-prod-us'")
    customer_id: str
    product_id: str
    version: str
    environment: Optional[str] = Field(None, description="prod | staging | dev")


class DeploymentResponse(BaseModel):
    id: str
    customer_id: str
    product_release_id: int
    environment: Optional[str]


# ── UTILIZATION REPORT (YAML ingest) ─────────────────────────────────────────
#
# The product sends a YAML file that extends the base taxonomy format with:
#   - A top-level `deployment` block identifying the sending deployment
#   - A top-level `report` block with the reporting period
#   - Per-feature `utilization` blocks with total_count + dimension_breakdown
#
# Example YAML:
#
#   product:
#     id: "identity-server"
#     version: "7.2.0"
#
#   deployment:
#     id: "acme-corp-prod-us"
#     customer_id: "acme-corp"
#
#   report:
#     from: "2026-03-01T00:00:00Z"
#     to:   "2026-03-31T23:59:59Z"
#
#   features:
#     - code: "is.sso.oidc"
#       utilization:
#         total_count: 15000
#         dimension_breakdown:
#           grant_type:
#             authorization-code: 12000
#             client-credentials: 3000

class FeatureUtilizationData(BaseModel):
    total_count: int = 0
    dimension_breakdown: Dict[str, Any] = Field(default_factory=dict)


class UtilizationFeatureEntry(BaseModel):
    code: str
    utilization: Optional[FeatureUtilizationData] = None


class DeploymentRef(BaseModel):
    id: str
    customer_id: str


class ReportPeriod(BaseModel):
    # field named `from` clashes with Python keyword — use alias
    period_from: datetime = Field(..., alias="from")
    period_to: datetime = Field(..., alias="to")

    class Config:
        populate_by_name = True


class UtilizationReportYAML(BaseModel):
    product: ProductMeta
    deployment: DeploymentRef
    report: ReportPeriod
    features: List[UtilizationFeatureEntry]


class UtilizationReportResponse(BaseModel):
    id: int
    deployment_id: str
    customer_id: str
    product_id: str
    version: str
    report_from: datetime
    report_to: datetime
    features_recorded: int


# ── REAL-TIME EVENT (existing, kept for completeness) ─────────────────────────

class FeatureUsageEventCreate(BaseModel):
    product_id: str
    version: str
    event_name: str
    platform: Optional[str] = None
    dimensions: Dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    event_timestamp: Optional[datetime] = None
