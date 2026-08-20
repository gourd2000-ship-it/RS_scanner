"""KRX 기준일 유니버스 snapshot 저장소."""

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.krx_universe import KrxUniverseMembership, KrxUniverseSnapshot


@dataclass(frozen=True)
class KrxMembershipInput:
    code: str
    isin: str | None
    name: str
    market: str
    security_type: str
    listing_status: str = "listed_observed"
    trading_status: str = "unknown"
    listed_at: date | None = None
    raw_fields: dict = field(default_factory=dict)


class KrxUniverseRepository:
    """KRX 원본 snapshot을 기존 symbols와 분리해 저장한다."""

    _TERMINAL_STATUSES = {"completed", "partial", "failed"}

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_snapshot(
        self,
        *,
        crawl_job_id: int | None,
        source: str,
        as_of_date: date,
        scope: str,
        source_metadata: dict | None = None,
    ) -> KrxUniverseSnapshot:
        snapshot = KrxUniverseSnapshot(
            crawl_job_id=crawl_job_id,
            source=source,
            scope=scope,
            as_of_date=as_of_date,
            status="running",
            source_metadata=source_metadata or {},
            started_at=datetime.utcnow(),
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def add_memberships(
        self,
        snapshot_id: int,
        members: list[KrxMembershipInput],
    ) -> list[KrxUniverseMembership]:
        if self.session.get(KrxUniverseSnapshot, snapshot_id) is None:
            raise ValueError(f"KRX universe snapshot을 찾을 수 없습니다: {snapshot_id}")

        codes = [member.code for member in members]
        if len(codes) != len(set(codes)):
            raise ValueError("하나의 KRX snapshot에는 중복 종목코드를 저장할 수 없습니다")

        rows = [
            KrxUniverseMembership(
                snapshot_id=snapshot_id,
                code=member.code,
                isin=member.isin,
                name=member.name,
                market=member.market,
                security_type=member.security_type,
                listing_status=member.listing_status,
                trading_status=member.trading_status,
                listed_at=member.listed_at,
                raw_fields=member.raw_fields,
            )
            for member in members
        ]
        self.session.add_all(rows)
        self.session.flush()
        return rows

    def complete_snapshot(
        self,
        snapshot_id: int,
        *,
        status: str,
        members_seen: int,
        members_valid: int,
        duplicate_count: int = 0,
        invalid_count: int = 0,
        snapshot_hash: str | None = None,
        error_message: str | None = None,
    ) -> KrxUniverseSnapshot:
        if status not in self._TERMINAL_STATUSES:
            raise ValueError(f"허용되지 않은 KRX snapshot 완료 상태입니다: {status}")

        snapshot = self.session.get(KrxUniverseSnapshot, snapshot_id)
        if snapshot is None:
            raise ValueError(f"KRX universe snapshot을 찾을 수 없습니다: {snapshot_id}")

        snapshot.status = status
        snapshot.members_seen = members_seen
        snapshot.members_valid = members_valid
        snapshot.duplicate_count = duplicate_count
        snapshot.invalid_count = invalid_count
        snapshot.snapshot_hash = snapshot_hash
        snapshot.error_message = error_message
        snapshot.finished_at = datetime.utcnow()
        self.session.flush()
        return snapshot

    def get(self, snapshot_id: int) -> KrxUniverseSnapshot | None:
        return self.session.get(KrxUniverseSnapshot, snapshot_id)

    def get_latest_completed(self, *, scope: str) -> KrxUniverseSnapshot | None:
        stmt = (
            select(KrxUniverseSnapshot)
            .where(
                KrxUniverseSnapshot.scope == scope,
                KrxUniverseSnapshot.status == "completed",
            )
            .order_by(
                KrxUniverseSnapshot.as_of_date.desc(),
                KrxUniverseSnapshot.id.desc(),
            )
            .limit(1)
        )
        return self.session.scalar(stmt)

    def list_memberships(self, snapshot_id: int) -> list[KrxUniverseMembership]:
        stmt = (
            select(KrxUniverseMembership)
            .where(KrxUniverseMembership.snapshot_id == snapshot_id)
            .order_by(KrxUniverseMembership.code)
        )
        return list(self.session.scalars(stmt).all())
