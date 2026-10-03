"""Protected browser backtest contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrategyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    config: dict[str, Any]


class StrategyVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version: int
    config: dict[str, Any]
    config_hash: str
    created_at: datetime


class StrategyResponse(BaseModel):
    strategy_id: str
    name: str
    created_at: datetime
    versions: list[StrategyVersionResponse] = []


class StrategyPatchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class StrategyVersionCreateRequest(BaseModel):
    config: dict[str, Any]


class BacktestRunCreateRequest(BaseModel):
    strategy_version_id: int
    start: date
    end: date


class BacktestRunResponse(BaseModel):
    run_id: str
    status: str
    strategy_version_id: int
    dataset_id: str | None
    dataset_manifest_hash: str | None
    rs_formula_version: str | None
    rs_result_hash: str | None
    markets: list[str]
    start: date
    end: date
    error_code: str | None = None
    error_detail: str | None = None


class BacktestRunListResponse(BaseModel):
    items: list[BacktestRunResponse]
    page: int
    size: int
    total: int


class BacktestRunDetailResponse(BaseModel):
    run: BacktestRunResponse
    metrics: dict[str, Any] | None
    equity_curve: list[dict[str, Any]]
    benchmarks: dict[str, list[dict[str, Any]]]
    orders: list[dict[str, Any]]
    trades: list[dict[str, Any]]
