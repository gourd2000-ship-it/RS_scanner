"""Persistence and locking helpers for crawl-quality analysis workflow."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crawl_analysis import (
    CrawlAnalysisReport,
    CrawlAnalysisRequest,
    CrawlAnalysisRequestQualityReport,
)
from app.models.crawl_quality_report import CrawlQualityReport


class CrawlAnalysisRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_request_id(self, request_id: str, *, lock: bool = False) -> CrawlAnalysisRequest | None:
        stmt = select(CrawlAnalysisRequest).where(CrawlAnalysisRequest.request_id == request_id)
        if lock:
            stmt = stmt.with_for_update()
        return self.session.scalar(stmt)

    def get_by_idempotency_key(self, idempotency_key: str) -> CrawlAnalysisRequest | None:
        return self.session.scalar(
            select(CrawlAnalysisRequest).where(
                CrawlAnalysisRequest.idempotency_key == idempotency_key
            )
        )

    def create_request(self, **values) -> CrawlAnalysisRequest:
        request = CrawlAnalysisRequest(**values)
        self.session.add(request)
        self.session.flush()
        return request

    def attach_quality_reports(
        self,
        *,
        analysis_request_id: int,
        quality_reports: list[CrawlQualityReport],
    ) -> None:
        self.session.add_all(
            [
                CrawlAnalysisRequestQualityReport(
                    analysis_request_id=analysis_request_id,
                    quality_report_id=report.id,
                )
                for report in quality_reports
            ]
        )
        self.session.flush()

    def quality_reports_for_request(self, analysis_request_id: int) -> list[CrawlQualityReport]:
        stmt = (
            select(CrawlQualityReport)
            .join(
                CrawlAnalysisRequestQualityReport,
                CrawlAnalysisRequestQualityReport.quality_report_id == CrawlQualityReport.id,
            )
            .where(CrawlAnalysisRequestQualityReport.analysis_request_id == analysis_request_id)
            .order_by(CrawlQualityReport.trade_date, CrawlQualityReport.id)
        )
        return list(self.session.scalars(stmt).all())

    def get_report(self, analysis_request_id: int) -> CrawlAnalysisReport | None:
        return self.session.scalar(
            select(CrawlAnalysisReport).where(CrawlAnalysisReport.request_id == analysis_request_id)
        )

    def create_report(self, **values) -> CrawlAnalysisReport:
        report = CrawlAnalysisReport(**values)
        self.session.add(report)
        self.session.flush()
        return report
