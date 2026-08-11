"""Hermes용 versioned read-only Agent API."""

from datetime import date, timezone
from email.utils import format_datetime
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.agent_auth import AgentPrincipal, require_agent_scope
from app.core.database import get_db_session
from app.schemas.agent import (
    AgentBriefingData,
    AgentEnvelope,
    AgentRankingPage,
    AgentStatusData,
    AgentStockHistoryData,
    AgentStockSnapshotData,
)
from app.services.agent_data import (
    AgentDataMeta,
    build_agent_meta,
    get_briefing_data,
    get_rs_rankings,
    get_status_data,
    get_stock_history,
    get_stock_snapshot,
)

router = APIRouter()


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _cache_headers(meta: AgentDataMeta, variant: str) -> dict[str, str]:
    etag_value = sha256(
        f"{meta.dataset_id}|{variant}".encode("utf-8")
    ).hexdigest()[:32]
    headers = {
        "ETag": f'"{etag_value}"',
        "X-Dataset-Id": meta.dataset_id,
        "X-Data-Status": meta.data_status,
        "X-Coverage": f"{meta.coverage:.6f}",
        "Cache-Control": "private, max-age=60",
    }
    if meta.as_of is not None:
        headers["X-Data-As-Of"] = meta.as_of.isoformat()
        as_of = meta.as_of
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        headers["Last-Modified"] = format_datetime(as_of, usegmt=True)
    return headers


def _apply_headers(
    request: Request,
    response: Response,
    meta: AgentDataMeta,
    variant: str,
) -> Response | None:
    headers = _cache_headers(meta, variant)
    if _request_id(request):
        headers["X-Request-Id"] = _request_id(request) or ""
    for key, value in headers.items():
        response.headers[key] = value

    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    return None


def _require_available(meta: AgentDataMeta) -> None:
    if meta.data_status == "unavailable":
        raise HTTPException(
            status_code=503,
            detail="RS dataset is currently unavailable",
            headers={"Retry-After": "300"},
        )


@router.get("/status", response_model=AgentEnvelope[AgentStatusData])
def get_agent_status(
    request: Request,
    response: Response,
    _principal: AgentPrincipal = Depends(require_agent_scope("status:read")),
    session: Session = Depends(get_db_session),
):
    meta = build_agent_meta(session)
    not_modified = _apply_headers(request, response, meta, "status")
    if not_modified is not None:
        return not_modified
    return AgentEnvelope(
        data=get_status_data(session),
        meta=meta.as_schema(_request_id(request)),
    )


@router.get("/briefing", response_model=AgentEnvelope[AgentBriefingData])
def get_agent_briefing(
    request: Request,
    response: Response,
    size: int = Query(default=10, ge=1, le=50),
    _principal: AgentPrincipal = Depends(require_agent_scope("rs:read")),
    session: Session = Depends(get_db_session),
):
    meta = build_agent_meta(session)
    _require_available(meta)
    assert meta.trade_date is not None
    not_modified = _apply_headers(request, response, meta, f"briefing:{size}")
    if not_modified is not None:
        return not_modified
    return AgentEnvelope(
        data=AgentBriefingData(
            trade_date=meta.trade_date,
            rankings=get_briefing_data(
                session,
                trade_date=meta.trade_date,
                size=size,
            ),
        ),
        meta=meta.as_schema(_request_id(request)),
    )


@router.get("/rankings/rs", response_model=AgentEnvelope[AgentRankingPage])
def get_agent_rankings(
    request: Request,
    response: Response,
    market: str = Query(..., pattern="^(KOSPI|KOSDAQ)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=100, ge=1, le=100),
    _principal: AgentPrincipal = Depends(require_agent_scope("rs:read")),
    session: Session = Depends(get_db_session),
):
    meta = build_agent_meta(session)
    _require_available(meta)
    assert meta.trade_date is not None
    variant = f"rankings:{market}:{page}:{size}"
    not_modified = _apply_headers(request, response, meta, variant)
    if not_modified is not None:
        return not_modified
    return AgentEnvelope(
        data=get_rs_rankings(
            session,
            market=market,
            trade_date=meta.trade_date,
            page=page,
            size=size,
        ),
        meta=meta.as_schema(_request_id(request)),
    )


@router.get(
    "/stocks/{code}",
    response_model=AgentEnvelope[AgentStockSnapshotData],
)
def get_agent_stock_snapshot(
    code: str,
    request: Request,
    response: Response,
    _principal: AgentPrincipal = Depends(require_agent_scope("stock:read")),
    session: Session = Depends(get_db_session),
):
    meta = build_agent_meta(session)
    _require_available(meta)
    not_modified = _apply_headers(request, response, meta, f"stock:{code}")
    if not_modified is not None:
        return not_modified
    try:
        data = get_stock_snapshot(
            session,
            code=code,
            trade_date=meta.trade_date,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail=f"종목을 찾을 수 없습니다: {code}")
    return AgentEnvelope(data=data, meta=meta.as_schema(_request_id(request)))


@router.get(
    "/stocks/{code}/history",
    response_model=AgentEnvelope[AgentStockHistoryData],
)
def get_agent_stock_history(
    code: str,
    request: Request,
    response: Response,
    limit: int = Query(default=90, ge=1, le=365),
    _principal: AgentPrincipal = Depends(require_agent_scope("stock:read")),
    session: Session = Depends(get_db_session),
):
    meta = build_agent_meta(session)
    _require_available(meta)
    not_modified = _apply_headers(request, response, meta, f"history:{code}:{limit}")
    if not_modified is not None:
        return not_modified
    try:
        data = get_stock_history(
            session,
            code=code,
            trade_date=meta.trade_date,
            limit=limit,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail=f"종목을 찾을 수 없습니다: {code}")
    return AgentEnvelope(data=data, meta=meta.as_schema(_request_id(request)))
