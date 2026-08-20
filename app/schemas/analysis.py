"""Pydantic contracts for the internal crawl-analysis API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QualityReportItem(BaseModel):
    id: int
    crawl_job_id: int
    report_schema_version: int
    trade_date: date | None
    job_type: str
    job_status: str
    symbols_total: int
    symbols_succeeded: int
    symbols_failed: int
    failure_event_count: int
    success_rate: float
    coverage_rate: float
    error_distribution: dict[str, Any]
    repeated_failure_summary: dict[str, Any]
    anomaly_summary: dict[str, Any]
    sample_refs: dict[str, Any]
    source_snapshot: dict[str, Any]
    report_hash: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnalysisFailureItem(BaseModel):
    id: int
    job_id: int
    target_type: str
    target_key: str
    http_status: int | None
    response_bytes: int | None
    error_class: str
    error_message: str
    retry_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnalysisTargetResultItem(BaseModel):
    id: int
    job_id: int
    step_name: str
    target_type: str
    target_key: str
    status: str
    provider: str | None
    attempt_count: int
    rows_received: int
    rows_persisted: int
    latest_date_before: date | None
    latest_date_after: date | None
    trade_date: date | None
    http_status: int | None
    response_bytes: int | None
    error_class: str | None
    error_message: str | None
    retry_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnalysisPriceItem(BaseModel):
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    change_rate: Decimal
    source: str

    model_config = ConfigDict(from_attributes=True)


class AnalysisPriceHistoryResponse(BaseModel):
    symbol: str
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    total_count: int
    items: list[AnalysisPriceItem]

    model_config = ConfigDict(populate_by_name=True)


class AnalysisRequestCreate(BaseModel):
    request_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    idempotency_key: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    requested_by: str = Field(default="operator", min_length=1, max_length=100)
    request_kind: Literal["weekly", "ad_hoc"] = "weekly"
    completed_job_ids: list[int] = Field(default_factory=list, max_length=7)
    period_from: date | None = Field(default=None, alias="period_from")
    period_to: date | None = Field(default=None, alias="period_to")
    error_types: list[str] = Field(default_factory=list, max_length=20)
    markets: list[str] = Field(default_factory=list, max_length=4)
    sample_limit: int = Field(default=10, ge=1, le=10)
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def validate_ad_hoc_selection(self):
        if self.request_kind == "ad_hoc" and not self.completed_job_ids:
            raise ValueError("ad_hoc analysis requires completed_job_ids")
        if (self.period_from is None) != (self.period_to is None):
            raise ValueError("period_from and period_to must be supplied together")
        return self

    model_config = ConfigDict(populate_by_name=True)


class AnalysisAcceptBody(BaseModel):
    accepted_by: Literal["sam"] = "sam"


class AnalysisReportSubmit(BaseModel):
    created_by: Literal["sam"] = "sam"
    markdown_body: str = Field(min_length=1, max_length=512_000)
    report_json: dict[str, Any]
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AnalysisReportHashPreview(BaseModel):
    """Report content used to derive the server's canonical SHA-256."""

    created_by: Literal["sam"] = "sam"
    markdown_body: str = Field(min_length=1, max_length=512_000)
    report_json: dict[str, Any]


class AnalysisReportHashPreviewResponse(BaseModel):
    request_id: str
    report_hash: str


class AnalysisReportItem(BaseModel):
    id: int
    created_by: str
    analysis_window: dict[str, Any]
    quality_report_refs: list[int]
    findings: list[dict[str, Any]]
    kiwoom_evidence: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    limitations: list[str]
    markdown_body: str
    report_json: dict[str, Any]
    report_hash: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnalysisRequestItem(BaseModel):
    request_id: str
    idempotency_key: str
    requested_by: str
    request_kind: str
    status: str
    period_from: date
    period_to: date
    completed_job_ids: list[int]
    quality_report_ids: list[int]
    error_types: list[str]
    markets: list[str]
    sample_limit: int
    reason: str
    accepted_by: str | None
    requested_at: datetime
    accepted_at: datetime | None
    report: AnalysisReportItem | None = None


class AnalysisMutationResponse(BaseModel):
    request_id: str
    status: str
    accepted_by: str | None = None
    accepted_at: datetime | None = None
    report_id: int | None = None
    report_hash: str | None = None
