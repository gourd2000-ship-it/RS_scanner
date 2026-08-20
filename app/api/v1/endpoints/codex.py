"""Audit API for user-approved Codex implementation results."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.agent_auth import AgentPrincipal, require_analysis_scope
from app.core.database import get_db_session
from app.repositories.codex_change_request_repository import CodexChangeRequestRepository
from app.schemas.codex_change import (
    CodexChangeRequestCreate,
    CodexChangeRequestItem,
    CodexChangeResultBody,
    CodexChangeReviewBody,
)
from app.services.analysis.codex_workflow import CodexChangeService, CodexChangeStateError


router = APIRouter()


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _raise_error(error: Exception) -> None:
    if isinstance(error, LookupError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, CodexChangeStateError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@router.post("", response_model=CodexChangeRequestItem, status_code=201)
def create_codex_change_request(
    body: CodexChangeRequestCreate,
    _principal: AgentPrincipal = Depends(require_analysis_scope("codex:request")),
    session: Session = Depends(get_db_session),
):
    try:
        item, _created = CodexChangeService(session).create_from_proposal(**body.model_dump())
        _commit(session)
    except Exception as error:  # noqa: BLE001
        session.rollback()
        _raise_error(error)
    return CodexChangeRequestItem.model_validate(item)


@router.get("/{change_request_id}", response_model=CodexChangeRequestItem)
def get_codex_change_request(
    change_request_id: str,
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:read")),
    session: Session = Depends(get_db_session),
):
    item = CodexChangeRequestRepository(session).get_by_change_request_id(change_request_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"codex change request not found: {change_request_id}")
    return CodexChangeRequestItem.model_validate(item)


@router.post("/{change_request_id}/review", response_model=CodexChangeRequestItem)
def review_codex_change_request(
    change_request_id: str,
    body: CodexChangeReviewBody,
    _principal: AgentPrincipal = Depends(require_analysis_scope("analysis:review")),
    session: Session = Depends(get_db_session),
):
    try:
        item = CodexChangeService(session).review(
            change_request_id=change_request_id,
            action=body.action,
            reviewed_by=body.reviewed_by,
            review_notes=body.review_notes,
        )
        _commit(session)
    except Exception as error:  # noqa: BLE001
        session.rollback()
        _raise_error(error)
    return CodexChangeRequestItem.model_validate(item)


@router.post("/{change_request_id}/result", response_model=CodexChangeRequestItem)
def record_codex_change_result(
    change_request_id: str,
    body: CodexChangeResultBody,
    _principal: AgentPrincipal = Depends(require_analysis_scope("codex:result")),
    session: Session = Depends(get_db_session),
):
    try:
        item = CodexChangeService(session).record_result(
            change_request_id=change_request_id,
            status=body.status,
            codex_run_id=body.codex_run_id,
            commit_ref=body.commit_ref,
            test_results=body.test_results,
            review_notes=body.review_notes,
        )
        _commit(session)
    except Exception as error:  # noqa: BLE001
        session.rollback()
        _raise_error(error)
    return CodexChangeRequestItem.model_validate(item)
