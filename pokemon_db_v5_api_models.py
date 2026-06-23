#!/usr/bin/env python3
"""Pydantic response models for the SaveRoom Pokémon DB public v1 API.

These models describe the versioned public API contract. They intentionally sit
above the current v2 SQLite views/cache tables so those implementation details
can change without breaking external clients.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ApiError(BaseModel):
    code: str = Field(..., description="Stable machine-readable error code.")
    message: str = Field(..., description="Human-readable error message.")
    details: dict[str, Any] | None = Field(default=None, description="Optional structured debugging context.")


class ErrorResponse(BaseModel):
    error: ApiError


class PaginationMeta(BaseModel):
    limit: int
    offset: int
    count: int
    total: int
    has_more: bool


class LanguageInfo(BaseModel):
    code: str
    name: str | None = None


class SetSummaryV1(BaseModel):
    set_id: str | None = None
    core_set_id: str | None = None
    name: str | None = None
    core_name: str | None = None
    series: str | None = None
    release_date: str | None = None


class ImageInfoV1(BaseModel):
    has_exact_image: bool
    has_display_image: bool
    exact_image_url: str | None = None
    display_image_url: str | None = None
    local_display_image_url: str | None = None
    local_display_image_cache_profile: str | None = None
    local_display_image_bytes: int | None = None
    display_image_source_type: str | None = None
    display_image_source_language_code: str | None = None
    language_matches_card: bool = True


class PriceSummaryV1(BaseModel):
    currency: str = "GBP"
    evidence_count: int = 0
    recommended_raw_count: int = 0
    raw_median: float | None = None
    raw_min: float | None = None
    raw_max: float | None = None
    graded_count: int = 0
    bundle_count: int = 0
    noise_count: int = 0
    latest_fetched_at: str | None = None
    source: str | None = None
    no_evidence_reason: str | None = None
    by_condition: dict = {}
    with_postage: bool = False


class PriceEvidenceV1(BaseModel):
    id: int | None = None
    source: str | None = None
    source_site: str | None = None
    bucket: str | None = None
    price_gbp: float | None = None
    sold_date: str | None = None
    raw_title: str | None = None
    listing_url: str | None = None
    condition: str | None = None
    condition_normalized: str | None = None
    is_played: bool = False
    postage_cost: float | None = None
    ebay_item_id: str | None = None
    currency: str = "GBP"
    confidence_score: float | None = None
    is_recommended_input: bool = False
    query: str | None = None
    fetched_at: str | None = None


class ProvenanceSummaryV1(BaseModel):
    v2_record_count: int | None = None
    legacy_record_count: int | None = None
    total_count: int | None = None


class CardSummaryV1(BaseModel):
    card_key: str
    language: LanguageInfo
    card_id: str
    local_id: str | None = None
    collector_number: str | None = None
    name: str | None = None
    name_english: str | None = Field(default=None, description="English translation of the card name. Useful for non-English cards when searching on English-language marketplaces like eBay UK.")
    set: SetSummaryV1
    images: ImageInfoV1
    price: PriceSummaryV1 | None = None


class CardDetailV1(CardSummaryV1):
    category: str | None = None
    hp: int | None = None
    types: Any | None = None
    rarity: str | None = None
    stage: str | None = None
    illustrator: str | None = None
    regulation_mark: str | None = None
    variants: Any | None = None
    legal: Any | None = None
    rules_text: dict[str, Any] | None = None
    provenance: ProvenanceSummaryV1 | None = None
    price_query: str | None = Field(default=None, description="Optimal eBay UK price search query using English name and set code.")


class HealthV1(BaseModel):
    ok: bool
    service: str
    version: str
    started_at: str
    checked_at: str
    counts: dict[str, Any]
    support_status: dict[str, Any]
    auth: dict[str, Any]


class HealthResponseV1(BaseModel):
    data: HealthV1


class CardSummaryResponseV1(BaseModel):
    data: CardSummaryV1


class CardDetailResponseV1(BaseModel):
    data: CardDetailV1


class CardSearchResponseV1(BaseModel):
    data: list[CardSummaryV1]
    pagination: PaginationMeta

class SetDetailV1(BaseModel):
    set_id: str
    core_set_id: str | None = None
    name: str | None = None
    core_name: str | None = None
    series: str | None = None
    release_date: str | None = None
    logo_url: str | None = None
    symbol_url: str | None = None
    abbreviation: str | None = None
    official_count: int | None = None
    total_count: int | None = None
    normal_count: int | None = None
    holo_count: int | None = None
    reverse_count: int | None = None
    first_ed_count: int | None = None
    language_code: str | None = None
    language_name: str | None = None
    card_count: int | None = None


class SetListResponseV1(BaseModel):
    data: list[SetDetailV1]
    pagination: PaginationMeta


class SetDetailResponseV1(BaseModel):
    data: SetDetailV1


class LanguageDetailV1(BaseModel):
    code: str
    name: str | None = None
    set_count: int | None = None
    card_count: int | None = None


class LanguageListResponseV1(BaseModel):
    data: list[LanguageDetailV1]


class ImageDetailResponseV1(BaseModel):
    data: ImageInfoV1
    card_key: str
    language_code: str
    card_id: str


class PriceSummaryResponseV1(BaseModel):
    data: PriceSummaryV1
    card_key: str
    language_code: str
    card_id: str


class PriceHistoryResponseV1(BaseModel):
    data: list[PriceEvidenceV1]
    pagination: PaginationMeta
    card_key: str
    language_code: str
    card_id: str


class ApiKeyCreateV1(BaseModel):
    label: str | None = None
    scopes: list[str] = ['cards:read']
    monthly_quota: int | None = None


class ApiKeyCreatedV1(BaseModel):
    id: int
    key: str
    label: str | None = None
    scopes: list[str]
    monthly_quota: int | None = None
    is_active: bool
    created_at: str


class ApiKeyCreatedResponseV1(BaseModel):
    data: ApiKeyCreatedV1


class ApiKeyListItemV1(BaseModel):
    id: int
    label: str | None = None
    scopes: list[str]
    monthly_quota: int | None = None
    is_active: bool
    created_at: str
    last_used_at: str | None = None


class ApiKeyListResponseV1(BaseModel):
    data: list[ApiKeyListItemV1]


class QuotaStatusV1(BaseModel):
    api_key_id: int
    monthly_quota: int | None = None
    used_this_month: int
    remaining: int | None = None
    window_start: str
    window_end: str


class QuotaStatusResponseV1(BaseModel):
    data: QuotaStatusV1


# ── v8 Pricing Evidence Models ──────────────────────────────────────

class PriceSourceV1(BaseModel):
    provider: str = "RapidAPI eBay Average Selling Price"
    observation_type: str = "active_listing"
    description: str = "eBay marketplace listing observations"


class PriceMatchingV1(BaseModel):
    confidence: str
    confidence_score: float | None = None
    confidence_reasons: list[str] | None = None
    confidence_weaknesses: list[str] | None = None
    exact_match_listings: int | None = None
    variant_match_listings: int | None = None
    identity_unknown_listings: int | None = None
    no_match_listings: int | None = None


class PriceSelectionV1(BaseModel):
    raw_eligible: int | None = None
    graded_eligible: int | None = None
    duplicates_excluded: int | None = None
    condition_excluded: int | None = None
    postage_excluded: int | None = None
    identity_excluded: int | None = None


class PriceQueryUsedV1(BaseModel):
    primary: str
    fallback: str | None = None


class PriceRecommendationV1(BaseModel):
    basis: str = "raw_exact_match_median"
    typical_raw_price_gbp: float | None = None
    typical_range_gbp: list[float | None] | None = None
    notes: str | None = None


class PriceSnapshotV1(BaseModel):
    currency: str = "GBP"
    recommended_price: float | None = None
    median_price: float | None = None
    mean_price: float | None = None
    minimum_price: float | None = None
    maximum_price: float | None = None
    sample_size: int | None = None
    confidence_score: float | None = None
    confidence_label: str | None = None
    algorithm_version: str | None = None


# ── v9 Inventory Models ─────────────────────────────────────────────

class ItemImageResponse(BaseModel):
    image_id: int
    item_id: str
    image_type: str | None = None
    image_url: str | None = None
    image_local_path: str | None = None
    is_primary: bool = False
    uploaded_at: str | None = None
    created_by: str | None = None


class SellableSKUIdentity(BaseModel):
    sku_id: int
    sku_key: str | None = None
    language_code: str | None = None
    condition_code: str | None = None
    set_code: str | None = None
    collector_number: str | None = None
    name_english: str | None = None


class TransactionSummary(BaseModel):
    transaction_id: int
    transaction_type: str
    from_location: str | None = None
    to_location: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    price: float | None = None
    currency: str | None = None
    reference: str | None = None
    notes: str | None = None
    created_by: str | None = None
    created_at: str


class PhysicalItemResponse(BaseModel):
    item_id: str
    sku_id: int
    sku_identity: SellableSKUIdentity | None = None
    revision: int = 0
    certification_number: str | None = None
    certification_company: str | None = None
    certification_grade: float | None = None
    certification_qualifier: str | None = None
    item_condition: str | None = None
    acquired_date: str | None = None
    acquired_price: float | None = None
    acquired_currency: str | None = None
    acquired_source: str | None = None
    acquired_source_reference: str | None = None
    location_code: str | None = None
    location_detail: str | None = None
    status: str | None = None
    notes: str | None = None
    current_value: float | None = None
    current_value_currency: str = "GBP"
    images: list[ItemImageResponse] = []
    last_transaction: TransactionSummary | None = None
    tenant_id: int = 1
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class TransactionResponse(BaseModel):
    transaction_id: int
    item_id: str
    transaction_type: str
    quantity: int = 1
    from_location: str | None = None
    to_location: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    price: float | None = None
    currency: str | None = None
    counterparty: str | None = None
    counterparty_id: str | None = None
    reference: str | None = None
    notes: str | None = None
    price_observation_id: int | None = None
    price_snapshot_id: int | None = None
    tenant_id: int = 1
    created_by: str | None = None
    created_at: str | None = None


class InventoryItemCreate(BaseModel):
    sku_id: int = Field(..., description="Required: FK to sellable_skus")
    certification_number: str | None = None
    certification_company: str | None = None
    certification_grade: float | None = None
    certification_qualifier: str | None = None
    item_condition: str = "Near Mint"
    acquired_date: str | None = None
    acquired_price: float | None = None
    acquired_currency: str = "GBP"
    acquired_source: str | None = None
    acquired_source_reference: str | None = None
    location_code: str = "Unknown"
    location_detail: str | None = None
    status: str = "owned"
    notes: str | None = None
    price_observation_id: int | None = None
    price_snapshot_id: int | None = None


class InventoryItemUpdate(BaseModel):
    item_condition: str | None = None
    notes: str | None = None
    location_code: str | None = None
    location_detail: str | None = None


class InventoryStatusChange(BaseModel):
    status: str = Field(..., description="New status: owned, consigned, sold, lost, returned, etc.")
    price: float | None = None
    currency: str = "GBP"
    counterparty: str | None = None
    reference: str | None = None
    notes: str | None = None
    price_observation_id: int | None = None
    price_snapshot_id: int | None = None


class InventoryLocationChange(BaseModel):
    location_code: str
    location_detail: str | None = None
    notes: str | None = None


class InventoryTransactionCreate(BaseModel):
    transaction_type: str
    quantity: int = 1
    to_location: str | None = None
    to_status: str | None = None
    price: float | None = None
    currency: str = "GBP"
    counterparty: str | None = None
    reference: str | None = None
    notes: str | None = None
    price_observation_id: int | None = None
    price_snapshot_id: int | None = None


class InventoryLocationList(BaseModel):
    location_code: str
    item_count: int
    status_summary: dict[str, int]


class InventoryValuationBreakdown(BaseModel):
    raw_items: int = 0
    graded_items: int = 0
    total_items: int = 0


class InventoryValuation(BaseModel):
    currency: str = "GBP"
    acquisition_cost_total_minor: int = 0
    current_market_value_total_minor: int = 0
    realised_sales_total_minor: int = 0
    valued_item_count: int = 0
    unvalued_item_count: int = 0
    stale_valuation_count: int = 0
    valuation_source: str = "v8 price snapshots"
    external_requests_used: int = 0
    total_items: int = 0


class TenantResponse(BaseModel):
    tenant_id: int
    tenant_name: str
    tenant_slug: str
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class TenantCreate(BaseModel):
    tenant_name: str
    tenant_slug: str
    is_active: bool = True
    owner_username: str | None = None
    owner_email: str | None = None


class UserResponse(BaseModel):
    user_id: int
    tenant_id: int
    username: str
    email: str | None = None
    role: str = "viewer"
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class UserCreate(BaseModel):
    username: str
    email: str | None = None
    password: str = ""
    role: str = "viewer"
    is_active: bool = True


class InventoryListResponse(BaseModel):
    data: list[PhysicalItemResponse]
    pagination: dict[str, Any]


class InventoryItemResponse(BaseModel):
    data: PhysicalItemResponse


class TransactionListResponse(BaseModel):
    data: list[TransactionResponse]
    pagination: dict[str, Any]


class TenantListResponse(BaseModel):
    data: list[TenantResponse]


class TenantDetailResponse(BaseModel):
    data: TenantResponse


class UserListResponse(BaseModel):
    data: list[UserResponse]


class InventoryValuationResponse(BaseModel):
    data: InventoryValuation


class PriceSnapshotRefV1(BaseModel):
    """Minimal price snapshot reference for linking to v8 pricing evidence."""
    snapshot_id: int | None = None
    observation_id: int | None = None
    price: float | None = None
    currency: str = "GBP"
    confidence_label: str | None = None
    algorithm_version: str | None = None


class PriceFetchResponseV1(BaseModel):
    success: bool
    query: str
    query_used: str
    language: str | None = None
    card_id: str | None = None
    cached: bool
    algorithm_version: str | None = None
    cost_guard: dict[str, Any]
    total_results: int | None = None
    products: list[dict[str, Any]]
    summary: dict[str, Any]
    recommendation: PriceRecommendationV1
    matching: PriceMatchingV1
    selection: PriceSelectionV1 | None = None
    source: PriceSourceV1 | None = None
    outliers: dict[str, Any]


# ── v9.1 Image Gateway Models ────────────────────────────────────────

class DeliveryPolicyArticle(BaseModel):
    """A single delivery policy entry."""
    policy_id: int
    scope_type: str
    scope_value: str
    external_display_enabled: bool
    reason: str | None = None
    attribution_text: str | None = None
    created_at: str
    updated_at: str


class DeliveryPolicyCreate(BaseModel):
    scope_type: str = Field(..., description="Global, source, language, set, card, image")
    scope_value: str
    external_display_enabled: bool
    reason: str | None = None
    attribution_text: str | None = None


class DeliveryPolicyUpdate(BaseModel):
    external_display_enabled: bool
    reason: str | None = None
    attribution_text: str | None = None


class DeliveryPolicyListResponse(BaseModel):
    data: list[DeliveryPolicyArticle]


class DeliveryPolicyArticleResponse(BaseModel):
    data: DeliveryPolicyArticle


class TakedownCaseCreate(BaseModel):
    requester_identity: str = Field(..., description="Name or email of the requester")
    requester_contact: str = Field(..., description="Contact email or phone")
    rights_description: str | None = None


class TakedownCaseResolve(BaseModel):
    resolution: str = Field(..., description="restore or remove")
    resolution_summary: str | None = None


class TakedownEventResponse(BaseModel):
    event_id: int
    case_id: int
    action_type: str
    scope_type: str | None = None
    scope_value: str | None = None
    actor_membership_id: int | None = None
    reason: str | None = None
    created_at: str


class TakedownCaseResponse(BaseModel):
    case_id: int
    requester_identity: str
    requester_contact: str
    rights_description: str | None = None
    status: str
    opened_at: str
    resolved_at: str | None = None
    resolution_summary: str | None = None
    events: list[TakedownEventResponse] = []


class TakedownCaseListResponse(BaseModel):
    data: list[TakedownCaseResponse]


class ImageContentResponse(BaseModel):
    """Binary content response — not directly used as a Pydantic model
    but returned as StreamingResponse in the gateway route."""
    pass


class DeliveryLogEntry(BaseModel):
    log_id: int
    image_id: int | None = None
    card_key: str | None = None
    tenant_id: int | None = None
    api_key_id: int | None = None
    size: str | None = None
    policy_decision: str
    response_status: int
    response_outcome: str
    created_at: str


class SignedUrlResponse(BaseModel):
    url: str
    expires_at: str
    image_id: int
    size: str


class SignedUrlResponseArticle(BaseModel):
    data: SignedUrlResponse

