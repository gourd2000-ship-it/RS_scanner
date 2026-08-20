"""Persist KRX membership observations without changing the Naver universe."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from typing import Protocol

from app.crawler.sources.krx import KrxUniverseFetchResult
from app.repositories.krx_universe_repository import KrxMembershipInput
from app.services.batch.context import BatchContext


class KrxUniverseSource(Protocol):
    def fetch_stock_membership(self, as_of_date: date) -> KrxUniverseFetchResult: ...


@dataclass(frozen=True)
class KrxUniverseSyncResult:
    snapshot_id: int
    status: str
    member_count: int
    error_message: str | None = None


def sync_krx_universe(
    context: BatchContext,
    source: KrxUniverseSource,
) -> KrxUniverseSyncResult:
    """Write one KRX shadow snapshot and leave the Naver target state untouched."""
    repository = context.krx_universe_repository
    if repository is None:
        raise RuntimeError("KRX universe repository가 설정되지 않았습니다")
    if not isinstance(context.target_date, date):
        raise RuntimeError("KRX snapshot 기준일이 설정되지 않았습니다")

    requested_as_of_date = context.target_date
    try:
        fetch_latest = getattr(source, "fetch_latest_stock_membership", None)
        fetched = (
            fetch_latest(requested_as_of_date)
            if callable(fetch_latest)
            else source.fetch_stock_membership(requested_as_of_date)
        )
    except Exception as exc:  # noqa: BLE001 - shadow failures must be recorded
        snapshot = repository.create_snapshot(
            crawl_job_id=context.job_id,
            source="krx_open_api",
            as_of_date=requested_as_of_date,
            scope="stock_membership",
            source_metadata={
                "markets": ["KOSPI", "KOSDAQ"],
                "requested_as_of_date": requested_as_of_date.isoformat(),
            },
        )
        context.krx_universe_snapshot_id = snapshot.id
        return _complete_snapshot(
            context,
            snapshot.id,
            status="failed",
            members=[],
            error_message=f"fetch:{type(exc).__name__}",
        )

    snapshot = repository.create_snapshot(
        crawl_job_id=context.job_id,
        source="krx_open_api",
        as_of_date=fetched.as_of_date,
        scope="stock_membership",
        source_metadata={
            "markets": ["KOSPI", "KOSDAQ"],
            "requested_as_of_date": requested_as_of_date.isoformat(),
        },
    )
    context.krx_universe_snapshot_id = snapshot.id

    members = [
        KrxMembershipInput(
            code=member.code,
            isin=None,
            name=member.name,
            market=member.market,
            security_type=member.security_type,
            listing_status=member.listing_status,
            trading_status=member.trading_status,
            raw_fields=member.raw_fields,
        )
        for member in fetched.members
    ]
    status = "completed" if fetched.complete and members else (
        "partial" if members else "failed"
    )
    try:
        if members:
            repository.add_memberships(snapshot.id, members)
        return _complete_snapshot(
            context,
            snapshot.id,
            status=status,
            members=members,
            error_message=fetched.error_message,
        )
    except Exception as exc:  # noqa: BLE001 - preserve the failed shadow record
        return _complete_snapshot(
            context,
            snapshot.id,
            status="failed",
            members=[],
            error_message=f"persist:{type(exc).__name__}",
        )


def _complete_snapshot(
    context: BatchContext,
    snapshot_id: int,
    *,
    status: str,
    members: list[KrxMembershipInput],
    error_message: str | None,
) -> KrxUniverseSyncResult:
    snapshot_hash = _snapshot_hash(members) if members else None
    context.krx_universe_repository.complete_snapshot(
        snapshot_id,
        status=status,
        members_seen=len(members),
        members_valid=len(members),
        snapshot_hash=snapshot_hash,
        error_message=error_message,
    )
    context.krx_universe_snapshot_status = status
    return KrxUniverseSyncResult(
        snapshot_id=snapshot_id,
        status=status,
        member_count=len(members),
        error_message=error_message,
    )


def _snapshot_hash(members: list[KrxMembershipInput]) -> str:
    canonical_members = [
        {
            "code": member.code,
            "isin": member.isin,
            "name": member.name,
            "market": member.market,
            "security_type": member.security_type,
            "listing_status": member.listing_status,
            "trading_status": member.trading_status,
            "raw_fields": member.raw_fields,
        }
        for member in sorted(members, key=lambda row: row.code)
    ]
    encoded = json.dumps(
        canonical_members,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
