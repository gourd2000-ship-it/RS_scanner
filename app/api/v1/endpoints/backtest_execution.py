"""Unregistered protected API for strategy versions and backtest results."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.v1.endpoints.backtest_auth import require_backtest_csrf, require_backtest_operator
from app.core.database import get_db_session
from app.models.backtest_run import BacktestOrder, BacktestRun, BacktestStrategy, BacktestStrategyVersion, BacktestTrade
from app.repositories.backtest_repository import BacktestRepository
from app.schemas.backtest_execution import (
    BacktestRunCreateRequest, BacktestRunDetailResponse, BacktestRunListResponse, BacktestRunResponse,
    StrategyCreateRequest, StrategyPatchRequest, StrategyResponse, StrategyVersionCreateRequest,
    StrategyVersionResponse, StrategyListResponse,
)
from app.services.backtest.run_preparation import BacktestRunPreparationService
from app.services.backtest.strategy import StrategyValidationError, return_lookback_days, validate_config
from app.core.config import get_settings
from app.core.market_calendar import krx_market_day_status


router = APIRouter()


def _request_configuration(body) -> dict:
    configuration = getattr(body, "configuration", None) or getattr(body, "config", None)
    if not isinstance(configuration, dict):
        raise StrategyValidationError("configuration is required")
    return configuration


def _version(row: BacktestStrategyVersion) -> StrategyVersionResponse:
    configuration = validate_config(row.config)
    return StrategyVersionResponse(
        id=row.id, version=row.version, config=configuration, config_hash=row.config_hash,
        created_at=row.created_at, version_id=row.id, version_number=row.version,
        configuration=configuration, strategy_id=row.strategy.strategy_id,
        configuration_hash=row.config_hash,
    )


def _strategy(row: BacktestStrategy, *, include_versions: bool = True) -> StrategyResponse:
    versions = [_version(v) for v in row.versions] if include_versions else []
    current = max(versions, key=lambda version: version.version_number, default=None)
    return StrategyResponse(
        strategy_id=row.strategy_id, name=row.name, created_at=row.created_at,
        updated_at=row.updated_at or row.created_at,
        current_version_id=current.version_id if current else None, versions=versions,
    )


def _run(row: BacktestRun) -> BacktestRunResponse:
    hashes = {item.market.lower(): item.snapshot_hash for item in row.benchmark_snapshots}
    try:
        reason = json.loads(row.error_detail) if row.error_detail else None
    except (TypeError, json.JSONDecodeError):
        reason = row.error_detail
    return BacktestRunResponse(
        run_id=row.run_id, status=row.status, strategy_version_id=row.backtest_strategy_version_id,
        dataset_id=row.dataset_id, dataset_manifest_hash=row.dataset_manifest_hash,
        rs_formula_version=row.rs_formula_version, rs_result_hash=row.rs_result_hash,
        markets=row.markets, start=row.range_start, end=row.range_end,
        error_code=row.error_code, error_detail=row.error_detail,
        dataset_final_manifest_hash=row.dataset_manifest_hash,
        rs_run_id=row.backtest_dataset_rs_run_id,
        benchmark_snapshot_hash=hashes, reason=reason,
    )


def _rebalance_dates(start, end, interval: int):
    dates = []
    current = start
    closed_dates = get_settings().market_closed_dates
    from datetime import timedelta
    while current <= end:
        if krx_market_day_status(current, configured_closed_dates=closed_dates).is_open:
            dates.append(current)
        current += timedelta(days=1)
    return dates[::interval]


@router.get("/strategies", response_model=StrategyListResponse)
def list_strategies(page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100), _operator=Depends(require_backtest_operator), session: Session = Depends(get_db_session)):
    total = session.scalar(select(func.count(BacktestStrategy.id))) or 0
    rows = session.scalars(select(BacktestStrategy).options(selectinload(BacktestStrategy.versions)).order_by(BacktestStrategy.created_at.desc()).offset((page - 1) * size).limit(size)).unique()
    return StrategyListResponse(items=[_strategy(row) for row in rows], page=page, size=size, total_count=total)


@router.post("/strategies", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
def create_strategy(body: StrategyCreateRequest, _operator=Depends(require_backtest_csrf), session: Session = Depends(get_db_session)):
    try:
        configuration = validate_config(_request_configuration(body))
        row = BacktestRepository(session).create_strategy(name=body.name, config=configuration)
        session.commit()
        return _strategy(row)
    except StrategyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/strategies/{strategy_id}", response_model=StrategyResponse)
def get_strategy(strategy_id: str, _operator=Depends(require_backtest_operator), session: Session = Depends(get_db_session)):
    row = session.scalar(select(BacktestStrategy).options(selectinload(BacktestStrategy.versions)).where(BacktestStrategy.strategy_id == strategy_id))
    if row is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    return _strategy(row)


@router.patch("/strategies/{strategy_id}", response_model=StrategyResponse)
def patch_strategy(strategy_id: str, body: StrategyPatchRequest, _operator=Depends(require_backtest_csrf), session: Session = Depends(get_db_session)):
    row = session.scalar(select(BacktestStrategy).options(selectinload(BacktestStrategy.versions)).where(BacktestStrategy.strategy_id == strategy_id))
    if row is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    try:
        BacktestRepository(session).add_strategy_version(row.id, config=validate_config(_request_configuration(body)))
        session.commit()
        session.refresh(row)
        return _strategy(row)
    except StrategyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/strategies/{strategy_id}/versions", response_model=StrategyVersionResponse, status_code=status.HTTP_201_CREATED)
def append_strategy_version(strategy_id: str, body: StrategyVersionCreateRequest, _operator=Depends(require_backtest_csrf), session: Session = Depends(get_db_session)):
    strategy = session.scalar(select(BacktestStrategy).where(BacktestStrategy.strategy_id == strategy_id))
    if strategy is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    try:
        version = BacktestRepository(session).add_strategy_version(strategy.id, config=validate_config(_request_configuration(body)))
        session.commit()
        return _version(version)
    except StrategyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/runs", response_model=BacktestRunResponse, status_code=status.HTTP_201_CREATED)
def create_run(body: BacktestRunCreateRequest, _operator=Depends(require_backtest_csrf), session: Session = Depends(get_db_session)):
    if body.start >= body.end:
        raise HTTPException(status_code=422, detail="start must be before end")
    version = session.get(BacktestStrategyVersion, body.strategy_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="strategy version not found")
    try:
        config = validate_config(version.config)
        run = BacktestRunPreparationService(session).prepare(
            strategy_version_id=version.id, range_start=body.start, range_end=body.end,
            markets=config["markets"], rebalance_dates=_rebalance_dates(body.start, body.end, config["rebalance_interval_days"]), return_lookback_days=return_lookback_days(config),
        )
        # Input selection validates data.  Rebalance day validation belongs to the
        # worker-free request path, derived from the later pinned calendar.
        session.commit()
    except (ValueError, StrategyValidationError) as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if run.status == "data_unavailable":
        payload = _run(run).model_dump(mode="json")
        return JSONResponse(status_code=409, content={"run": payload, "reason": payload["reason"]})
    return _run(run)


@router.get("/runs", response_model=BacktestRunListResponse)
def list_runs(page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100), _operator=Depends(require_backtest_operator), session: Session = Depends(get_db_session)):
    total = session.scalar(select(func.count(BacktestRun.id))) or 0
    rows = list(session.scalars(select(BacktestRun).order_by(BacktestRun.queued_at.desc(), BacktestRun.id.desc()).offset((page - 1) * size).limit(size)))
    return BacktestRunListResponse(items=[_run(row) for row in rows], page=page, size=size, total_count=total)


@router.get("/runs/{run_id}", response_model=BacktestRunDetailResponse)
def get_run(
    run_id: str, orders_page: int = Query(1, ge=1), orders_size: int = Query(100, ge=1, le=500),
    trades_page: int = Query(1, ge=1), trades_size: int = Query(100, ge=1, le=500),
    _operator=Depends(require_backtest_operator), session: Session = Depends(get_db_session),
):
    row = BacktestRepository(session).get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="backtest run not found")
    benchmarks = {}
    for snapshot in row.benchmark_snapshots:
        first_close = snapshot.prices[0].close if snapshot.prices else None
        daily_values = [
            {"trade_date": p.trade_date, "close": p.close, "price_return": (p.close / first_close - 1) if first_close else None}
            for p in snapshot.prices
        ]
        benchmarks[snapshot.market.lower()] = {"benchmark_code": snapshot.benchmark_code, "snapshot_hash": snapshot.snapshot_hash, "daily_values": daily_values}
    orders_total = session.scalar(select(func.count(BacktestOrder.id)).where(BacktestOrder.backtest_run_id == row.id)) or 0
    order_rows = list(session.scalars(select(BacktestOrder).where(BacktestOrder.backtest_run_id == row.id).order_by(BacktestOrder.sequence).offset((orders_page - 1) * orders_size).limit(orders_size)))
    trades_total = session.scalar(select(func.count(BacktestTrade.id)).where(BacktestTrade.backtest_run_id == row.id)) or 0
    trade_rows = list(session.scalars(select(BacktestTrade).where(BacktestTrade.backtest_run_id == row.id).order_by(BacktestTrade.id).offset((trades_page - 1) * trades_size).limit(trades_size)))
    return BacktestRunDetailResponse(
        run=_run(row), metrics=row.metrics,
        equity_curve=[{"trade_date": item.trade_date, "cash": item.cash, "holdings_value": item.holdings_value, "net_asset_value": item.net_asset_value, "holdings": item.holdings} for item in row.daily_equity],
        benchmarks=benchmarks,
        orders={"page": orders_page, "size": orders_size, "total_count": orders_total, "items": [{"sequence": item.sequence, "code": item.code, "side": item.side, "signal_date": item.signal_date, "execution_date": item.execution_date, "quantity": item.quantity, "execution_price": item.execution_price, "fee": item.fee, "slippage": item.slippage, "reason_codes": item.reason_codes, "status": item.status} for item in order_rows]},
        trades={"page": trades_page, "size": trades_size, "total_count": trades_total, "items": [{"code": item.code, "entry_date": item.entry_date, "exit_date": item.exit_date, "quantity": item.quantity, "entry_value": item.entry_value, "exit_value": item.exit_value, "profit_loss": item.profit_loss, "return_rate": item.return_rate, "exit_reason_codes": item.exit_reason_codes} for item in trade_rows]},
    )


@router.post("/runs/{run_id}/cancel", response_model=BacktestRunResponse)
def cancel_run(run_id: str, _operator=Depends(require_backtest_csrf), session: Session = Depends(get_db_session)):
    try:
        row = BacktestRepository(session).cancel_queued_run(run_id)
        session.commit()
        return _run(row)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="backtest run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
