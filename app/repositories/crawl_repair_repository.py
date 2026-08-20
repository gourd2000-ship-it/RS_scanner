"""Repository for the PostgreSQL-backed Sam repair queue."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
import secrets

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.crawl_repair import (
    CrawlRepairAttempt,
    CrawlRepairRequest,
    CrawlRepairResult,
)


@dataclass(frozen=True)
class RepairClaim:
    request: CrawlRepairRequest
    attempt: CrawlRepairAttempt
    claim_token: str


def hash_claim_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


class CrawlRepairRepository:
    """Persistence operations and atomic state transitions for repair work."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def build_dedupe_key(
        *,
        job_id: int | None,
        symbol: str,
        trade_date: date,
        error_type: str,
        adjusted_price: bool,
    ) -> str:
        job_part = str(job_id) if job_id is not None else "manual"
        return ":".join(
            (
                job_part,
                symbol.strip(),
                trade_date.isoformat(),
                error_type.strip(),
                "adjusted" if adjusted_price else "raw",
            )
        )

    def enqueue(
        self,
        *,
        symbol: str,
        trade_date: date,
        error_type: str,
        job_id: int | None = None,
        crawl_target_result_id: int | None = None,
        history_from: date | None = None,
        operation: str = "daily_chart",
        provider: str = "kiwoom",
        adjusted_price: bool = True,
        max_attempts: int = 3,
        requested_at: datetime | None = None,
    ) -> tuple[CrawlRepairRequest, bool]:
        """Create a request once and return ``(request, created)``."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        requested_at = requested_at or datetime.utcnow()
        dedupe_key = self.build_dedupe_key(
            job_id=job_id,
            symbol=symbol,
            trade_date=trade_date,
            error_type=error_type,
            adjusted_price=adjusted_price,
        )
        existing = self.session.scalar(
            select(CrawlRepairRequest).where(CrawlRepairRequest.dedupe_key == dedupe_key)
        )
        if existing is not None:
            return existing, False

        request = CrawlRepairRequest(
            dedupe_key=dedupe_key,
            job_id=job_id,
            crawl_target_result_id=crawl_target_result_id,
            symbol=symbol.strip(),
            trade_date=trade_date,
            history_from=history_from,
            operation=operation,
            error_type=error_type,
            provider=provider,
            adjusted_price=adjusted_price,
            status="pending",
            application_status="not_applied",
            attempt_count=0,
            max_attempts=max_attempts,
            next_attempt_at=requested_at,
            requested_at=requested_at,
            created_at=requested_at,
            updated_at=requested_at,
        )
        self.session.add(request)
        self.session.flush()
        return request, True

    def get(self, request_id: int) -> CrawlRepairRequest | None:
        return self.session.get(CrawlRepairRequest, request_id)

    def get_by_dedupe_key(self, dedupe_key: str) -> CrawlRepairRequest | None:
        return self.session.scalar(
            select(CrawlRepairRequest).where(CrawlRepairRequest.dedupe_key == dedupe_key)
        )

    def get_for_application(self, request_id: int) -> CrawlRepairRequest | None:
        """Lock one completed request so two reconciler runs cannot apply it together."""
        return self.session.scalar(
            select(CrawlRepairRequest)
            .where(CrawlRepairRequest.id == request_id)
            .with_for_update()
        )

    def list_results(self, request_id: int) -> list[CrawlRepairResult]:
        stmt = (
            select(CrawlRepairResult)
            .where(CrawlRepairResult.request_id == request_id)
            .order_by(CrawlRepairResult.trade_date, CrawlRepairResult.id)
        )
        return list(self.session.scalars(stmt).all())

    def latest_attempt(self, request_id: int) -> CrawlRepairAttempt | None:
        stmt = (
            select(CrawlRepairAttempt)
            .where(CrawlRepairAttempt.request_id == request_id)
            .order_by(CrawlRepairAttempt.attempt_no.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def list_ready_for_application(self, *, limit: int = 100) -> list[CrawlRepairRequest]:
        """Return completed repair requests that have not reached the canonical DB."""
        if limit < 1:
            raise ValueError("limit must be positive")
        stmt = (
            select(CrawlRepairRequest)
            .where(
                CrawlRepairRequest.status == "completed",
                CrawlRepairRequest.application_status == "not_applied",
            )
            .order_by(CrawlRepairRequest.completed_at, CrawlRepairRequest.id)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def _requeue_expired(self, now: datetime) -> None:
        expired = list(
            self.session.scalars(
                select(CrawlRepairRequest).where(
                    CrawlRepairRequest.status == "processing",
                    CrawlRepairRequest.lease_expires_at.is_not(None),
                    CrawlRepairRequest.lease_expires_at <= now,
                )
            ).all()
        )
        for request in expired:
            attempt = self.latest_attempt(request.id)
            if attempt is not None and attempt.status == "processing":
                attempt.status = "failed"
                attempt.finished_at = now
                attempt.error_code = "lease_expired"
                attempt.error_message = "repair claim lease expired"
                attempt.retryable = True
            request.status = "pending"
            request.claimed_by = None
            request.claim_token_hash = None
            request.lease_expires_at = None
            request.next_attempt_at = now
            request.last_error_code = "lease_expired"
            request.last_error_message = "repair claim lease expired"
            request.updated_at = now

    def claim_one(
        self,
        *,
        claimed_by: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> RepairClaim | None:
        """Atomically claim the oldest ready request."""
        if not claimed_by.strip():
            raise ValueError("claimed_by must not be empty")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        now = now or datetime.utcnow()
        self._requeue_expired(now)

        stmt: Select[tuple[CrawlRepairRequest]] = (
            select(CrawlRepairRequest)
            .where(
                CrawlRepairRequest.status == "pending",
                CrawlRepairRequest.next_attempt_at <= now,
                CrawlRepairRequest.attempt_count < CrawlRepairRequest.max_attempts,
            )
            .order_by(CrawlRepairRequest.requested_at, CrawlRepairRequest.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        request = self.session.scalar(stmt)
        if request is None:
            return None

        claim_token = secrets.token_urlsafe(32)
        request.status = "processing"
        request.attempt_count += 1
        request.claim_version += 1
        request.claimed_by = claimed_by.strip()
        request.claim_token_hash = hash_claim_token(claim_token)
        request.claimed_at = now
        request.lease_expires_at = now + timedelta(seconds=lease_seconds)
        request.updated_at = now

        attempt = CrawlRepairAttempt(
            request_id=request.id,
            attempt_no=request.attempt_count,
            executor=claimed_by.strip(),
            status="processing",
            started_at=now,
            created_at=now,
            details={},
        )
        self.session.add(attempt)
        self.session.flush()
        return RepairClaim(request=request, attempt=attempt, claim_token=claim_token)

    def _locked_claim(
        self,
        *,
        request_id: int,
        claim_token: str,
        claim_version: int | None,
        now: datetime,
    ) -> tuple[CrawlRepairRequest, CrawlRepairAttempt]:
        request = self.session.scalar(
            select(CrawlRepairRequest)
            .where(CrawlRepairRequest.id == request_id)
            .with_for_update()
        )
        if request is None:
            raise LookupError(f"repair request not found: {request_id}")
        if request.status != "processing":
            raise ValueError(f"repair request is not processing: {request.status}")
        if request.lease_expires_at is not None and request.lease_expires_at <= now:
            raise ValueError("repair claim lease expired")
        if not request.claim_token_hash or request.claim_token_hash != hash_claim_token(claim_token):
            raise PermissionError("invalid repair claim token")
        if claim_version is None or claim_version != request.claim_version:
            raise PermissionError("stale repair claim version")
        attempt = self.session.scalar(
            select(CrawlRepairAttempt)
            .where(
                CrawlRepairAttempt.request_id == request_id,
                CrawlRepairAttempt.attempt_no == request.attempt_count,
                CrawlRepairAttempt.status == "processing",
            )
            .with_for_update()
        )
        if attempt is None:
            raise ValueError("active repair attempt not found")
        return request, attempt

    def complete(
        self,
        *,
        request_id: int,
        claim_token: str,
        claim_version: int | None,
        rows: Iterable[dict],
        executor: str,
        tool: str,
        mode: str,
        latest_date: date,
        data_complete: bool,
        result_hash: str,
        details: dict | None = None,
        now: datetime | None = None,
    ) -> CrawlRepairRequest:
        now = now or datetime.utcnow()
        request, attempt = self._locked_claim(
            request_id=request_id,
            claim_token=claim_token,
            claim_version=claim_version,
            now=now,
        )
        materialized_rows = list(rows)
        for row in materialized_rows:
            self.session.add(
                CrawlRepairResult(
                    request_id=request.id,
                    attempt_id=attempt.id,
                    application_status="not_applied",
                    created_at=now,
                    **row,
                )
            )
        attempt.executor = executor
        attempt.tool = tool
        attempt.mode = mode
        attempt.status = "completed"
        attempt.finished_at = now
        attempt.row_count = len(materialized_rows)
        attempt.latest_date = latest_date
        attempt.data_complete = data_complete
        attempt.result_hash = result_hash
        attempt.details = details or {}

        request.status = "completed"
        request.completed_at = now
        request.claimed_by = None
        request.claim_token_hash = None
        request.lease_expires_at = None
        request.last_error_code = None
        request.last_error_message = None
        request.last_http_status = None
        request.updated_at = now
        self.session.flush()
        return request

    def fail(
        self,
        *,
        request_id: int,
        claim_token: str,
        claim_version: int | None,
        error_code: str,
        error_message: str,
        retryable: bool,
        http_status: int | None = None,
        retry_after_seconds: int = 0,
        details: dict | None = None,
        now: datetime | None = None,
    ) -> CrawlRepairRequest:
        now = now or datetime.utcnow()
        request, attempt = self._locked_claim(
            request_id=request_id,
            claim_token=claim_token,
            claim_version=claim_version,
            now=now,
        )
        attempt.status = "failed"
        attempt.finished_at = now
        attempt.error_code = error_code
        attempt.error_message = error_message[:1000]
        attempt.http_status = http_status
        attempt.retryable = retryable
        attempt.details = details or {}

        can_retry = retryable and request.attempt_count < request.max_attempts
        request.status = "pending" if can_retry else "failed"
        request.next_attempt_at = now + timedelta(seconds=max(0, retry_after_seconds))
        request.last_error_code = error_code
        request.last_error_message = error_message[:1000]
        request.last_http_status = http_status
        request.claimed_by = None
        request.claim_token_hash = None
        request.lease_expires_at = None
        request.updated_at = now
        self.session.flush()
        return request

    def set_application_status(
        self,
        *,
        request_id: int,
        application_status: str,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> CrawlRepairRequest:
        if application_status not in {"applied", "conflict", "rejected"}:
            raise ValueError(f"invalid application status: {application_status}")
        request = self.session.get(CrawlRepairRequest, request_id)
        if request is None:
            raise LookupError(f"repair request not found: {request_id}")
        now = now or datetime.utcnow()
        request.application_status = application_status
        request.application_error = error_message[:1000] if error_message else None
        request.applied_at = now if application_status == "applied" else None
        request.updated_at = now
        self.session.query(CrawlRepairResult).filter(
            CrawlRepairResult.request_id == request_id
        ).update(
            {
                CrawlRepairResult.application_status: application_status,
                CrawlRepairResult.application_error: request.application_error,
                CrawlRepairResult.applied_at: request.applied_at,
            },
            synchronize_session=False,
        )
        self.session.flush()
        return request
