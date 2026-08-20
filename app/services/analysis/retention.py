"""Explicit, auditable retention for completed crawl-analysis workflows."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.codex_change_request import CodexChangeRequest
from app.models.crawl_analysis import (
    CrawlAnalysisReport,
    CrawlAnalysisRequest,
    CrawlAnalysisRequestQualityReport,
)


TERMINAL_ANALYSIS_STATUSES = {"implemented", "partially_implemented", "deferred"}


def expired_terminal_analysis_request_ids(
    session: Session,
    *,
    before: datetime,
    limit: int = 1_000,
) -> list[int]:
    """Return terminal analysis records eligible for one-year retention cleanup."""
    if limit < 1 or limit > 10_000:
        raise ValueError("limit must be between 1 and 10000")
    return list(
        session.scalars(
            select(CrawlAnalysisRequest.id)
            .where(
                CrawlAnalysisRequest.status.in_(TERMINAL_ANALYSIS_STATUSES),
                CrawlAnalysisRequest.created_at < before,
            )
            .order_by(CrawlAnalysisRequest.created_at, CrawlAnalysisRequest.id)
            .limit(limit)
        )
    )


def prune_terminal_analysis_requests(session: Session, *, request_ids: list[int]) -> int:
    """Delete final reports and audit rows only for explicitly selected terminal requests."""
    selected_ids = sorted(set(request_ids))
    if not selected_ids:
        return 0
    terminal_ids = list(
        session.scalars(
            select(CrawlAnalysisRequest.id).where(
                CrawlAnalysisRequest.id.in_(selected_ids),
                CrawlAnalysisRequest.status.in_(TERMINAL_ANALYSIS_STATUSES),
            )
        )
    )
    if not terminal_ids:
        return 0
    report_ids = list(
        session.scalars(
            select(CrawlAnalysisReport.id).where(CrawlAnalysisReport.request_id.in_(terminal_ids))
        )
    )
    if report_ids:
        session.execute(delete(CodexChangeRequest).where(CodexChangeRequest.report_id.in_(report_ids)))
    session.execute(
        delete(CrawlAnalysisRequestQualityReport).where(
            CrawlAnalysisRequestQualityReport.analysis_request_id.in_(terminal_ids)
        )
    )
    session.execute(delete(CrawlAnalysisReport).where(CrawlAnalysisReport.request_id.in_(terminal_ids)))
    session.execute(delete(CrawlAnalysisRequest).where(CrawlAnalysisRequest.id.in_(terminal_ids)))
    return len(terminal_ids)
