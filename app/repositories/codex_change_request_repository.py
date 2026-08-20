"""Persistence helpers for Codex implementation audit records."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.codex_change_request import CodexChangeRequest


class CodexChangeRequestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_change_request_id(self, change_request_id: str, *, lock: bool = False) -> CodexChangeRequest | None:
        stmt = select(CodexChangeRequest).where(
            CodexChangeRequest.change_request_id == change_request_id
        )
        if lock:
            stmt = stmt.with_for_update()
        return self.session.scalar(stmt)

    def get_by_report_proposal(self, report_id: int, proposal_id: str) -> CodexChangeRequest | None:
        return self.session.scalar(
            select(CodexChangeRequest).where(
                CodexChangeRequest.report_id == report_id,
                CodexChangeRequest.proposal_id == proposal_id,
            )
        )

    def list_for_analysis_request(self, analysis_request_id: int) -> list[CodexChangeRequest]:
        from app.models.crawl_analysis import CrawlAnalysisReport

        return list(
            self.session.scalars(
                select(CodexChangeRequest)
                .join(CrawlAnalysisReport, CrawlAnalysisReport.id == CodexChangeRequest.report_id)
                .where(CrawlAnalysisReport.request_id == analysis_request_id)
                .order_by(CodexChangeRequest.id)
            )
        )

    def create(self, **values) -> CodexChangeRequest:
        change_request = CodexChangeRequest(**values)
        self.session.add(change_request)
        self.session.flush()
        return change_request
