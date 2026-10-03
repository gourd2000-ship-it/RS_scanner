"""Protected browser backtest contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrategyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    configuration: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


class StrategyVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version: int
    config: dict[str, Any]
    config_hash: str
    created_at: datetime
    version_id: int
    version_number: int
    configuration: dict[str, Any]


class StrategyResponse(BaseModel):
    strategy_id: str
    name: str
    created_at: datetime
    updated_at: datetime
    current_version_id: int | None
    versions: list[StrategyVersionResponse] = []


class StrategyPatchRequest(BaseModel):
    configuration: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


class StrategyVersionCreateRequest(BaseModel):
    configuration: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


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
    dataset_final_manifest_hash: str | None
    rs_run_id: int | None
    benchmark_snapshot_hash: dict[str, str]
    reason: object | None = None


class BacktestRunListResponse(BaseModel):
    items: list[BacktestRunResponse]
    page: int
    size: int
    total_count: int


class StrategyListResponse(BaseModel):
    items: list[StrategyResponse]
    page: int
    size: int
    total_count: int


class BacktestRunDetailResponse(BaseModel):
    run: BacktestRunResponse
    metrics: dict[str, Any] | None
    equity_curve: list[dict[str, Any]]
    benchmarks: dict[str, dict[str, Any]]
    orders: dict[str, Any]
    trades: dict[str, Any]
