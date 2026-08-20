"""Request and response contracts for Sam's internal repair API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RepairClaimBody(BaseModel):
    claimed_by: str = Field(default="sam", pattern=r"^[A-Za-z0-9._-]{1,50}$")


class RepairClaimResponse(BaseModel):
    request_id: int
    claim_token: str
    claim_version: int
    attempt_no: int
    operation: Literal["daily_chart"]
    symbol: str
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    adjusted_price: bool
    lease_expires_at: datetime

    model_config = ConfigDict(populate_by_name=True)


class RepairPriceRow(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    trade_date: date
    source: Literal["kiwoom", "kiwoom_rest"]
    adjusted_price: bool
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(ge=0)
    change_rate: Decimal | None = None


class RepairCompleteBody(BaseModel):
    claim_token: str = Field(min_length=20, max_length=200)
    claim_version: int = Field(ge=1)
    operation: Literal["daily_chart"]
    symbol: str = Field(min_length=1, max_length=20)
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    adjusted_price: bool
    executor: Literal["sam"] = "sam"
    tool: Literal["kiwoomcli"] = "kiwoomcli"
    mode: Literal["demo", "real"]
    latest_date: date
    row_count: int = Field(ge=1, le=6000)
    data_complete: bool
    result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rows: list[RepairPriceRow] = Field(min_length=1, max_length=6000)
    details: dict = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class RepairFailBody(BaseModel):
    claim_token: str = Field(min_length=20, max_length=200)
    claim_version: int = Field(ge=1)
    error_code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    error_message: str = Field(min_length=1, max_length=2000)
    retryable: bool = False
    http_status: int | None = Field(default=None, ge=100, le=599)
    retry_after_seconds: int = Field(default=0, ge=0, le=86400)
    details: dict = Field(default_factory=dict)


class RepairAttemptSummary(BaseModel):
    id: int
    attempt_no: int
    executor: str
    tool: str | None
    mode: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    http_status: int | None
    error_code: str | None
    retryable: bool
    row_count: int
    latest_date: date | None
    data_complete: bool
    result_hash: str | None


class RepairRequestStatusResponse(BaseModel):
    request_id: int
    status: str
    application_status: str
    operation: str
    symbol: str
    from_date: date | None = Field(alias="from")
    to_date: date = Field(alias="to")
    error_type: str
    provider: str
    adjusted_price: bool
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime
    requested_at: datetime
    claimed_at: datetime | None
    completed_at: datetime | None
    applied_at: datetime | None
    application_error: str | None
    last_error_code: str | None
    last_error_message: str | None
    last_http_status: int | None
    result_count: int
    latest_attempt: RepairAttemptSummary | None

    model_config = ConfigDict(populate_by_name=True)


class RepairMutationResponse(BaseModel):
    request_id: int
    status: str
    application_status: str
    attempt_count: int
