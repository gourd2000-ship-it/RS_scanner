"""Service boundary for creating and reading dataset-pinned indicators."""

from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.models.backtest_dataset import (
    BacktestDatasetIndicatorSnapshot,
    BacktestDatasetIndicatorSnapshotRow,
)
from app.repositories.backtest_indicator_snapshot_repository import BacktestIndicatorSnapshotRepository


class BacktestIndicatorSnapshotService:
    """Expose only complete immutable snapshots to backtest consumers."""

    def __init__(self, session: Session) -> None:
        self.repository = BacktestIndicatorSnapshotRepository(session)

    def create_for_dataset(
        self,
        *,
        dataset_id: str,
        indicator_kind: str,
        source_run_ids_by_instrument: Mapping[int, int],
    ) -> BacktestDatasetIndicatorSnapshot:
        return self.repository.create_snapshot(
            dataset_id=dataset_id,
            indicator_kind=indicator_kind,
            source_run_ids_by_instrument=source_run_ids_by_instrument,
        )

    def get_complete(self, snapshot_id: int) -> BacktestDatasetIndicatorSnapshot | None:
        snapshot = self.repository.get_snapshot(snapshot_id)
        return snapshot if snapshot is not None and snapshot.status == "complete" else None

    def list_rows(self, snapshot_id: int) -> tuple[BacktestDatasetIndicatorSnapshotRow, ...]:
        return self.repository.list_rows(snapshot_id)
