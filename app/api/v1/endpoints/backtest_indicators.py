"""Read-only operator routes for Volume MA50 and ATR14 evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.backtest_auth import require_backtest_operator
from app.core.database import get_db_session
from app.repositories.backtest_indicator_query_repository import CurrentIndicatorSeries
from app.schemas.backtest_indicator import (
    BacktestIndicatorDailyResponse,
    BacktestIndicatorQueryResponse,
    IndicatorInputPolicyResponse,
)
from app.services.indicators.backtest_query_service import (
    AmbiguousCurrentIndicatorSeriesError,
    AmbiguousIndicatorInstrumentError,
    BacktestIndicatorQueryService,
    IndicatorInstrumentMismatchError,
    IndicatorNotCalculatedError,
    IndicatorQueryError,
    UnknownIndicatorInstrumentError,
    decimal_string,
)


router = APIRouter(prefix="/indicators")


def _response(result) -> BacktestIndicatorQueryResponse:
    series: CurrentIndicatorSeries = result.series
    policy = series.input_policy
    return BacktestIndicatorQueryResponse(
        indicator_kind=result.indicator_kind,
        code=result.code,
        instrument_id=result.instrument_id,
        series_id=series.series_id,
        generation_id=series.generation_id,
        generation=series.generation,
        period=int(series.periods),
        input_field=series.input_field,
        formula_version=series.formula_version,
        source_provider=series.source_provider,
        adjustment_policy=series.adjustment_policy,
        source_policy_fingerprint=policy.fingerprint,
        input_policy=IndicatorInputPolicyResponse(
            id=policy.id,
            version=policy.version,
            source_provider=policy.provider,
            adjustment_policy=policy.adjustment_type,
            allowed_parser_versions=policy.allowed_parser_versions,
            observation_cutoff=_as_utc(policy.observation_cutoff),
            selector_version=policy.selector_version,
            validation_version=policy.validation_version,
            correction_version=policy.correction_version,
        ),
        as_of=series.as_of,
        calculated_at=series.calculated_at,
        page=result.page,
        size=result.size,
        total_count=result.total_count,
        items=[
            BacktestIndicatorDailyResponse(
                trade_date=item.trade_date,
                value=decimal_string(item.value),
                status=item.status,
                reason_code=item.reason_code,
                available_observations=item.available_observations,
            )
            for item in result.items
        ],
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _query(
    *,
    indicator_kind: str,
    code: str,
    start: date,
    end: date,
    instrument_id: int | None,
    series_id: int | None,
    page: int,
    size: int,
    session: Session,
) -> BacktestIndicatorQueryResponse:
    try:
        result = BacktestIndicatorQueryService(session).current_page(
            indicator_kind=indicator_kind,
            code=code,
            instrument_id=instrument_id,
            series_id=series_id,
            start=start,
            end=end,
            page=page,
            size=size,
        )
    except (AmbiguousIndicatorInstrumentError, AmbiguousCurrentIndicatorSeriesError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail) from exc
    except (UnknownIndicatorInstrumentError, IndicatorNotCalculatedError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (IndicatorInstrumentMismatchError, IndicatorQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return _response(result)


@router.get("/volume-sma50", response_model=BacktestIndicatorQueryResponse)
def get_current_volume_sma50(
    code: str = Query(..., min_length=1, max_length=20),
    start: date = Query(...),
    end: date = Query(...),
    instrument_id: int | None = Query(default=None, ge=1),
    series_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=250, ge=1, le=1_000),
    _operator=Depends(require_backtest_operator),
    session: Session = Depends(get_db_session),
) -> BacktestIndicatorQueryResponse:
    return _query(
        indicator_kind="volume_sma",
        code=code,
        start=start,
        end=end,
        instrument_id=instrument_id,
        series_id=series_id,
        page=page,
        size=size,
        session=session,
    )


@router.get("/atr14", response_model=BacktestIndicatorQueryResponse)
def get_current_atr14(
    code: str = Query(..., min_length=1, max_length=20),
    start: date = Query(...),
    end: date = Query(...),
    instrument_id: int | None = Query(default=None, ge=1),
    series_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=250, ge=1, le=1_000),
    _operator=Depends(require_backtest_operator),
    session: Session = Depends(get_db_session),
) -> BacktestIndicatorQueryResponse:
    return _query(
        indicator_kind="atr",
        code=code,
        start=start,
        end=end,
        instrument_id=instrument_id,
        series_id=series_id,
        page=page,
        size=size,
        session=session,
    )
