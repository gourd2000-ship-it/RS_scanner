"""심볼 universe snapshot 저장소."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot


class SymbolUniverseSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_snapshot(
        self,
        *,
        job_id: int | None,
        provider: str,
        market: str = "ALL",
    ) -> SymbolUniverseSnapshot:
        snapshot = SymbolUniverseSnapshot(
            job_id=job_id,
            provider=provider,
            market=market,
            status="running",
            started_at=datetime.utcnow(),
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def complete_snapshot(
        self,
        snapshot_id: int,
        *,
        status: str,
        pages_total: int,
        pages_succeeded: int,
        symbols_seen: int,
        symbols_valid: int,
        duplicate_count: int = 0,
        invalid_count: int = 0,
        snapshot_hash: str | None = None,
        deactivation_candidates: list[str] | None = None,
        error_message: str | None = None,
    ) -> SymbolUniverseSnapshot:
        snapshot = self.session.get(SymbolUniverseSnapshot, snapshot_id)
        if snapshot is None:
            raise ValueError(f"Universe snapshot not found: {snapshot_id}")

        snapshot.status = status
        snapshot.pages_total = pages_total
        snapshot.pages_succeeded = pages_succeeded
        snapshot.symbols_seen = symbols_seen
        snapshot.symbols_valid = symbols_valid
        snapshot.duplicate_count = duplicate_count
        snapshot.invalid_count = invalid_count
        snapshot.snapshot_hash = snapshot_hash
        snapshot.deactivation_candidates = deactivation_candidates or []
        snapshot.error_message = error_message
        snapshot.finished_at = datetime.utcnow()
        self.session.flush()
        return snapshot

    def get(self, snapshot_id: int) -> SymbolUniverseSnapshot | None:
        return self.session.get(SymbolUniverseSnapshot, snapshot_id)

    def list_recent(self, limit: int = 20) -> list[SymbolUniverseSnapshot]:
        stmt = (
            select(SymbolUniverseSnapshot)
            .order_by(SymbolUniverseSnapshot.started_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())
