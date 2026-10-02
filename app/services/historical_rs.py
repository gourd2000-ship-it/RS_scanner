"""Calculate dated RS from immutable backtest-dataset price copies only."""

from dataclasses import dataclass
from datetime import datetime, time, timezone
from hashlib import sha256
import json

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.models.backtest_dataset import BacktestDataset, BacktestDatasetRs, BacktestDatasetRsRun
from app.schemas.market_data import DailyPricePayload
from app.services.rs.calculator import MIN_REQUIRED_PRICES, SymbolSeries, calculate_combined_rs


@dataclass(frozen=True)
class HistoricalRsPolicy:
    version: str


@dataclass(frozen=True)
class HistoricalRsResult:
    run: BacktestDatasetRsRun
    rows: tuple[BacktestDatasetRs, ...]
    result_hash: str


def calculate_historical_rs(session: Session, *, dataset_id: str, policy: HistoricalRsPolicy) -> HistoricalRsResult:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        return _calculate_historical_rs_postgresql(session, dataset_id=dataset_id, policy=policy)
    dataset = session.scalar(select(BacktestDataset).options(
        selectinload(BacktestDataset.prices), selectinload(BacktestDataset.memberships), selectinload(BacktestDataset.rs_runs).selectinload(BacktestDatasetRsRun.rows)
    ).where(BacktestDataset.dataset_id == dataset_id))
    if dataset is None:
        raise ValueError(f"dataset not found: {dataset_id}")
    existing = next((run for run in dataset.rs_runs if run.formula_version == policy.version), None)
    if existing is not None:
        return HistoricalRsResult(existing, tuple(existing.rows), existing.result_hash)
    prices_by_instrument: dict[int, list] = {}
    for price in dataset.prices:
        prices_by_instrument.setdefault(price.instrument_id, []).append(price)
    run = BacktestDatasetRsRun(
        formula_version=policy.version, policy_version=dataset.policy_version,
        input_hash=_hash([_price_material(row) for row in dataset.prices]), result_hash="", manifest={},
    )
    dataset.rs_runs.append(run)
    for target in dataset.memberships:
        available = sorted((row for row in prices_by_instrument.get(target.instrument_id, []) if row.trade_date <= target.trade_date), key=lambda row: row.trade_date)
        reason = None
        if target.price_expectation != "expected":
            reason = "outside_trading_interval"
        elif not any(row.trade_date == target.trade_date for row in available):
            reason = "price_missing"
        elif len(available) < MIN_REQUIRED_PRICES:
            reason = "insufficient_history"
        if reason is not None:
            run.rows.append(_unavailable(run, dataset, target, available, reason))
    eligible = [target for target in dataset.memberships if not any(row.instrument_id == target.instrument_id and row.trade_date == target.trade_date for row in run.rows)]
    for target_date in sorted({target.trade_date for target in eligible}):
        targets = [target for target in eligible if target.trade_date == target_date]
        series_by_market = {}
        for target in targets:
            rows = sorted((row for row in prices_by_instrument.get(target.instrument_id, []) if row.trade_date <= target_date), key=lambda row: row.trade_date)
            series_by_market.setdefault(target.market, []).append(SymbolSeries(
                code=str(target.instrument_id), market=target.market,
                prices=[DailyPricePayload(trade_date=row.trade_date, open=row.open, high=row.high, low=row.low, close=row.close, volume=row.volume, change_rate=row.change_rate) for row in rows],
            ))
        results = {int(row.code): row for row in calculate_combined_rs(series_by_market, target_date=target_date)}
        for target in targets:
            payload = results.get(target.instrument_id)
            rows = [row for row in prices_by_instrument.get(target.instrument_id, []) if row.trade_date <= target_date]
            if payload is None:
                run.rows.append(_unavailable(run, dataset, target, rows, "insufficient_history"))
            else:
                run.rows.append(BacktestDatasetRs(
                    backtest_dataset_id=dataset.id, instrument_id=target.instrument_id, code=next(row.code for row in rows if row.trade_date == target_date), market=target.market,
                    trade_date=target_date, status="available", reason_code=None, required_observations=MIN_REQUIRED_PRICES, available_observations=len(rows),
                    available_at=datetime.combine(target_date, time.max, tzinfo=timezone.utc),
                    return_1m=payload.return_1m, return_3m=payload.return_3m, return_6m=payload.return_6m, return_9m=payload.return_9m, return_12m=payload.return_12m,
                    relative_return_score=payload.relative_return_score, rs_percentile=payload.rs_percentile, rs_1m=payload.rs_1m, rs_3m=payload.rs_3m, rs_6m=payload.rs_6m, rs_12m=payload.rs_12m,
                    rs_rating=payload.rs_rating, rank_in_market=payload.rank_in_market, rank_in_universe=payload.rank_in_universe,
                    input_hash=_hash([_price_material(row) for row in rows]),
                ))
    session.flush()
    run.result_hash = _hash([_rs_material(row) for row in run.rows])
    run.manifest = {"formula_version": policy.version, "policy_version": dataset.policy_version, "input_hash": run.input_hash, "result_hash": run.result_hash}
    dataset.manifest = {**dataset.manifest, "rs": run.manifest}
    dataset.final_manifest_hash = _hash(dataset.manifest)
    session.flush()
    return HistoricalRsResult(run, tuple(run.rows), run.result_hash)


def _calculate_historical_rs_postgresql(
    session: Session, *, dataset_id: str, policy: HistoricalRsPolicy
) -> HistoricalRsResult:
    """Materialize the full historical RS relation without loading it into Python.

    The reference implementation above is intentionally retained for portable
    unit tests.  A production dataset has millions of memberships, so the
    PostgreSQL path performs the identical observation-count gates and dated
    return windows in one database statement, then ranks only eligible rows
    per trade date.  Missing price and insufficient-history rows remain
    explicit ``unavailable`` records.
    """
    dataset = session.scalar(select(BacktestDataset).where(BacktestDataset.dataset_id == dataset_id))
    if dataset is None:
        raise ValueError(f"dataset not found: {dataset_id}")
    existing = session.scalar(select(BacktestDatasetRsRun).where(
        BacktestDatasetRsRun.backtest_dataset_id == dataset.id,
        BacktestDatasetRsRun.formula_version == policy.version,
    ))
    if existing is not None:
        return HistoricalRsResult(existing, (), existing.result_hash)

    input_hash = dataset.manifest["watermark"]["price_snapshot_hash"]
    run = BacktestDatasetRsRun(
        backtest_dataset_id=dataset.id,
        formula_version=policy.version,
        policy_version=dataset.policy_version,
        input_hash=input_hash,
        result_hash="",
        manifest={},
    )
    session.add(run)
    session.flush()
    session.execute(text(_POSTGRESQL_RS_INSERT), {
        "dataset_id": dataset.id,
        "run_id": run.id,
        "input_hash": input_hash,
    })
    total_rows = session.scalar(select(func.count()).select_from(BacktestDatasetRs).where(
        BacktestDatasetRs.backtest_dataset_rs_run_id == run.id
    ))
    available_rows = session.scalar(select(func.count()).select_from(BacktestDatasetRs).where(
        BacktestDatasetRs.backtest_dataset_rs_run_id == run.id,
        BacktestDatasetRs.status == "available",
    ))
    run.result_hash = _hash({
        "formula_version": policy.version,
        "input_hash": input_hash,
        "total_rows": total_rows,
        "available_rows": available_rows,
    })
    run.manifest = {
        "formula_version": policy.version,
        "policy_version": dataset.policy_version,
        "input_hash": input_hash,
        "result_hash": run.result_hash,
        "execution": "postgresql-window-v1",
        "total_rows": total_rows,
        "available_rows": available_rows,
    }
    dataset.manifest = {**dataset.manifest, "rs": run.manifest}
    dataset.final_manifest_hash = _hash(dataset.manifest)
    session.flush()
    return HistoricalRsResult(run, (), run.result_hash)


_POSTGRESQL_RS_INSERT = """
WITH history AS (
    SELECT
        p.instrument_id, p.trade_date, p.code, p.close,
        row_number() OVER (PARTITION BY p.instrument_id ORDER BY p.trade_date) AS observations,
        lag(p.close, 21) OVER (PARTITION BY p.instrument_id ORDER BY p.trade_date) AS c21,
        lag(p.close, 63) OVER (PARTITION BY p.instrument_id ORDER BY p.trade_date) AS c63,
        lag(p.close, 126) OVER (PARTITION BY p.instrument_id ORDER BY p.trade_date) AS c126,
        lag(p.close, 189) OVER (PARTITION BY p.instrument_id ORDER BY p.trade_date) AS c189,
        lag(p.close, 252) OVER (PARTITION BY p.instrument_id ORDER BY p.trade_date) AS c252
    FROM backtest_dataset_prices p
    WHERE p.backtest_dataset_id = :dataset_id
), base AS (
    SELECT
        m.instrument_id, m.market, m.trade_date, m.price_expectation,
        h.code, h.observations, h.close, h.c21, h.c63, h.c126, h.c189, h.c252,
        CASE WHEN m.price_expectation = 'expected' AND h.c252 IS NOT NULL THEN h.close / h.c21 - 1 END AS r1,
        CASE WHEN m.price_expectation = 'expected' AND h.c252 IS NOT NULL THEN h.close / h.c63 - 1 END AS r3,
        CASE WHEN m.price_expectation = 'expected' AND h.c252 IS NOT NULL THEN h.close / h.c126 - 1 END AS r6,
        CASE WHEN m.price_expectation = 'expected' AND h.c252 IS NOT NULL THEN h.close / h.c189 - 1 END AS r9,
        CASE WHEN m.price_expectation = 'expected' AND h.c252 IS NOT NULL THEN h.close / h.c252 - 1 END AS r12
    FROM backtest_dataset_memberships m
    LEFT JOIN history h ON h.instrument_id = m.instrument_id AND h.trade_date = m.trade_date
    WHERE m.backtest_dataset_id = :dataset_id
), scored AS (
    SELECT *,
        CASE WHEN c252 IS NOT NULL AND price_expectation = 'expected' THEN
            0.25 * (r3 + ((1 + r6) / (1 + r3) - 1) + ((1 + r9) / (1 + r6) - 1) + ((1 + r12) / (1 + r9) - 1))
        END AS score
    FROM base
), ranked AS (
    SELECT *,
        count(*) FILTER (WHERE score IS NOT NULL) OVER (PARTITION BY trade_date) AS eligible_count,
        rank() OVER (PARTITION BY trade_date ORDER BY score DESC NULLS LAST, instrument_id) AS overall_rank,
        rank() OVER (PARTITION BY trade_date ORDER BY r1 DESC NULLS LAST, instrument_id) AS rank_1m,
        rank() OVER (PARTITION BY trade_date ORDER BY r3 DESC NULLS LAST, instrument_id) AS rank_3m,
        rank() OVER (PARTITION BY trade_date ORDER BY r6 DESC NULLS LAST, instrument_id) AS rank_6m,
        rank() OVER (PARTITION BY trade_date ORDER BY r12 DESC NULLS LAST, instrument_id) AS rank_12m
    FROM scored
)
INSERT INTO backtest_dataset_rs (
    backtest_dataset_rs_run_id, backtest_dataset_id, instrument_id, code, market, trade_date,
    status, reason_code, required_observations, available_observations, available_at,
    return_1m, return_3m, return_6m, return_9m, return_12m, relative_return_score,
    rs_percentile, rs_1m, rs_3m, rs_6m, rs_12m, rs_rating, rank_in_market,
    rank_in_universe, input_hash
)
SELECT
    :run_id, :dataset_id, instrument_id, coalesce(code, instrument_id::text), market, trade_date,
    CASE WHEN score IS NOT NULL THEN 'available' ELSE 'unavailable' END,
    CASE
        WHEN score IS NOT NULL THEN NULL
        WHEN price_expectation <> 'expected' THEN 'outside_trading_interval'
        WHEN close IS NULL THEN 'price_missing'
        ELSE 'insufficient_history'
    END,
    253, coalesce(least(observations, 253), 0),
    CASE WHEN score IS NOT NULL THEN (trade_date::timestamp + time '23:59:59.999999') AT TIME ZONE 'UTC' END,
    r1, r3, r6, r9, r12, score,
    CASE WHEN score IS NOT NULL AND eligible_count > 1 THEN (eligible_count - overall_rank)::numeric / (eligible_count - 1)
         WHEN score IS NOT NULL THEN 1 ELSE NULL END,
    CASE WHEN score IS NOT NULL THEN least(99, greatest(1, round(98 * (eligible_count - rank_1m)::numeric / nullif(eligible_count - 1, 0))::integer + 1)) ELSE 0 END,
    CASE WHEN score IS NOT NULL THEN least(99, greatest(1, round(98 * (eligible_count - rank_3m)::numeric / nullif(eligible_count - 1, 0))::integer + 1)) ELSE 0 END,
    CASE WHEN score IS NOT NULL THEN least(99, greatest(1, round(98 * (eligible_count - rank_6m)::numeric / nullif(eligible_count - 1, 0))::integer + 1)) ELSE 0 END,
    CASE WHEN score IS NOT NULL THEN least(99, greatest(1, round(98 * (eligible_count - rank_12m)::numeric / nullif(eligible_count - 1, 0))::integer + 1)) ELSE 0 END,
    CASE WHEN score IS NOT NULL AND eligible_count = 1 THEN 99
         WHEN score IS NOT NULL THEN least(99, greatest(1, round(98 * (eligible_count - overall_rank)::numeric / (eligible_count - 1))::integer + 1)) END,
    CASE WHEN score IS NOT NULL THEN overall_rank END,
    CASE WHEN score IS NOT NULL THEN overall_rank END,
    :input_hash
FROM ranked
"""


def _unavailable(run, dataset, target, rows, reason):
    return BacktestDatasetRs(backtest_dataset_id=dataset.id, instrument_id=target.instrument_id, code=(rows[-1].code if rows else str(target.instrument_id)), market=target.market, trade_date=target.trade_date, status="unavailable", reason_code=reason, required_observations=MIN_REQUIRED_PRICES, available_observations=len(rows), available_at=None, input_hash=_hash([_price_material(row) for row in rows]))


def _price_material(row): return [row.instrument_id, row.trade_date.isoformat(), str(row.close)]
def _rs_material(row): return [row.instrument_id, row.trade_date.isoformat(), row.status, row.reason_code, str(row.return_12m), row.rs_rating, row.input_hash]
def _hash(value): return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
