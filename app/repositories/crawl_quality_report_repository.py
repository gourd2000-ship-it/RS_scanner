"""Persistence helpers for immutable crawl quality reports."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crawl_quality_report import CrawlQualityReport


class CrawlQualityReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_job_id(self, crawl_job_id: int) -> CrawlQualityReport | None:
        return self.session.scalar(
            select(CrawlQualityReport).where(CrawlQualityReport.crawl_job_id == crawl_job_id)
        )

    def create(self, **values) -> CrawlQualityReport:
        report = CrawlQualityReport(**values)
        self.session.add(report)
        self.session.flush()
        return report
