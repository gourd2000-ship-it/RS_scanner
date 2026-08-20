"""Internal API for one-at-a-time Sam Kiwoom repair work."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.agent_auth import AgentPrincipal, require_repair_scope
from app.core.config import get_settings
from app.core.database import get_db_session
from app.repositories.crawl_repair_repository import CrawlRepairRepository
from app.schemas.repair import (
    RepairClaimBody,
    RepairClaimResponse,
    RepairCompleteBody,
    RepairFailBody,
    RepairMutationResponse,
    RepairPriceRow,
    RepairRequestStatusResponse,
    RepairAttemptSummary,
)
from app.services.repair_queue import (
    RepairClaimError,
    RepairQueueService,
    RepairResultRow,
    RepairValidationError,
)


router = APIRouter()


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _raise_mutation_error(error: Exception) -> None:
    if isinstance(error, LookupError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, PermissionError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, RepairClaimError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, RepairValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@router.post("/requests/claim", response_model=RepairClaimResponse)
def claim_repair_request(
    body: RepairClaimBody,
    _principal: AgentPrincipal = Depends(require_repair_scope("repair:claim")),
    session: Session = Depends(get_db_session),
):
    if body.claimed_by != "sam":
        raise HTTPException(status_code=403, detail="Only Sam may claim repair work")
    settings = get_settings()
    service = RepairQueueService(session, max_rows=settings.repair_max_rows)
    claim = service.claim(
        claimed_by=body.claimed_by,
        lease_seconds=settings.repair_claim_lease_seconds,
    )
    if claim is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    _commit(session)
    return RepairClaimResponse(
        request_id=claim.request.id,
        claim_token=claim.claim_token,
        claim_version=claim.request.claim_version,
        attempt_no=claim.attempt.attempt_no,
        operation=claim.request.operation,
        symbol=claim.request.symbol,
        from_date=claim.request.history_from or claim.request.trade_date,
        to_date=claim.request.trade_date,
        adjusted_price=claim.request.adjusted_price,
        lease_expires_at=claim.request.lease_expires_at,
    )


@router.post(
    "/requests/{request_id}/complete",
    response_model=RepairMutationResponse,
)
def complete_repair_request(
    request_id: int,
    body: RepairCompleteBody,
    _principal: AgentPrincipal = Depends(require_repair_scope("repair:submit")),
    session: Session = Depends(get_db_session),
):
    settings = get_settings()
    service = RepairQueueService(session, max_rows=settings.repair_max_rows)
    try:
        request = service.complete(
            request_id=request_id,
            claim_token=body.claim_token,
            claim_version=body.claim_version,
            operation=body.operation,
            symbol=body.symbol,
            from_date=body.from_date,
            to_date=body.to_date,
            adjusted_price=body.adjusted_price,
            executor=body.executor,
            tool=body.tool,
            mode=body.mode,
            latest_date=body.latest_date,
            row_count=body.row_count,
            data_complete=body.data_complete,
            rows=(
                RepairResultRow(
                    symbol=row.symbol,
                    trade_date=row.trade_date,
                    source=row.source,
                    adjusted_price=row.adjusted_price,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    change_rate=row.change_rate,
                )
                for row in body.rows
            ),
            result_hash=body.result_hash,
            details=body.details,
        )
        _commit(session)
    except (LookupError, PermissionError, RepairClaimError, RepairValidationError) as error:
        session.rollback()
        _raise_mutation_error(error)
    return RepairMutationResponse(
        request_id=request.id,
        status=request.status,
        application_status=request.application_status,
        attempt_count=request.attempt_count,
    )


@router.post(
    "/requests/{request_id}/fail",
    response_model=RepairMutationResponse,
)
def fail_repair_request(
    request_id: int,
    body: RepairFailBody,
    _principal: AgentPrincipal = Depends(require_repair_scope("repair:fail")),
    session: Session = Depends(get_db_session),
):
    settings = get_settings()
    service = RepairQueueService(session, max_rows=settings.repair_max_rows)
    try:
        request = service.fail(
            request_id=request_id,
            claim_token=body.claim_token,
            claim_version=body.claim_version,
            error_code=body.error_code,
            error_message=body.error_message,
            retryable=body.retryable,
            http_status=body.http_status,
            retry_after_seconds=body.retry_after_seconds,
            details=body.details,
        )
        _commit(session)
    except (LookupError, PermissionError, RepairClaimError, RepairValidationError) as error:
        session.rollback()
        _raise_mutation_error(error)
    return RepairMutationResponse(
        request_id=request.id,
        status=request.status,
        application_status=request.application_status,
        attempt_count=request.attempt_count,
    )


@router.get(
    "/requests/{request_id}",
    response_model=RepairRequestStatusResponse,
)
def get_repair_request(
    request_id: int,
    _principal: AgentPrincipal = Depends(require_repair_scope("repair:claim")),
    session: Session = Depends(get_db_session),
):
    repository = CrawlRepairRepository(session)
    request = repository.get(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=f"repair request not found: {request_id}")
    attempt = repository.latest_attempt(request.id)
    attempt_summary = None
    if attempt is not None:
        attempt_summary = RepairAttemptSummary(
            id=attempt.id,
            attempt_no=attempt.attempt_no,
            executor=attempt.executor,
            tool=attempt.tool,
            mode=attempt.mode,
            status=attempt.status,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            http_status=attempt.http_status,
            error_code=attempt.error_code,
            retryable=attempt.retryable,
            row_count=attempt.row_count,
            latest_date=attempt.latest_date,
            data_complete=attempt.data_complete,
            result_hash=attempt.result_hash,
        )
    return RepairRequestStatusResponse(
        request_id=request.id,
        status=request.status,
        application_status=request.application_status,
        operation=request.operation,
        symbol=request.symbol,
        from_date=request.history_from,
        to_date=request.trade_date,
        error_type=request.error_type,
        provider=request.provider,
        adjusted_price=request.adjusted_price,
        attempt_count=request.attempt_count,
        max_attempts=request.max_attempts,
        next_attempt_at=request.next_attempt_at,
        requested_at=request.requested_at,
        claimed_at=request.claimed_at,
        completed_at=request.completed_at,
        applied_at=request.applied_at,
        application_error=request.application_error,
        last_error_code=request.last_error_code,
        last_error_message=request.last_error_message,
        last_http_status=request.last_http_status,
        result_count=len(repository.list_results(request.id)),
        latest_attempt=attempt_summary,
    )
