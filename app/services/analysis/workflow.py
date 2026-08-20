"""State transitions for explicit weekly/ad-hoc analysis requests."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.crawl_analysis import CrawlAnalysisRequest
from app.models.crawl_job import CrawlJob
from app.models.crawl_quality_report import CrawlQualityReport
from app.repositories.crawl_analysis_repository import CrawlAnalysisRepository
from app.services.analysis.report_validator import validate_analysis_report


MAX_ANALYSIS_SAMPLE_LIMIT = 10
WEEKLY_COMPLETED_JOB_COUNT = 7
DAILY_CRAWL_JOB_TYPE = "daily_full"


class AnalysisStateError(ValueError):
    pass


class CrawlAnalysisService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = CrawlAnalysisRepository(session)

    def create_request(
        self,
        *,
        request_id: str,
        idempotency_key: str,
        requested_by: str,
        request_kind: str,
        completed_job_ids: list[int],
        period_from: date | None,
        period_to: date | None,
        error_types: list[str],
        markets: list[str],
        sample_limit: int,
        reason: str,
    ) -> tuple[CrawlAnalysisRequest, bool]:
        if sample_limit < 1 or sample_limit > MAX_ANALYSIS_SAMPLE_LIMIT:
            raise ValueError("sample_limit must be between 1 and 10")
        existing = self.repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing, False
        if self.repository.get_by_request_id(request_id) is not None:
            raise AnalysisStateError("request_id already exists with a different idempotency key")

        reports = self._quality_reports_for_jobs(completed_job_ids, request_kind=request_kind)
        resolved_job_ids = [report.crawl_job_id for report in reports]
        resolved_from, resolved_to = _report_window(reports)
        if period_from is not None and period_to is not None and period_from > period_to:
            raise ValueError("period_from must not be after period_to")
        if period_from is not None:
            resolved_from = period_from
        if period_to is not None:
            resolved_to = period_to
        if resolved_from is None or resolved_to is None:
            raise ValueError("selected quality reports do not provide an analysis period")

        request = self.repository.create_request(
            request_id=request_id,
            idempotency_key=idempotency_key,
            requested_by=requested_by,
            request_kind=request_kind,
            status="requested",
            period_from=resolved_from,
            period_to=resolved_to,
            completed_job_ids=resolved_job_ids,
            error_types=sorted(set(error_types)),
            markets=sorted(set(markets)),
            sample_limit=sample_limit,
            reason=reason,
            requested_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.repository.attach_quality_reports(
            analysis_request_id=request.id,
            quality_reports=reports,
        )
        return request, True

    def accept(self, *, request_id: str, accepted_by: str) -> CrawlAnalysisRequest:
        request = self.repository.get_by_request_id(request_id, lock=True)
        if request is None:
            raise LookupError(f"analysis request not found: {request_id}")
        if request.status != "requested":
            raise AnalysisStateError(f"analysis request is not requested: {request.status}")
        if accepted_by != "sam":
            raise PermissionError("only sam may accept analysis work")
        request.status = "accepted"
        request.accepted_by = accepted_by
        request.accepted_at = datetime.utcnow()
        request.updated_at = datetime.utcnow()
        self.session.flush()
        return request

    def submit_report(
        self,
        *,
        request_id: str,
        created_by: str,
        markdown_body: str,
        report_json: dict[str, Any],
        report_hash: str,
    ):
        request = self.repository.get_by_request_id(request_id, lock=True)
        if request is None:
            raise LookupError(f"analysis request not found: {request_id}")
        if request.status != "accepted":
            raise AnalysisStateError(f"analysis request is not accepted: {request.status}")
        if created_by != "sam" or request.accepted_by != "sam":
            raise PermissionError("only the accepting Sam principal may submit a report")
        if self.repository.get_report(request.id) is not None:
            raise AnalysisStateError("analysis request already has a final report")
        normalized = validate_analysis_report(
            request_id=request_id,
            markdown_body=markdown_body,
            report_json=report_json,
            report_hash=report_hash,
            sample_limit=request.sample_limit,
        )
        quality_reports = self.repository.quality_reports_for_request(request.id)
        report = self.repository.create_report(
            request_id=request.id,
            created_by=created_by,
            analysis_window={"from": request.period_from.isoformat(), "to": request.period_to.isoformat()},
            quality_report_refs=[item.id for item in quality_reports],
            findings=normalized["findings"],
            kiwoom_evidence=normalized["kiwoom_evidence"],
            recommendations=normalized["recommendations"],
            limitations=normalized["limitations"],
            markdown_body=markdown_body,
            report_json=report_json,
            report_hash=report_hash,
            created_at=datetime.utcnow(),
        )
        request.status = "report_ready"
        request.updated_at = datetime.utcnow()
        self.session.flush()
        return request, report

    def _quality_reports_for_jobs(
        self,
        completed_job_ids: list[int],
        *,
        request_kind: str,
    ) -> list[CrawlQualityReport]:
        if completed_job_ids:
            if len(set(completed_job_ids)) != len(completed_job_ids):
                raise ValueError("completed_job_ids must not contain duplicates")
            if len(completed_job_ids) > WEEKLY_COMPLETED_JOB_COUNT:
                raise ValueError("at most seven completed jobs may be selected")
            reports = list(
                self.session.scalars(
                    select(CrawlQualityReport).where(
                        CrawlQualityReport.crawl_job_id.in_(completed_job_ids)
                    )
                )
            )
            if len(reports) != len(completed_job_ids):
                raise LookupError("every selected crawl job must have a quality report")
            return sorted(reports, key=lambda item: (item.trade_date or date.min, item.id))
        if request_kind != "weekly":
            raise ValueError("ad_hoc analysis requires completed_job_ids")
        stmt = (
            select(CrawlQualityReport)
            .join(CrawlJob, CrawlJob.id == CrawlQualityReport.crawl_job_id)
            .where(
                CrawlJob.finished_at.is_not(None),
                CrawlJob.job_type == DAILY_CRAWL_JOB_TYPE,
            )
            .order_by(desc(CrawlJob.finished_at), desc(CrawlJob.id))
            .limit(WEEKLY_COMPLETED_JOB_COUNT)
        )
        reports = list(self.session.scalars(stmt))
        if not reports:
            raise LookupError("no completed crawl quality reports are available")
        return sorted(reports, key=lambda item: (item.trade_date or date.min, item.id))


def _report_window(reports: list[CrawlQualityReport]) -> tuple[date | None, date | None]:
    dates = [report.trade_date for report in reports if report.trade_date is not None]
    return (min(dates), max(dates)) if dates else (None, None)
