"""Persistence rules for reproducible, single-worker backtest runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from hmac import compare_digest
import json
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.market_calendar import krx_market_day_status
from app.models.backtest_dataset import BacktestDataset, BacktestDatasetRsRun
from app.models.backtest_run import (
    BACKTEST_TERMINAL_STATUSES,
    BacktestBenchmarkSnapshot,
    BacktestBenchmarkSnapshotPrice,
    BacktestDailyEquity,
    BacktestOperatorLockout,
    BacktestOperatorLoginAttempt,
    BacktestOperatorSession,
    BacktestOperatorAuditEvent,
    BacktestOrder,
    BacktestRun,
    BacktestStrategy,
    BacktestStrategyVersion,
    BacktestTrade,
)


@dataclass(frozen=True)
class BenchmarkSnapshotInput:
    """A frozen close series for one of the two mandatory benchmarks."""

    market: str
    benchmark_code: str
    snapshot_hash: str
    prices: tuple[tuple[date, Decimal], ...]


class BacktestRepository:
    """Owns immutable input checks and allowed backtest queue transitions."""

    _TRANSITIONS = {
        "queued": frozenset({"running", "cancelled", "data_unavailable"}),
        "running": frozenset({"completed", "failed"}),
    }

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_strategy(self, *, name: str, config: dict, strategy_id: str | None = None) -> BacktestStrategy:
        if not name.strip():
            raise ValueError("strategy name is required")
        strategy = BacktestStrategy(strategy_id=strategy_id or uuid4().hex, name=name.strip())
        self.session.add(strategy)
        self.session.flush()
        self.add_strategy_version(strategy.id, config=config, version=1)
        self.session.flush()
        return strategy

    def add_strategy_version(
        self, strategy_id: int, *, config: dict, version: int | None = None
    ) -> BacktestStrategyVersion:
        strategy = self.session.get(BacktestStrategy, strategy_id)
        if strategy is None:
            raise KeyError(f"strategy not found: {strategy_id}")
        current_version = self.session.scalar(
            select(func.max(BacktestStrategyVersion.version)).where(
                BacktestStrategyVersion.backtest_strategy_id == strategy_id
            )
        )
        next_version = (current_version or 0) + 1
        if version is not None and version != next_version:
            raise ValueError("strategy versions are immutable and must be appended")
        serialized = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        row = BacktestStrategyVersion(
            backtest_strategy_id=strategy_id,
            version=next_version,
            config=json.loads(serialized),
            config_hash=sha256(serialized.encode()).hexdigest(),
        )
        strategy.updated_at = datetime.now(timezone.utc)
        self.session.add(row)
        self.session.flush()
        return row

    def enqueue_run(
        self,
        *,
        strategy_version_id: int,
        dataset_id: str,
        dataset_manifest_hash: str | None,
        rs_run_id: int,
        rs_result_hash: str,
        range_start: date,
        range_end: date,
        markets: list[str],
        benchmark_snapshots: tuple[BenchmarkSnapshotInput, BenchmarkSnapshotInput],
        candidate_exclusions: list[dict[str, object]] | None = None,
        run_id: str | None = None,
    ) -> BacktestRun:
        if range_start > range_end:
            raise ValueError("range_start must be on or before range_end")
        if not set(markets) or not set(markets) <= {"KOSPI", "KOSDAQ"}:
            raise ValueError("markets must contain KOSPI and/or KOSDAQ")
        version = self.session.get(BacktestStrategyVersion, strategy_version_id)
        if version is None:
            raise KeyError(f"strategy version not found: {strategy_version_id}")
        dataset = self.session.scalar(select(BacktestDataset).where(BacktestDataset.dataset_id == dataset_id))
        if dataset is None:
            raise KeyError(f"dataset not found: {dataset_id}")
        if not dataset.final_manifest_hash or dataset_manifest_hash != dataset.final_manifest_hash:
            raise ValueError("dataset final manifest hash does not match the frozen dataset")
        if not isinstance(dataset.manifest, dict) or self._manifest_hash(dataset.manifest) != dataset.final_manifest_hash:
            raise ValueError("dataset manifest does not match its finalized manifest hash")
        if dataset.status != "active" or dataset.manifest.get("publication_scope") != "complete_segments_only":
            raise ValueError(
                "only active datasets published with complete_segments_only can be used for backtests"
            )
        rs_run = self.session.get(BacktestDatasetRsRun, rs_run_id)
        if rs_run is None or rs_run.backtest_dataset_id != dataset.id:
            raise ValueError("RS run does not belong to the selected dataset")
        if rs_run.status != "completed" or rs_result_hash != rs_run.result_hash:
            raise ValueError("RS result hash does not match a completed dataset RS run")
        snapshot_by_market = {snapshot.market: snapshot for snapshot in benchmark_snapshots}
        if set(snapshot_by_market) != {"KOSPI", "KOSDAQ"}:
            raise ValueError("both KOSPI and KOSDAQ benchmark snapshots are required")
        expected_benchmark_dates = self._krx_dates(
            range_start, range_end, configured_closed_dates=get_settings().market_closed_dates
        )
        canonical_snapshots = tuple(
            self._canonical_benchmark_snapshot(snapshot, expected_dates=expected_benchmark_dates)
            for snapshot in (snapshot_by_market["KOSPI"], snapshot_by_market["KOSDAQ"])
        )

        run = BacktestRun(
            run_id=run_id or uuid4().hex,
            backtest_strategy_version_id=version.id,
            backtest_dataset_id=dataset.id,
            backtest_dataset_rs_run_id=rs_run.id,
            dataset_id=dataset.dataset_id,
            dataset_manifest_hash=dataset.final_manifest_hash,
            rs_formula_version=rs_run.formula_version,
            rs_result_hash=rs_run.result_hash,
            range_start=range_start,
            range_end=range_end,
            markets=sorted(set(markets)),
            candidate_exclusions=candidate_exclusions or [],
            status="queued",
        )
        for snapshot in canonical_snapshots:
            frozen = BacktestBenchmarkSnapshot(
                market=snapshot.market,
                benchmark_code=snapshot.benchmark_code,
                snapshot_hash=snapshot.snapshot_hash,
            )
            frozen.prices = [
                BacktestBenchmarkSnapshotPrice(trade_date=trade_date, close=close)
                for trade_date, close in snapshot.prices
            ]
            run.benchmark_snapshots.append(frozen)
        self.session.add(run)
        self.session.flush()
        return run

    def record_data_unavailable_run(
        self, *, strategy_version_id: int, range_start: date, range_end: date, markets: list[str],
        reasons: list[dict[str, object]], dataset: BacktestDataset | None = None,
        rs_run: BacktestDatasetRsRun | None = None, run_id: str | None = None,
    ) -> BacktestRun:
        """Persist a failed input attempt without inventing missing lineage."""
        if range_start > range_end or not set(markets) or not set(markets) <= {"KOSPI", "KOSDAQ"}:
            raise ValueError("invalid backtest range or markets")
        version = self.session.get(BacktestStrategyVersion, strategy_version_id)
        if version is None:
            raise KeyError(f"strategy version not found: {strategy_version_id}")
        if rs_run is not None and (dataset is None or rs_run.backtest_dataset_id != dataset.id):
            raise ValueError("RS run does not belong to data-unavailable dataset")
        run = BacktestRun(
            run_id=run_id or uuid4().hex, backtest_strategy_version_id=version.id,
            backtest_dataset_id=dataset.id if dataset else None,
            backtest_dataset_rs_run_id=rs_run.id if rs_run else None,
            dataset_id=dataset.dataset_id if dataset else None,
            dataset_manifest_hash=dataset.final_manifest_hash if dataset else None,
            rs_formula_version=rs_run.formula_version if rs_run else None,
            rs_result_hash=rs_run.result_hash if rs_run else None,
            range_start=range_start, range_end=range_end, markets=sorted(set(markets)),
            status="queued",
        )
        self.session.add(run)
        self.session.flush()
        # The database queue trigger requires all rows to enter as queued.
        return self._transition(run, "data_unavailable", "data_unavailable", json.dumps(reasons, ensure_ascii=False, separators=(",", ":"), default=str))

    def get_run(self, run_id: str) -> BacktestRun | None:
        return self.session.scalar(
            select(BacktestRun)
            .options(
                selectinload(BacktestRun.benchmark_snapshots).selectinload(BacktestBenchmarkSnapshot.prices),
                selectinload(BacktestRun.daily_equity),
                selectinload(BacktestRun.orders),
                selectinload(BacktestRun.trades),
            )
            .where(BacktestRun.run_id == run_id)
        )

    def claim_next_run(self) -> BacktestRun | None:
        """Claim one FIFO item. PostgreSQL locks make concurrent workers skip it."""
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            acquired = self.session.scalar(select(func.pg_try_advisory_xact_lock(90821, 1)))
            if not acquired:
                return None
        # The partial unique index is the durable guarantee after the advisory
        # transaction lock is released on commit.
        if self.session.scalar(select(BacktestRun.id).where(BacktestRun.status == "running").limit(1)) is not None:
            return None
        run = self.session.scalar(
            select(BacktestRun)
            .where(BacktestRun.status == "queued")
            .order_by(BacktestRun.queued_at, BacktestRun.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run is None:
            return None
        return self._transition(run, "running")

    def cancel_queued_run(self, run_id: str) -> BacktestRun:
        run = self._required_run(run_id)
        if run.status != "queued":
            raise ValueError("only queued backtest runs can be cancelled")
        return self._transition(run, "cancelled")

    def transition_run(
        self, run_id: str, new_status: str, *, error_code: str | None = None, error_detail: str | None = None
    ) -> BacktestRun:
        return self._transition(self._required_run(run_id), new_status, error_code, error_detail)

    def add_daily_equity(
        self, run_id: str, *, trade_date: date, cash: Decimal, holdings_value: Decimal, net_asset_value: Decimal,
        holdings: dict | None = None,
    ) -> BacktestDailyEquity:
        run = self._mutable_run(run_id)
        row = BacktestDailyEquity(
            backtest_run_id=run.id, trade_date=trade_date, cash=cash,
            holdings_value=holdings_value, net_asset_value=net_asset_value, holdings=holdings or {},
        )
        self.session.add(row)
        self.session.flush()
        return row

    def add_order(self, run_id: str, **values: object) -> BacktestOrder:
        run = self._mutable_run(run_id)
        row = BacktestOrder(backtest_run_id=run.id, **values)
        self.session.add(row)
        self.session.flush()
        return row

    def add_trade(self, run_id: str, **values: object) -> BacktestTrade:
        run = self._mutable_run(run_id)
        row = BacktestTrade(backtest_run_id=run.id, **values)
        self.session.add(row)
        self.session.flush()
        return row

    def create_operator_session(
        self, *, session_token_hash: str, operator_subject_hash: str,
        csrf_token_hash: str | None = None,
        expires_at: datetime, is_operator: bool = False,
    ) -> BacktestOperatorSession:
        self._validate_hash(session_token_hash, "session token")
        csrf_token_hash = csrf_token_hash or session_token_hash
        self._validate_hash(csrf_token_hash, "CSRF token")
        self._validate_hash(operator_subject_hash, "operator subject")
        row = BacktestOperatorSession(
            session_token_hash=session_token_hash,
            csrf_token_hash=csrf_token_hash,
            operator_subject_hash=operator_subject_hash,
            expires_at=expires_at,
            is_operator=is_operator,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_active_operator_session(
        self, *, session_token_hash: str, now: datetime
    ) -> BacktestOperatorSession | None:
        self._validate_hash(session_token_hash, "session token")
        return self.session.scalar(
            select(BacktestOperatorSession).where(
                BacktestOperatorSession.session_token_hash == session_token_hash,
                BacktestOperatorSession.revoked_at.is_(None),
                BacktestOperatorSession.expires_at > now,
            )
        )

    def get_active_operator_session_with_csrf(
        self, *, session_token_hash: str, csrf_token_hash: str, now: datetime,
        require_operator: bool = True,
    ) -> BacktestOperatorSession | None:
        self._validate_hash(csrf_token_hash, "CSRF token")
        row = self.get_active_operator_session(session_token_hash=session_token_hash, now=now)
        if row is None or not compare_digest(row.csrf_token_hash, csrf_token_hash):
            return None
        if require_operator and not row.is_operator:
            return None
        return row

    def revoke_operator_session(self, *, session_token_hash: str, now: datetime) -> None:
        row = self.get_active_operator_session(session_token_hash=session_token_hash, now=now)
        if row is not None:
            row.revoked_at = now
            self.session.flush()

    def record_login_success(self, *, subject_hash: str, now: datetime) -> BacktestOperatorLoginAttempt:
        self._validate_hash(subject_hash, "login subject")
        row = BacktestOperatorLoginAttempt(subject_hash=subject_hash, succeeded=True, attempted_at=now)
        self.session.add(row)
        self.session.flush()
        return row

    def record_login_failure(
        self, *, subject_hash: str, now: datetime, max_failures: int = 5, window: timedelta = timedelta(minutes=15),
        lock_duration: timedelta = timedelta(minutes=15),
    ) -> BacktestOperatorLockout | None:
        """Record only a hashed subject; no supplied password reaches persistence."""
        self._validate_hash(subject_hash, "login subject")
        if max_failures < 1:
            raise ValueError("max_failures must be positive")
        self.session.add(BacktestOperatorLoginAttempt(subject_hash=subject_hash, succeeded=False, attempted_at=now))
        self.session.flush()
        count = self.session.scalar(
            select(func.count(BacktestOperatorLoginAttempt.id)).where(
                BacktestOperatorLoginAttempt.subject_hash == subject_hash,
                BacktestOperatorLoginAttempt.succeeded.is_(False),
                BacktestOperatorLoginAttempt.attempted_at >= now - window,
            )
        ) or 0
        if count < max_failures:
            return None
        row = self.session.scalar(
            select(BacktestOperatorLockout).where(BacktestOperatorLockout.subject_hash == subject_hash)
        )
        if row is None:
            row = BacktestOperatorLockout(subject_hash=subject_hash, locked_until=now + lock_duration, updated_at=now)
            self.session.add(row)
        else:
            row.locked_until = now + lock_duration
            row.updated_at = now
        self.session.flush()
        return row

    def is_login_locked(self, *, subject_hash: str, now: datetime) -> bool:
        self._validate_hash(subject_hash, "login subject")
        row = self.session.scalar(
            select(BacktestOperatorLockout).where(BacktestOperatorLockout.subject_hash == subject_hash)
        )
        if row is None:
            return False
        # SQLite test storage does not round-trip timezone information, while
        # PostgreSQL does. Compare equivalent UTC wall-clock values here.
        comparison_now = now.replace(tzinfo=None) if row.locked_until.tzinfo is None else now
        return row.locked_until > comparison_now

    def record_operator_audit(
        self, *, subject_hash: str, event_type: str, result: str, request_id: str | None = None,
        now: datetime | None = None,
    ) -> BacktestOperatorAuditEvent:
        self._validate_hash(subject_hash, "operator subject")
        row = BacktestOperatorAuditEvent(
            subject_hash=subject_hash, event_type=event_type, result=result,
            request_id=(request_id or None), created_at=now or datetime.now(timezone.utc),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def _required_run(self, run_id: str) -> BacktestRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(f"backtest run not found: {run_id}")
        return run

    def _mutable_run(self, run_id: str) -> BacktestRun:
        run = self._required_run(run_id)
        if run.status in BACKTEST_TERMINAL_STATUSES:
            raise ValueError("terminal backtest results are immutable")
        return run

    def _transition(
        self, run: BacktestRun, new_status: str, error_code: str | None = None, error_detail: str | None = None
    ) -> BacktestRun:
        if run.status in BACKTEST_TERMINAL_STATUSES:
            raise ValueError("terminal backtest runs cannot change status")
        if new_status not in self._TRANSITIONS.get(run.status, frozenset()):
            raise ValueError(f"invalid backtest status transition: {run.status} -> {new_status}")
        now = datetime.now(timezone.utc)
        run.status = new_status
        if new_status == "running":
            run.started_at = now
        if new_status in BACKTEST_TERMINAL_STATUSES:
            run.finished_at = now
        run.error_code = error_code
        run.error_detail = error_detail
        self.session.flush()
        return run

    @staticmethod
    def _validate_hash(value: str, label: str) -> None:
        if len(value) != 64:
            raise ValueError(f"{label} hash must be a SHA-256 digest")

    @staticmethod
    def _manifest_hash(manifest: dict) -> str:
        serialized = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        return sha256(serialized.encode()).hexdigest()

    @staticmethod
    def _krx_dates(range_start: date, range_end: date, *, configured_closed_dates: str) -> set[date]:
        dates: set[date] = set()
        current = range_start
        while current <= range_end:
            if krx_market_day_status(current, configured_closed_dates=configured_closed_dates).is_open:
                dates.add(current)
            current += timedelta(days=1)
        if range_start not in dates or range_end not in dates:
            raise ValueError("backtest boundaries must be configured Korean trading days")
        return dates

    @staticmethod
    def _canonical_benchmark_snapshot(
        snapshot: BenchmarkSnapshotInput, *, expected_dates: set[date],
    ) -> BenchmarkSnapshotInput:
        if snapshot.market not in {"KOSPI", "KOSDAQ"}:
            raise ValueError("unknown benchmark market")
        prices_by_date = dict(snapshot.prices)
        if len(prices_by_date) != len(snapshot.prices) or set(prices_by_date) != expected_dates:
            raise ValueError("benchmark snapshot coverage must match every Korean trading date")
        canonical_prices = tuple(sorted((trade_date, Decimal(close)) for trade_date, close in prices_by_date.items()))
        material = [
            [snapshot.market, snapshot.benchmark_code, trade_date.isoformat(), format(close, "f")]
            for trade_date, close in canonical_prices
        ]
        canonical_hash = sha256(json.dumps(material, separators=(",", ":")).encode()).hexdigest()
        return BenchmarkSnapshotInput(snapshot.market, snapshot.benchmark_code, canonical_hash, canonical_prices)
