"""User approval and Codex verification state transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.crawl_analysis import CrawlAnalysisReport, CrawlAnalysisRequest
from app.models.codex_change_request import CodexChangeRequest
from app.repositories.codex_change_request_repository import CodexChangeRequestRepository


class CodexChangeStateError(ValueError):
    pass


class CodexChangeService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = CodexChangeRequestRepository(session)

    def create_from_proposal(
        self,
        *,
        change_request_id: str,
        report_id: int,
        proposal_id: str,
        requested_by: str,
    ) -> tuple[CodexChangeRequest, bool]:
        report = self.session.get(CrawlAnalysisReport, report_id)
        if report is None:
            raise LookupError(f"analysis report not found: {report_id}")
        request = self.session.get(CrawlAnalysisRequest, report.request_id)
        if request is None or request.status not in {"report_ready", "codex_reviewed"}:
            raise CodexChangeStateError("analysis request is not ready for Codex review")
        existing = self.repository.get_by_report_proposal(report.id, proposal_id)
        if existing is not None:
            return existing, False
        if self.repository.get_by_change_request_id(change_request_id) is not None:
            raise CodexChangeStateError("change_request_id already exists")
        proposal = _proposal(report.recommendations, proposal_id)
        change_request = self.repository.create(
            change_request_id=change_request_id,
            report_id=report.id,
            proposal_id=proposal_id,
            status="proposed",
            requested_by=requested_by,
            target_files=proposal["target_files"],
            change_scope=proposal["change_scope"],
            risk_level=proposal["risk_level"],
            verification_plan=proposal["tests"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        request.status = "codex_reviewed"
        request.updated_at = datetime.utcnow()
        self.session.flush()
        return change_request, True

    def review(
        self,
        *,
        change_request_id: str,
        action: str,
        reviewed_by: str,
        review_notes: str | None,
    ) -> CodexChangeRequest:
        change_request = self.repository.get_by_change_request_id(change_request_id, lock=True)
        if change_request is None:
            raise LookupError(f"codex change request not found: {change_request_id}")
        now = datetime.utcnow()
        if action == "approved":
            if change_request.status != "proposed":
                raise CodexChangeStateError("only a proposed change may be approved")
            change_request.status = "approved"
            change_request.approved_by = reviewed_by
        elif action == "implemented":
            if change_request.status != "verified":
                raise CodexChangeStateError("only a verified change may be marked implemented")
            change_request.status = "implemented"
        elif action == "deferred":
            if change_request.status not in {"proposed", "approved", "verified", "failed"}:
                raise CodexChangeStateError("change cannot be deferred from its current state")
            change_request.status = "deferred"
        else:
            raise ValueError("unsupported review action")
        change_request.review_notes = review_notes
        change_request.updated_at = now
        self._roll_up_analysis_request(change_request.report_id)
        self.session.flush()
        return change_request

    def record_result(
        self,
        *,
        change_request_id: str,
        status: str,
        codex_run_id: str | None,
        commit_ref: str | None,
        test_results: dict[str, Any],
        review_notes: str | None,
    ) -> CodexChangeRequest:
        change_request = self.repository.get_by_change_request_id(change_request_id, lock=True)
        if change_request is None:
            raise LookupError(f"codex change request not found: {change_request_id}")
        if status == "running":
            if change_request.status != "approved":
                raise CodexChangeStateError("only an approved change may start")
        elif status in {"verified", "failed"}:
            if change_request.status not in {"approved", "running"}:
                raise CodexChangeStateError("only an approved or running change may submit a result")
        else:
            raise ValueError("Codex may record only running, verified, or failed")
        change_request.status = status
        change_request.codex_run_id = codex_run_id
        change_request.commit_ref = commit_ref
        change_request.test_results = test_results
        if review_notes:
            change_request.review_notes = review_notes
        change_request.updated_at = datetime.utcnow()
        self._roll_up_analysis_request(change_request.report_id)
        self.session.flush()
        return change_request

    def _roll_up_analysis_request(self, report_id: int) -> None:
        report = self.session.get(CrawlAnalysisReport, report_id)
        if report is None:
            return
        request = self.session.get(CrawlAnalysisRequest, report.request_id)
        if request is None:
            return
        items = self.repository.list_for_analysis_request(request.id)
        statuses = {item.status for item in items}
        if not items or statuses - {"implemented", "deferred", "failed"}:
            request.status = "codex_reviewed"
        elif "implemented" in statuses and ("deferred" in statuses or "failed" in statuses):
            request.status = "partially_implemented"
        elif statuses == {"implemented"}:
            request.status = "implemented"
        else:
            request.status = "deferred"
        request.updated_at = datetime.utcnow()


def _proposal(recommendations: list[dict[str, Any]], proposal_id: str) -> dict[str, Any]:
    for proposal in recommendations:
        if proposal.get("proposal_id") == proposal_id:
            return proposal
    raise LookupError(f"proposal not found in report: {proposal_id}")
