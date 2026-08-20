"""Authenticated API for explicit Sam crawl-quality analysis work."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.agent_auth import AgentPrincipal, require_analysis_scope
from app.core.database import get_db_session
from app.models.crawl_analysis import CrawlAnalysisRequest
from app.models.crawl_failure import CrawlFailure
from app.models.crawl_quality_report import CrawlQualityReport
from app.models.crawl_target_result import CrawlTargetResult
from app.models.daily_price import DailyPrice
from app.models.symbol import Symbol
from app.repositories.crawl_analysis_repository import CrawlAnalysisRepository
from app.schemas.analysis import (
    AnalysisAcceptBody,
    AnalysisFailureItem,
    AnalysisMutationResponse,
    AnalysisPriceHistoryResponse,
    AnalysisPriceItem,
    AnalysisReportItem,
    AnalysisReportHashPreview,
    AnalysisReportHashPreviewResponse,
    AnalysisReportSubmit,
    AnalysisRequestCreate,
    AnalysisRequestItem,
    AnalysisTargetResultItem,
    QualityReportItem,
)
from app.schemas.response import PaginatedResponse
from app.services.analysis.report_validator import AnalysisReportValidationError
from app.services.analysis.report_validator import report_content_hash, validate_analysis_report
from app.services.analysis.workflow import AnalysisStateError, CrawlAnalysisService


router = APIRouter()


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _raise_workflow_error(error: Exception) -> None:
    if isinstance(error, LookupError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, PermissionError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, (AnalysisStateError, AnalysisReportValidationError)):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@router.get("/quality-reports", response_model=PaginatedResponse[QualityReportItem])
def list_quality_reports(
    job_id: int | None = Query(default=None, ge=1),
    trade_date_from: date | None = None,
    trade_date_to: date | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:read")),
    session: Session = Depends(get_db_session),
):
    stmt = select(CrawlQualityReport).order_by(desc(CrawlQualityReport.created_at), desc(CrawlQualityReport.id))
    count_stmt = select(func.count()).select_from(CrawlQualityReport)
    filters = []
    if job_id is not None:
        filters.append(CrawlQualityReport.crawl_job_id == job_id)
    if trade_date_from is not None:
        filters.append(CrawlQualityReport.trade_date >= trade_date_from)
    if trade_date_to is not None:
        filters.append(CrawlQualityReport.trade_date <= trade_date_to)
    if status is not None:
        filters.append(CrawlQualityReport.job_status == status)
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)
    total_count = session.scalar(count_stmt) or 0
    reports = list(session.scalars(stmt.limit(size).offset((page - 1) * size)))
    return PaginatedResponse(
        total_count=total_count,
        page=page,
        size=size,
        items=[QualityReportItem.model_validate(item) for item in reports],
    )


@router.get("/quality-reports/{report_id}", response_model=QualityReportItem)
def get_quality_report(
    report_id: int,
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:read")),
    session: Session = Depends(get_db_session),
):
    report = session.get(CrawlQualityReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"quality report not found: {report_id}")
    return QualityReportItem.model_validate(report)


@router.get("/failures", response_model=PaginatedResponse[AnalysisFailureItem])
def list_analysis_failures(
    job_id: int = Query(ge=1),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=100),
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:read")),
    session: Session = Depends(get_db_session),
):
    base = select(CrawlFailure).where(CrawlFailure.job_id == job_id)
    total_count = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    failures = list(
        session.scalars(
            base.order_by(CrawlFailure.created_at, CrawlFailure.id).limit(size).offset((page - 1) * size)
        )
    )
    return PaginatedResponse(
        total_count=total_count,
        page=page,
        size=size,
        items=[AnalysisFailureItem.model_validate(item) for item in failures],
    )


@router.get("/target-results", response_model=PaginatedResponse[AnalysisTargetResultItem])
def list_analysis_target_results(
    job_id: int = Query(ge=1),
    target_key: str | None = Query(default=None, min_length=1, max_length=255),
    step_name: str | None = Query(default=None, min_length=1, max_length=50),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=100),
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:read")),
    session: Session = Depends(get_db_session),
):
    """Expose audited crawl target outcomes for bounded report samples."""
    base = select(CrawlTargetResult).where(CrawlTargetResult.job_id == job_id)
    if target_key is not None:
        base = base.where(CrawlTargetResult.target_key == target_key)
    if step_name is not None:
        base = base.where(CrawlTargetResult.step_name == step_name)
    total_count = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = list(
        session.scalars(
            base.order_by(CrawlTargetResult.step_name, CrawlTargetResult.target_key, CrawlTargetResult.id)
            .limit(size)
            .offset((page - 1) * size)
        )
    )
    return PaginatedResponse(
        total_count=total_count,
        page=page,
        size=size,
        items=[AnalysisTargetResultItem.model_validate(item) for item in items],
    )


@router.get("/stock-history/{symbol}", response_model=AnalysisPriceHistoryResponse)
def get_analysis_stock_history(
    symbol: str,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    limit: int = Query(default=365, ge=1, le=365),
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:read")),
    session: Session = Depends(get_db_session),
):
    if from_date > to_date:
        raise HTTPException(status_code=422, detail="from must not be after to")
    stock = session.scalar(select(Symbol).where(Symbol.code == symbol))
    if stock is None:
        raise HTTPException(status_code=404, detail=f"symbol not found: {symbol}")
    rows = list(
        session.scalars(
            select(DailyPrice)
            .where(
                DailyPrice.symbol_id == stock.id,
                DailyPrice.trade_date >= from_date,
                DailyPrice.trade_date <= to_date,
            )
            .order_by(DailyPrice.trade_date)
            .limit(limit)
        )
    )
    return AnalysisPriceHistoryResponse(
        symbol=stock.code,
        **{"from": from_date, "to": to_date},
        total_count=len(rows),
        items=[AnalysisPriceItem.model_validate(row) for row in rows],
    )


@router.post("/requests", response_model=AnalysisRequestItem, status_code=201)
def create_analysis_request(
    body: AnalysisRequestCreate,
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:request")),
    session: Session = Depends(get_db_session),
):
    service = CrawlAnalysisService(session)
    try:
        request, created = service.create_request(**body.model_dump())
        _commit(session)
    except Exception as error:  # noqa: BLE001
        session.rollback()
        _raise_workflow_error(error)
    return _request_item(session, request, status_code_created=created)


@router.get("/requests/{request_id}", response_model=AnalysisRequestItem)
def get_analysis_request(
    request_id: str,
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:read")),
    session: Session = Depends(get_db_session),
):
    request = CrawlAnalysisRepository(session).get_by_request_id(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=f"analysis request not found: {request_id}")
    return _request_item(session, request)


@router.get("/requests/{request_id}/quality-reports", response_model=list[QualityReportItem])
def list_request_quality_reports(
    request_id: str,
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:read")),
    session: Session = Depends(get_db_session),
):
    request = CrawlAnalysisRepository(session).get_by_request_id(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=f"analysis request not found: {request_id}")
    reports = CrawlAnalysisRepository(session).quality_reports_for_request(request.id)
    return [QualityReportItem.model_validate(item) for item in reports]


@router.post("/requests/{request_id}/accept", response_model=AnalysisMutationResponse)
def accept_analysis_request(
    request_id: str,
    body: AnalysisAcceptBody,
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:accept")),
    session: Session = Depends(get_db_session),
):
    try:
        request = CrawlAnalysisService(session).accept(
            request_id=request_id,
            accepted_by=body.accepted_by,
        )
        _commit(session)
    except Exception as error:  # noqa: BLE001
        session.rollback()
        _raise_workflow_error(error)
    return AnalysisMutationResponse(
        request_id=request.request_id,
        status=request.status,
        accepted_by=request.accepted_by,
        accepted_at=request.accepted_at,
    )


@router.post(
    "/requests/{request_id}/report-hash",
    response_model=AnalysisReportHashPreviewResponse,
)
def preview_analysis_report_hash(
    request_id: str,
    body: AnalysisReportHashPreview,
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:submit")),
    session: Session = Depends(get_db_session),
):
    """Validate report content without persistence and return the canonical hash."""
    request = CrawlAnalysisRepository(session).get_by_request_id(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=f"analysis request not found: {request_id}")
    if request.status != "accepted":
        raise HTTPException(status_code=409, detail=f"analysis request is not accepted: {request.status}")
    if request.accepted_by != "sam" or body.created_by != "sam":
        raise HTTPException(status_code=403, detail="only the accepting Sam principal may preview a report")
    expected_hash = report_content_hash(body.markdown_body, body.report_json)
    try:
        validate_analysis_report(
            request_id=request_id,
            markdown_body=body.markdown_body,
            report_json=body.report_json,
            report_hash=expected_hash,
            sample_limit=request.sample_limit,
        )
    except AnalysisReportValidationError as error:
        _raise_workflow_error(error)
    return AnalysisReportHashPreviewResponse(request_id=request_id, report_hash=expected_hash)


@router.post("/requests/{request_id}/report", response_model=AnalysisMutationResponse)
def submit_analysis_report(
    request_id: str,
    body: AnalysisReportSubmit,
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:submit")),
    session: Session = Depends(get_db_session),
):
    try:
        request, report = CrawlAnalysisService(session).submit_report(
            request_id=request_id,
            created_by=body.created_by,
            markdown_body=body.markdown_body,
            report_json=body.report_json,
            report_hash=body.report_hash,
        )
        _commit(session)
    except Exception as error:  # noqa: BLE001
        session.rollback()
        _raise_workflow_error(error)
    return AnalysisMutationResponse(
        request_id=request.request_id,
        status=request.status,
        report_id=report.id,
        report_hash=report.report_hash,
    )


def _request_item(
    session: Session,
    request: CrawlAnalysisRequest,
    *,
    status_code_created: bool | None = None,
) -> AnalysisRequestItem:
    repository = CrawlAnalysisRepository(session)
    reports = repository.quality_reports_for_request(request.id)
    report = repository.get_report(request.id)
    return AnalysisRequestItem(
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        requested_by=request.requested_by,
        request_kind=request.request_kind,
        status=request.status,
        period_from=request.period_from,
        period_to=request.period_to,
        completed_job_ids=request.completed_job_ids,
        quality_report_ids=[item.id for item in reports],
        error_types=request.error_types,
        markets=request.markets,
        sample_limit=request.sample_limit,
        reason=request.reason,
        accepted_by=request.accepted_by,
        requested_at=request.requested_at,
        accepted_at=request.accepted_at,
        report=AnalysisReportItem.model_validate(report) if report is not None else None,
    )
