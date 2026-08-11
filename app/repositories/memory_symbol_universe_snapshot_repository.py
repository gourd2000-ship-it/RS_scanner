"""심볼 universe snapshot 메모리 저장소 (테스트용)."""

from datetime import datetime


class MemorySymbolUniverseSnapshot:
    def __init__(
        self,
        *,
        id: int,
        job_id: int | None,
        provider: str,
        market: str,
        status: str,
        started_at: datetime,
    ) -> None:
        self.id = id
        self.job_id = job_id
        self.provider = provider
        self.market = market
        self.status = status
        self.pages_total = 0
        self.pages_succeeded = 0
        self.symbols_seen = 0
        self.symbols_valid = 0
        self.duplicate_count = 0
        self.invalid_count = 0
        self.snapshot_hash: str | None = None
        self.deactivation_candidates: list[str] = []
        self.started_at = started_at
        self.finished_at: datetime | None = None
        self.error_message: str | None = None


class MemorySymbolUniverseSnapshotRepository:
    def __init__(self) -> None:
        self._snapshots: dict[int, MemorySymbolUniverseSnapshot] = {}
        self._next_id = 1

    def create_snapshot(
        self,
        *,
        job_id: int | None,
        provider: str,
        market: str = "ALL",
    ) -> MemorySymbolUniverseSnapshot:
        snapshot = MemorySymbolUniverseSnapshot(
            id=self._next_id,
            job_id=job_id,
            provider=provider,
            market=market,
            status="running",
            started_at=datetime.utcnow(),
        )
        self._snapshots[snapshot.id] = snapshot
        self._next_id += 1
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
    ) -> MemorySymbolUniverseSnapshot:
        snapshot = self._snapshots.get(snapshot_id)
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
        snapshot.deactivation_candidates = list(deactivation_candidates or [])
        snapshot.error_message = error_message
        snapshot.finished_at = datetime.utcnow()
        return snapshot

    def get(self, snapshot_id: int) -> MemorySymbolUniverseSnapshot | None:
        return self._snapshots.get(snapshot_id)

    def list_recent(self, limit: int = 20) -> list[MemorySymbolUniverseSnapshot]:
        return sorted(
            self._snapshots.values(),
            key=lambda snapshot: snapshot.started_at,
            reverse=True,
        )[:limit]
