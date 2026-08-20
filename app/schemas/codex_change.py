"""Contracts for user-approved Codex change audit records."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CodexChangeRequestCreate(BaseModel):
    change_request_id: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    report_id: int = Field(ge=1)
    proposal_id: str = Field(min_length=1, max_length=120)
    requested_by: str = Field(default="operator", min_length=1, max_length=100)


class CodexChangeReviewBody(BaseModel):
    action: Literal["approved", "implemented", "deferred"]
    reviewed_by: str = Field(default="operator", min_length=1, max_length=100)
    review_notes: str | None = Field(default=None, max_length=4000)


class CodexChangeResultBody(BaseModel):
    status: Literal["running", "verified", "failed"]
    codex_run_id: str | None = Field(default=None, max_length=160)
    commit_ref: str | None = Field(default=None, max_length=160)
    test_results: dict[str, Any] = Field(default_factory=dict)
    review_notes: str | None = Field(default=None, max_length=4000)


class CodexChangeRequestItem(BaseModel):
    change_request_id: str
    report_id: int
    proposal_id: str
    status: str
    requested_by: str
    approved_by: str | None
    target_files: list[str]
    change_scope: str
    risk_level: str
    verification_plan: list[str]
    codex_run_id: str | None
    commit_ref: str | None
    test_results: dict[str, Any]
    review_notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
