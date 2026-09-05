"""Versioned, paginated backtest dataset API."""

import base64
import bisect
import hashlib
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.agent_auth import AgentPrincipal, require_agent_scope
from app.core.database import get_db_session
from app.models.daily_price import DailyPrice
from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot
from app.models.rs_score import RsScore
from app.models.symbol import Symbol
from app.schemas.agent import (
    BacktestCoverage,
    BacktestDatasetItem,
    BacktestDatasetResponse,
    BacktestUniverseState,
    BacktestWatermark,
)
from app.schemas.response import DailyPriceItem, RsScoreItem


router = APIRouter()

_ALLOWED_MARKETS = frozenset({"KOSPI", "KOSDAQ"})
_CURSOR_VERSION = 1


def _normalise_markets(markets: str) -> tuple[str, ...]:
    parsed = tuple(sorted({market.strip().upper() for market in markets.split(",") if market.strip()}))
    if not parsed or not set(parsed).issubset(_ALLOWED_MARKETS):
        raise HTTPException(
            status_code=422,
            detail="markets must contain one or both of KOSPI,KOSDAQ",
        )
    return parsed


def _encode_cursor(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> dict:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid backtest cursor") from exc
    if not isinstance(payload, dict) or payload.get("version") != _CURSOR_VERSION:
        raise HTTPException(status_code=422, detail="Invalid backtest cursor")
    return payload


def _watermark(session: Session) -> BacktestWatermark:
    return BacktestWatermark(
        daily_price_id=session.scalar(select(func.max(DailyPrice.id))) or 0,
        rs_score_id=session.scalar(select(func.max(RsScore.id))) or 0,
        universe_snapshot_id=session.scalar(select(func.max(KrxUniverseSnapshot.id))) or 0,
    )


def _dataset_id(*, start: date, end: date, markets: tuple[str, ...], watermark: BacktestWatermark) -> str:
    material = json.dumps(
        {
            "version": _CURSOR_VERSION,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "markets": markets,
            "watermark": watermark.model_dump(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"backtest-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _cursor_payload(
    *,
    start: date,
    end: date,
    markets: tuple[str, ...],
    watermark: BacktestWatermark,
    dataset_id: str,
    row: DailyPrice,
    code: str,
) -> dict:
    return {
        "version": _CURSOR_VERSION,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "markets": list(markets),
        "watermark": watermark.model_dump(),
        "dataset_id": dataset_id,
        "last": [row.trade_date.isoformat(), code, row.id],
    }


def _universe_states(
    session: Session,
    *,
    rows: list[tuple[DailyPrice, Symbol, RsScore | None]],
    watermark: BacktestWatermark,
) -> list[BacktestUniverseState]:
    if not rows:
        return []

    latest_trade_date = max(price.trade_date for price, _, _ in rows)
    snapshots = list(
        session.scalars(
            select(KrxUniverseSnapshot)
            .where(
                KrxUniverseSnapshot.id <= watermark.universe_snapshot_id,
                KrxUniverseSnapshot.scope == "stock_membership",
                KrxUniverseSnapshot.status == "completed",
                KrxUniverseSnapshot.as_of_date <= latest_trade_date,
            )
            .order_by(KrxUniverseSnapshot.as_of_date, KrxUniverseSnapshot.id)
        )
    )
    latest_by_date: dict[date, KrxUniverseSnapshot] = {
        snapshot.as_of_date: snapshot for snapshot in snapshots
    }
    snapshot_dates = sorted(latest_by_date)
    snapshot_ids = [latest_by_date[snapshot_date].id for snapshot_date in snapshot_dates]
    codes = {symbol.code for _, symbol, _ in rows}
    memberships = {}
    if snapshot_ids:
        memberships = {
            (membership.snapshot_id, membership.code): membership
            for membership in session.scalars(
                select(KrxUniverseMembership).where(
                    KrxUniverseMembership.snapshot_id.in_(snapshot_ids),
                    KrxUniverseMembership.code.in_(codes),
                )
            )
        }

    states = []
    for price, symbol, _ in rows:
        snapshot = None
        index = bisect.bisect_right(snapshot_dates, price.trade_date) - 1
        if index >= 0:
            snapshot = latest_by_date[snapshot_dates[index]]
        membership = memberships.get((snapshot.id, symbol.code)) if snapshot else None
        if membership is not None:
            states.append(
                BacktestUniverseState(
                    status="listed_observed",
                    observed_as_of=snapshot.as_of_date,
                    source=snapshot.source,
                    trading_status=membership.trading_status,
                )
            )
        elif symbol.delisted_at is not None and symbol.delisted_at <= price.trade_date:
            states.append(BacktestUniverseState(status="delisted_recorded"))
        elif symbol.listed_at is not None and symbol.listed_at > price.trade_date:
            states.append(BacktestUniverseState(status="not_listed_recorded"))
        else:
            states.append(BacktestUniverseState(status="unknown"))
    return states


@router.get("/backtest/dataset", response_model=BacktestDatasetResponse)
def get_backtest_dataset(
    request: Request,
    response: Response,
    start: date = Query(...),
    end: date = Query(...),
    markets: str = Query(default="KOSPI,KOSDAQ"),
    cursor: str | None = Query(default=None),
    page_size: int = Query(default=1000, ge=1, le=5000),
    _principal: AgentPrincipal = Depends(require_agent_scope("backtest:read")),
    session: Session = Depends(get_db_session),
):
    """Return a bounded page of historical price, RS, and universe data.

    A cursor binds the date range, markets, and database watermark. If source
    rows change between pages, the client receives 409 and must restart, rather
    than silently joining two dataset versions.
    """
    if start > end:
        raise HTTPException(status_code=422, detail="start must not be after end")
    selected_markets = _normalise_markets(markets)
    current_watermark = _watermark(session)
    current_dataset_id = _dataset_id(
        start=start,
        end=end,
        markets=selected_markets,
        watermark=current_watermark,
    )
    last = None
    if cursor is not None:
        payload = _decode_cursor(cursor)
        expected = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "markets": list(selected_markets),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise HTTPException(status_code=422, detail="Cursor does not match request filters")
        if payload.get("dataset_id") != current_dataset_id:
            raise HTTPException(
                status_code=409,
                detail="Backtest dataset changed; restart from the first page",
            )
        try:
            watermark = BacktestWatermark.model_validate(payload["watermark"])
            last_date = date.fromisoformat(payload["last"][0])
            last_code = str(payload["last"][1])
            last_id = int(payload["last"][2])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Invalid backtest cursor") from exc
        if watermark != current_watermark:
            raise HTTPException(
                status_code=409,
                detail="Backtest dataset changed; restart from the first page",
            )
        dataset_id = current_dataset_id
        last = (last_date, last_code, last_id)
    else:
        watermark = current_watermark
        dataset_id = current_dataset_id

    filters = [
        DailyPrice.id <= watermark.daily_price_id,
        DailyPrice.trade_date >= start,
        DailyPrice.trade_date <= end,
        Symbol.market.in_(selected_markets),
    ]
    if last is not None:
        last_date, last_code, last_id = last
        filters.append(
            or_(
                DailyPrice.trade_date > last_date,
                and_(DailyPrice.trade_date == last_date, Symbol.code > last_code),
                and_(
                    DailyPrice.trade_date == last_date,
                    Symbol.code == last_code,
                    DailyPrice.id > last_id,
                ),
            )
        )
    rows = list(
        session.execute(
            select(DailyPrice, Symbol, RsScore)
            .join(Symbol, Symbol.id == DailyPrice.symbol_id)
            .outerjoin(
                RsScore,
                and_(
                    RsScore.symbol_id == DailyPrice.symbol_id,
                    RsScore.trade_date == DailyPrice.trade_date,
                    RsScore.id <= watermark.rs_score_id,
                ),
            )
            .where(*filters)
            .order_by(DailyPrice.trade_date, Symbol.code, DailyPrice.id)
            .limit(page_size + 1)
        ).all()
    )
    has_next = len(rows) > page_size
    page_rows = rows[:page_size]
    states = _universe_states(session, rows=page_rows, watermark=watermark)
    items = []
    rs_count = 0
    observed_universe_count = 0
    for (price, symbol, rs), universe in zip(page_rows, states, strict=True):
        price_item = DailyPriceItem(
            trade_date=price.trade_date,
            open=price.open,
            high=price.high,
            low=price.low,
            close=price.close,
            volume=price.volume,
            change_rate=price.change_rate,
            source=price.source,
        )
        rs_item = None
        if rs is not None:
            rs_count += 1
            rs_item = RsScoreItem(
                trade_date=rs.trade_date,
                rs_rating=rs.rs_rating,
                rank_in_market=rs.rank_in_market,
                return_1m=rs.return_1m,
                return_3m=rs.return_3m,
                return_6m=rs.return_6m,
                return_9m=rs.return_9m,
                return_12m=rs.return_12m,
                rs_1m=rs.rs_1m,
                rs_3m=rs.rs_3m,
                rs_6m=rs.rs_6m,
                rs_12m=rs.rs_12m,
                relative_return_score=rs.relative_return_score,
                rs_percentile=rs.rs_percentile,
            )
        if universe.status == "listed_observed":
            observed_universe_count += 1
        items.append(
            BacktestDatasetItem(
                code=symbol.code,
                name=symbol.name,
                market=symbol.market,
                trade_date=price.trade_date,
                price=price_item,
                rs=rs_item,
                universe=universe,
            )
        )

    next_cursor = None
    if has_next and page_rows:
        price, symbol, _ = page_rows[-1]
        next_cursor = _encode_cursor(
            _cursor_payload(
                start=start,
                end=end,
                markets=selected_markets,
                watermark=watermark,
                dataset_id=dataset_id,
                row=price,
                code=symbol.code,
            )
        )
    etag = hashlib.sha256(
        f"{dataset_id}:{next_cursor or 'final'}".encode("utf-8")
    ).hexdigest()[:32]
    response.headers["ETag"] = f'"{etag}"'
    response.headers["X-Dataset-Id"] = dataset_id
    response.headers["X-Backtest-Watermark"] = json.dumps(watermark.model_dump(), separators=(",", ":"))
    if request.headers.get("if-none-match") == response.headers["ETag"]:
        return Response(status_code=304, headers=dict(response.headers))
    row_count = len(items)
    return BacktestDatasetResponse(
        dataset_id=dataset_id,
        watermark=watermark,
        coverage=BacktestCoverage(
            rs=rs_count / row_count if row_count else 0.0,
            universe=observed_universe_count / row_count if row_count else 0.0,
        ),
        next_cursor=next_cursor,
        items=items,
    )
