from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.base import Base
import app.models  # noqa: F401
from app.models.crawl_job import CrawlJob
from app.services.repair_queue import (
    RepairClaimError,
    RepairQueueService,
    RepairResultRow,
    RepairValidationError,
    classify_repair_error,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_request(session: Session):
    job = CrawlJob(job_type="daily_full")
    session.add(job)
    session.flush()
    service = RepairQueueService(session)
    request, created = service.enqueue_from_target(
        job_id=job.id,
        crawl_target_result_id=None,
        symbol="005930",
        trade_date=date(2026, 8, 14),
        history_from=date(2026, 8, 1),
        error_type="empty_response",
    )
    assert created
    return service, request


def valid_row(trade_date: date = date(2026, 8, 13)) -> RepairResultRow:
    return RepairResultRow(
        symbol="005930",
        trade_date=trade_date,
        source="kiwoom",
        adjusted_price=True,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=1000,
        change_rate=Decimal("1.2"),
    )


def test_enqueue_is_idempotent_and_claim_stores_only_token_hash(session):
    service, request = make_request(session)
    duplicate, created = service.enqueue_from_target(
        job_id=request.job_id,
        crawl_target_result_id=None,
        symbol=request.symbol,
        trade_date=request.trade_date,
        history_from=request.history_from,
        error_type=request.error_type,
    )
    assert duplicate.id == request.id
    assert created is False

    claim = service.claim(claimed_by="sam", lease_seconds=300)
    assert claim is not None
    assert claim.request.status == "processing"
    assert claim.request.claim_token_hash != claim.claim_token
    assert claim.request.attempt_count == 1
    assert claim.attempt.attempt_no == 1


def test_complete_validates_and_persists_audited_rows(session):
    service, request = make_request(session)
    claim = service.claim(claimed_by="sam", lease_seconds=300)
    assert claim is not None

    completed = service.complete(
        request_id=request.id,
        claim_token=claim.claim_token,
        claim_version=claim.request.claim_version,
        operation="daily_chart",
        symbol="005930",
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 14),
        adjusted_price=True,
        executor="sam",
        tool="kiwoomcli",
        mode="demo",
        latest_date=date(2026, 8, 13),
        row_count=1,
        data_complete=True,
        rows=[valid_row()],
    )

    assert completed.status == "completed"
    assert completed.application_status == "not_applied"
    assert service.repository.latest_attempt(request.id).status == "completed"
    results = service.repository.list_results(request.id)
    assert len(results) == 1
    assert results[0].close == Decimal("105.0000")


def test_incomplete_result_is_not_accepted_as_success(session):
    service, request = make_request(session)
    claim = service.claim(claimed_by="sam", lease_seconds=300)
    assert claim is not None

    with pytest.raises(RepairValidationError, match="incomplete"):
        service.complete(
            request_id=request.id,
            claim_token=claim.claim_token,
            claim_version=claim.request.claim_version,
            operation="daily_chart",
            symbol="005930",
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 14),
            adjusted_price=True,
            executor="sam",
            tool="kiwoomcli",
            mode="demo",
            latest_date=date(2026, 8, 13),
            row_count=1,
            data_complete=False,
            rows=[valid_row()],
        )

    assert request.status == "processing"
    assert service.repository.list_results(request.id) == []


def test_stale_claim_version_cannot_submit_results(session):
    service, request = make_request(session)
    claim = service.claim(claimed_by="sam", lease_seconds=300)
    assert claim is not None

    with pytest.raises(RepairClaimError, match="stale repair claim version"):
        service.complete(
            request_id=request.id,
            claim_token=claim.claim_token,
            claim_version=claim.request.claim_version + 1,
            operation="daily_chart",
            symbol="005930",
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 14),
            adjusted_price=True,
            executor="sam",
            tool="kiwoomcli",
            mode="demo",
            latest_date=date(2026, 8, 13),
            row_count=1,
            data_complete=True,
            rows=[valid_row()],
        )

    assert request.status == "processing"
    assert service.repository.list_results(request.id) == []


def test_retryable_failure_returns_to_pending_and_terminal_failure_stays_failed(session):
    service, request = make_request(session)
    claim = service.claim(claimed_by="sam", lease_seconds=300)
    assert claim is not None
    pending = service.fail(
        request_id=request.id,
        claim_token=claim.claim_token,
        claim_version=claim.request.claim_version,
        error_code="rate_limit",
        error_message="HTTP 429",
        retryable=True,
        http_status=429,
        retry_after_seconds=60,
    )
    assert pending.status == "pending"
    assert pending.next_attempt_at >= pending.requested_at + timedelta(seconds=60)

    pending.next_attempt_at = pending.requested_at
    claim = service.claim(claimed_by="sam", lease_seconds=300)
    assert claim is not None
    failed = service.fail(
        request_id=request.id,
        claim_token=claim.claim_token,
        claim_version=claim.request.claim_version,
        error_code="auth_failed",
        error_message="token=secret-value",
        retryable=False,
    )
    assert failed.status == "failed"
    assert "secret-value" not in failed.last_error_message


@pytest.mark.parametrize(
    ("status", "error_class", "error_message", "expected"),
    [
        ("failed", "PriceParseError", "response has no data rows", "empty_response"),
        ("partial", "ParseError", "some rows invalid", "partial"),
        ("failed", "CorporateActionError", "corporate action remains", "corporate_action_unresolved"),
        ("failed", "PriceFetchError", "timeout", "failed"),
        ("fetched", None, None, None),
    ],
)
def test_classify_repair_error(status, error_class, error_message, expected):
    assert classify_repair_error(
        status=status,
        error_class=error_class,
        error_message=error_message,
    ) == expected
