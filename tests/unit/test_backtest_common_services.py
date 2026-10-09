from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.models  # noqa: F401
from app.core.base import Base
from app.core.database import get_db_session
from app.models.backtest_dataset import (
    BacktestDataset,
    BacktestDatasetIndicatorSnapshot,
    BacktestDatasetIndicatorSnapshotRow,
    BacktestDatasetIndicatorSnapshotSource,
    BacktestDatasetMembership,
    BacktestDatasetPrice,
    BacktestDatasetRs,
    BacktestDatasetRsRun,
)
from app.models.backtest_run import BacktestStrategyVersion
from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorGeneration,
    IndicatorInputPolicy,
    IndicatorSeries,
)
from app.models.benchmark import Benchmark
from app.models.benchmark_daily_price import BenchmarkDailyPrice
from app.repositories.backtest_repository import BacktestRepository
from app.services.backtest.auth import BacktestOperatorAuthService, InvalidCsrfToken
from app.services.backtest.input_selection import BacktestInputUnavailable, select_backtest_inputs
from app.services.backtest.execution import BacktestExecutionService
from app.services.backtest.run_preparation import BacktestRunPreparationService
from app.api.v1.endpoints import backtest_auth
from app.api.v1.endpoints.backtest_execution import _run as serialize_run


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _complete_inputs(session: Session) -> tuple[BacktestDataset, BacktestDatasetRsRun]:
    manifest = {"publication_scope": "complete_segments_only"}
    dataset = BacktestDataset(
        dataset_id="complete-latest", manifest_hash="a" * 64, final_manifest_hash=_hash(manifest),
        range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI", "KOSDAQ"], reconstruction_mode="historical_reconstructed",
        adjustment_policy="fixture:1", policy_version="v1", manifest=manifest, status="active",
    )
    session.add(dataset)
    session.flush()
    for market, instrument, code in (("KOSPI", 1, "000001"), ("KOSDAQ", 2, "000002")):
        for offset, trade_date in enumerate((date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5))):
            dataset.memberships.append(BacktestDatasetMembership(
                instrument_id=instrument, trade_date=trade_date, market=market, security_type="stock",
                membership_evidence_state="observed", trading_status="trading", price_expectation="expected",
                event_revision_hashes=[], code=code, name=code, quality_status="complete",
            ))
            dataset.prices.append(BacktestDatasetPrice(
                instrument_id=instrument, source_symbol_id=instrument, code=code, name=code, market=market,
                trade_date=trade_date, open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
                close=Decimal(str(100 + offset)), volume=100, change_rate=Decimal("0"), provider="fixture",
            ))
    run = BacktestDatasetRsRun(
        backtest_dataset_id=dataset.id, formula_version="rs-v1", policy_version="v1", input_hash="b" * 64,
        result_hash="c" * 64, status="completed", created_at=datetime(2024, 1, 10, tzinfo=timezone.utc), manifest={},
    )
    session.add(run)
    session.flush()
    for membership in dataset.memberships:
        session.add(BacktestDatasetRs(
            backtest_dataset_rs_run_id=run.id, backtest_dataset_id=dataset.id, instrument_id=membership.instrument_id,
            code=membership.code or "", market=membership.market, trade_date=membership.trade_date,
            status="available", required_observations=1, available_observations=1,
            rs_rating=90, rank_in_market=1, input_hash="d" * 64,
        ))
    for market in ("KOSPI", "KOSDAQ"):
        benchmark = Benchmark(benchmark_code=market, name=market, market=market)
        session.add(benchmark)
        session.flush()
        for offset, trade_date in enumerate((date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5))):
            session.add(BenchmarkDailyPrice(
                benchmark_id=benchmark.id, trade_date=trade_date, open=Decimal("100"), high=Decimal("101"),
                low=Decimal("99"), close=Decimal(str(100 + offset)), volume=None, change_rate=Decimal("0"),
            ))
    session.commit()
    return dataset, run


def _indicator_config(
    *, buy_field: str = "volume_sma50", sell_field: str = "rs_rating", rebalance_interval_days: int = 1,
) -> dict:
    return {
        "markets": ["KOSPI"], "rebalance_interval_days": rebalance_interval_days, "max_holdings": 1,
        "max_position_weight": "1", "cash_reserve_ratio": "0", "buy_fee_rate": "0",
        "sell_fee_rate": "0", "buy_slippage_rate": "0", "sell_slippage_rate": "0",
        "buy_conditions": {"type": "rule", "field": buy_field, "operator": "gte", "value": "1"},
        "sell_conditions": {"type": "rule", "field": sell_field, "operator": "lt", "value": "50"},
    }


def _attach_indicator_snapshot(
    session: Session,
    dataset: BacktestDataset,
    *,
    kind: str = "volume_sma",
    missing_date: date | None = None,
    unavailable: tuple[date, str, str] | None = None,
    wrong_manifest_hash: bool = False,
    wrong_source_provider: bool = False,
) -> BacktestDatasetIndicatorSnapshot:
    fingerprint = "c" * 64
    policy = IndicatorInputPolicy(
        provider="fixture", adjustment_type="1", allowed_parser_versions=["fixture-v1"],
        observation_cutoff=datetime(2024, 1, 10), selector_version="selector-v1",
        validation_version="validation-v1", correction_version="correction-v1", fingerprint=fingerprint,
    )
    session.add(policy)
    session.flush()
    period, formula, input_field = (50, "volume-sma-v1", "volume") if kind == "volume_sma" else (14, "wilder-atr-14-v1", "high-low-close")
    instruments = sorted({price.instrument_id for price in dataset.prices})
    source_models = []
    for instrument_id in instruments:
        series = IndicatorSeries(
            instrument_id=instrument_id, indicator_kind=kind, input_field=input_field, periods=str(period),
            input_policy_version="validated-observation-ohlcv-v1", formula_version=formula,
            source_provider="wrong-provider" if wrong_source_provider else "fixture",
            adjustment_policy="1", allowed_parser_versions=["fixture-v1"],
            observation_cutoff=datetime(2024, 1, 10), input_policy_id=policy.id,
        )
        session.add(series)
        session.flush()
        generation = IndicatorGeneration(series_id=series.id, generation=1, status="current")
        session.add(generation)
        session.flush()
        run = IndicatorCalculationRun(
            generation_id=generation.id, series_id=series.id, run_kind="backfill", status="completed",
            input_cutoff=datetime(2024, 1, 10), range_start=dataset.range_start, range_end=dataset.range_end,
            input_hash="b" * 64, result_hash="d" * 64, input_count=4, result_count=4,
            completed_at=datetime(2024, 1, 10),
        )
        session.add(run)
        session.flush()
        source_models.append(BacktestDatasetIndicatorSnapshotSource(
            snapshot_id=0, instrument_id=instrument_id, indicator_series_id=series.id,
            generation_id=generation.id, calculation_run_id=run.id, input_policy_id=policy.id,
            source_policy_fingerprint=fingerprint, input_hash=run.input_hash, result_hash=run.result_hash,
        ))

    prices = list(session.scalars(select(BacktestDatasetPrice).where(
        BacktestDatasetPrice.backtest_dataset_id == dataset.id,
    )))
    snapshot = BacktestDatasetIndicatorSnapshot(
        snapshot_key=("a" if kind == "volume_sma" else "b") * 64,
        backtest_dataset_id=dataset.id, dataset_id=dataset.dataset_id,
        dataset_manifest_hash=("f" * 64 if wrong_manifest_hash else dataset.final_manifest_hash),
        indicator_kind=kind, period=period, formula_version=formula,
        source_policy_fingerprint=fingerprint, range_start=dataset.range_start, range_end=dataset.range_end,
        source_count=len(instruments),
        row_count=len(prices) - sum(price.trade_date == missing_date for price in prices),
        input_hash="1" * 64,
        result_hash="2" * 64, content_hash="3" * 64, status="complete",
        completed_at=datetime(2024, 1, 10),
    )
    session.add(snapshot)
    session.flush()
    source_id_by_instrument = {}
    for source in source_models:
        source.snapshot_id = snapshot.id
        session.add(source)
        session.flush()
        source_id_by_instrument[source.instrument_id] = source.id

    for index, price in enumerate(prices, start=1):
        if price.trade_date == missing_date:
            continue
        unavailable_state = unavailable if unavailable and unavailable[0] == price.trade_date else None
        row_status = unavailable_state[1] if unavailable_state else "available"
        reason_code = unavailable_state[2] if unavailable_state else None
        session.add(BacktestDatasetIndicatorSnapshotRow(
            snapshot_id=snapshot.id, source_id=source_id_by_instrument[price.instrument_id],
            instrument_id=price.instrument_id, trade_date=price.trade_date,
            source_value_id=index, source_run_input_id=index, source_evidence_id=index,
            value=(Decimal("120") if kind == "volume_sma" else Decimal("2")) if row_status == "available" else None,
            status=row_status, reason_code=reason_code,
            available_observations=period if row_status == "available" else (period - 1 if row_status == "warming_up" else 0),
            input_prefix_hash="4" * 64, source_evidence_key="5" * 64,
            source_symbol_id=price.source_symbol_id, price_observation_id=index,
            identity_snapshot_id=index, provider_symbol_mapping_id=index,
            mapping_status="matched", mapping_valid_from=date(2000, 1, 1), mapping_valid_to=None,
            resolver_version="resolver-v1", resolved_at=datetime(2024, 1, 10),
            provider="fixture", provider_symbol=price.code, adjustment_type="1", parser_version="fixture-v1",
            observed_at=datetime(2024, 1, 10), payload_hash="6" * 64,
            open=price.open, high=max(price.high, price.open, price.close),
            low=min(price.low, price.open, price.close), close=price.close, volume=price.volume,
            correction_ids=[], validation_evidence=[], row_hash="7" * 64,
        ))
    session.flush()
    return snapshot


def test_input_selection_pins_latest_complete_dataset_rs_and_benchmark_closes():
    session = _session()
    dataset, rs_run = _complete_inputs(session)

    selected = select_backtest_inputs(
        session, range_start=date(2024, 1, 3), range_end=date(2024, 1, 5), markets=["KOSPI"],
        rebalance_dates=[date(2024, 1, 3), date(2024, 1, 5)],
    )

    assert selected.dataset.id == dataset.id
    assert selected.dataset_manifest_hash == dataset.final_manifest_hash
    assert selected.rs_run.id == rs_run.id
    assert selected.rs_run.formula_version == "rs-v1"
    assert {item.market for item in selected.benchmark_snapshots} == {"KOSPI", "KOSDAQ"}
    assert all(len(item.snapshot_hash) == 64 for item in selected.benchmark_snapshots)


def test_indicator_condition_preparation_pins_snapshot_and_preserves_dataset_rs_lineage():
    session = _session()
    dataset, rs_run = _complete_inputs(session)
    snapshot = _attach_indicator_snapshot(session, dataset)
    strategy = BacktestRepository(session).create_strategy(name="MA50 조건", config=_indicator_config())

    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )

    assert run.status == "queued"
    assert run.backtest_dataset_id == dataset.id
    assert run.backtest_dataset_rs_run_id == rs_run.id
    assert run.rs_result_hash == rs_run.result_hash
    assert run.volume_sma50_snapshot_id == snapshot.id
    assert run.volume_sma50_snapshot_hash == snapshot.content_hash
    assert run.atr14_snapshot_id is None


def test_indicator_execution_reads_only_the_run_pinned_decimal_snapshot():
    session = _session()
    dataset, _ = _complete_inputs(session)
    snapshot = _attach_indicator_snapshot(session, dataset)
    strategy = BacktestRepository(session).create_strategy(name="MA50 실행", config=_indicator_config())
    prepared = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )
    claimed = BacktestRepository(session).claim_next_run()
    assert claimed is not None and claimed.volume_sma50_snapshot_id == snapshot.id

    result = BacktestExecutionService(session).execute(claimed)

    assert prepared.status == "completed"
    assert result.orders[0].side == "buy"
    assert result.orders[0].signal_date == date(2024, 1, 2)
    assert result.orders[0].execution_date == date(2024, 1, 3)
    serialized = serialize_run(prepared)
    assert serialized.volume_sma50_snapshot_id == snapshot.id
    assert serialized.volume_sma50_snapshot_hash == snapshot.content_hash


def test_indicator_preparation_checks_actual_first_rebalance_date_before_queue():
    session = _session()
    dataset, rs_run = _complete_inputs(session)
    # The worker's schedule starts on Jan 2 and then every other dataset trade
    # day.  Jan 3 here deliberately differs from the request's supplied date.
    _attach_indicator_snapshot(session, dataset, missing_date=date(2024, 1, 2))
    strategy = BacktestRepository(session).create_strategy(
        name="첫 매수일 누락 지표", config=_indicator_config(rebalance_interval_days=2),
    )

    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )

    reason = next(item for item in json.loads(run.error_detail) if item["code"] == "indicator_value_missing")
    assert run.status == "data_unavailable"
    assert run.backtest_dataset_id == dataset.id
    assert run.backtest_dataset_rs_run_id == rs_run.id
    assert reason["indicator_kind"] == "volume_sma"
    assert reason["instrument_id"] == 1
    assert reason["trade_date"] == "2024-01-02"


def test_indicator_preparation_keeps_original_unavailable_status_and_reason():
    session = _session()
    dataset, _ = _complete_inputs(session)
    _attach_indicator_snapshot(
        session, dataset, unavailable=(date(2024, 1, 3), "warming_up", "warming_up"),
    )
    strategy = BacktestRepository(session).create_strategy(name="워밍업 지표", config=_indicator_config())

    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )

    reasons = json.loads(run.error_detail)
    reason = next(item for item in reasons if item["code"] == "indicator_value_unavailable")
    assert run.status == "data_unavailable"
    assert reason["original_status"] == "warming_up"
    assert reason["original_reason_code"] == "warming_up"
    assert run.backtest_dataset_id is not None


def test_indicator_preparation_checks_sell_conditions_each_market_day():
    session = _session()
    dataset, _ = _complete_inputs(session)
    _attach_indicator_snapshot(session, dataset, kind="atr", missing_date=date(2024, 1, 4))
    strategy = BacktestRepository(session).create_strategy(
        name="ATR 매도 조건", config=_indicator_config(buy_field="rs_rating", sell_field="atr14"),
    )

    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )

    reason = json.loads(run.error_detail)[0]
    assert run.status == "data_unavailable"
    assert reason["code"] == "indicator_value_missing"
    assert reason["field"] == "atr14"
    assert reason["trade_date"] == "2024-01-04"


def test_indicator_preparation_rejects_snapshot_from_a_different_dataset_manifest():
    session = _session()
    dataset, _ = _complete_inputs(session)
    _attach_indicator_snapshot(session, dataset, wrong_manifest_hash=True)
    strategy = BacktestRepository(session).create_strategy(name="잘못된 snapshot", config=_indicator_config())

    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )

    assert run.status == "data_unavailable"
    assert json.loads(run.error_detail)[0]["code"] == "indicator_evidence_mismatch"


def test_indicator_preparation_reports_missing_bundle_without_queuing():
    session = _session()
    dataset, rs_run = _complete_inputs(session)
    strategy = BacktestRepository(session).create_strategy(name="묶음 없음", config=_indicator_config())

    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )

    reason = json.loads(run.error_detail)[0]
    assert run.status == "data_unavailable"
    assert run.backtest_dataset_id == dataset.id
    assert run.backtest_dataset_rs_run_id == rs_run.id
    assert reason["code"] == "indicator_snapshot_missing"
    assert reason["indicator_kind"] == "volume_sma"


def test_indicator_preparation_rejects_snapshot_source_policy_mismatch():
    session = _session()
    dataset, _ = _complete_inputs(session)
    _attach_indicator_snapshot(session, dataset, wrong_source_provider=True)
    strategy = BacktestRepository(session).create_strategy(name="source 불일치", config=_indicator_config())

    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )

    assert run.status == "data_unavailable"
    assert json.loads(run.error_detail)[0]["code"] == "indicator_evidence_mismatch"


def test_input_selection_rejects_missing_benchmark_or_required_rs():
    session = _session()
    _complete_inputs(session)
    benchmark = session.query(Benchmark).filter_by(benchmark_code="KOSDAQ").one()
    session.query(BenchmarkDailyPrice).filter_by(benchmark_id=benchmark.id, trade_date=date(2024, 1, 4)).delete()
    session.commit()

    with pytest.raises(BacktestInputUnavailable) as unavailable:
        select_backtest_inputs(
            session, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5), markets=["KOSPI"],
            rebalance_dates=[date(2024, 1, 3)],
        )
    assert any(reason.code == "benchmark_price_missing" for reason in unavailable.value.reasons)


def test_input_selection_does_not_accept_another_market_price_or_rs_for_membership():
    session = _session()
    dataset, rs_run = _complete_inputs(session)
    kospi_membership = next(item for item in dataset.memberships if item.market == "KOSPI" and item.trade_date == date(2024, 1, 3))
    wrong_market_price = session.query(BacktestDatasetPrice).filter_by(
        backtest_dataset_id=dataset.id, instrument_id=kospi_membership.instrument_id,
        trade_date=kospi_membership.trade_date,
    ).one()
    wrong_market_price.market = "KOSDAQ"
    session.commit()
    with pytest.raises(BacktestInputUnavailable) as unavailable:
        select_backtest_inputs(
            session, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5), markets=["KOSPI"],
            rebalance_dates=[date(2024, 1, 3)],
        )
    assert any(reason.code == "ohlcv_missing" for reason in unavailable.value.reasons)

    wrong_market_price.market = "KOSPI"
    wrong_market_rs = session.query(BacktestDatasetRs).filter_by(
        backtest_dataset_rs_run_id=rs_run.id, instrument_id=kospi_membership.instrument_id,
        trade_date=kospi_membership.trade_date,
    ).one()
    wrong_market_rs.market = "KOSDAQ"
    session.commit()
    with pytest.raises(BacktestInputUnavailable) as unavailable:
        select_backtest_inputs(
            session, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5), markets=["KOSPI"],
            rebalance_dates=[date(2024, 1, 3)],
        )
    assert any(reason.code == "rs_value_missing" for reason in unavailable.value.reasons)


def test_input_selection_honors_configured_exchange_closure_for_benchmark_coverage():
    session = _session()
    _complete_inputs(session)
    for benchmark in session.query(Benchmark).all():
        session.query(BenchmarkDailyPrice).filter_by(benchmark_id=benchmark.id, trade_date=date(2024, 1, 4)).delete()
    session.commit()
    selected = select_backtest_inputs(
        session, range_start=date(2024, 1, 3), range_end=date(2024, 1, 5), markets=["KOSPI"],
        rebalance_dates=[date(2024, 1, 3)], market_closed_dates="2024-01-04",
    )
    assert len(selected.benchmark_snapshots) == 2


def test_return_lookback_excludes_candidate_even_when_its_rs_row_is_available():
    session = _session()
    dataset, _ = _complete_inputs(session)
    membership = next(item for item in dataset.memberships if item.market == "KOSPI" and item.trade_date == date(2024, 1, 3))
    session.query(BacktestDatasetPrice).filter_by(
        backtest_dataset_id=dataset.id, instrument_id=membership.instrument_id,
        market="KOSPI", trade_date=date(2024, 1, 2),
    ).delete()
    session.commit()
    selected = select_backtest_inputs(
        session, range_start=date(2024, 1, 3), range_end=date(2024, 1, 5), markets=["KOSPI"],
        rebalance_dates=[date(2024, 1, 3)], return_lookback_days=1,
    )
    assert (membership.instrument_id, "KOSPI", date(2024, 1, 3)) in selected.lookback_excluded_candidates

    strategy = BacktestRepository(session).create_strategy(name="룩백 제외", config={})
    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 3), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)], return_lookback_days=1,
    )
    assert run.candidate_exclusions == [{
        "instrument_id": membership.instrument_id, "market": "KOSPI", "trade_date": "2024-01-03",
        "reason": "insufficient_return_lookback",
    }]


def test_data_unavailable_attempt_keeps_an_auditable_run_without_invented_dataset_lineage():
    session = _session()
    repository = BacktestRepository(session)
    strategy = repository.create_strategy(name="입력 부족", config={})
    run = repository.record_data_unavailable_run(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], reasons=[{"code": "dataset_missing", "detail": "no verified dataset"}],
    )
    assert run.status == "data_unavailable"
    assert run.dataset_id is None
    assert "dataset_missing" in (run.error_detail or "")


def test_preparation_persists_missing_inputs_as_data_unavailable_run():
    session = _session()
    strategy = BacktestRepository(session).create_strategy(name="입력 부족", config={})
    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )
    assert run.status == "data_unavailable"
    assert "dataset_missing" in (run.error_detail or "")


def test_preparation_pins_the_selected_rs_formula_version_on_queued_run():
    session = _session()
    _, rs_run = _complete_inputs(session)
    strategy = BacktestRepository(session).create_strategy(name="고정 입력", config={})
    run = BacktestRunPreparationService(session).prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )
    assert run.status == "queued"
    assert run.rs_formula_version == rs_run.formula_version


def test_queue_never_claims_a_second_run_while_one_is_running():
    session = _session()
    _complete_inputs(session)
    strategy = BacktestRepository(session).create_strategy(name="대기열", config={})
    service = BacktestRunPreparationService(session)
    first = service.prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )
    second = service.prepare(
        strategy_version_id=strategy.versions[0].id, range_start=date(2024, 1, 2), range_end=date(2024, 1, 5),
        markets=["KOSPI"], rebalance_dates=[date(2024, 1, 3)],
    )
    repository = BacktestRepository(session)
    assert repository.claim_next_run().run_id == first.run_id
    assert repository.claim_next_run() is None
    assert repository.get_run(second.run_id).status == "queued"


def test_operator_auth_uses_hashed_sessions_rotated_csrf_and_lockout():
    session = _session()
    service = BacktestOperatorAuthService(session, password="operator-secret")
    preauth_token, csrf = service.issue_pre_auth(request_subject="127.0.0.1")
    with pytest.raises(InvalidCsrfToken):
        service.login(preauth_token=preauth_token, csrf_token="wrong", password="operator-secret", request_subject="127.0.0.1")
    for _ in range(4):
        with pytest.raises(PermissionError):
            service.login(preauth_token=preauth_token, csrf_token=csrf, password="wrong", request_subject="127.0.0.1")
    with pytest.raises(TimeoutError):
        service.login(preauth_token=preauth_token, csrf_token=csrf, password="wrong", request_subject="127.0.0.1")

    session2 = _session()
    service2 = BacktestOperatorAuthService(session2, password="operator-secret")
    preauth_token, csrf = service2.issue_pre_auth(request_subject="127.0.0.2")
    operator_token, operator_csrf = service2.login(
        preauth_token=preauth_token, csrf_token=csrf, password="operator-secret", request_subject="127.0.0.2"
    )
    assert operator_token != preauth_token
    assert operator_csrf != csrf
    assert service2.require_operator(operator_token, operator_csrf) is not None
    service2.logout(operator_token, operator_csrf)
    assert service2.find_operator(operator_token) is None


def test_operator_session_expiry_is_always_eight_hours():
    session = _session()
    service = BacktestOperatorAuthService(session, password="operator-secret")
    now = datetime(2026, 1, 2, 9, tzinfo=timezone.utc)
    preauth_token, csrf = service.issue_pre_auth(request_subject="127.0.0.3", now=now)
    operator_token, _ = service.login(
        preauth_token=preauth_token, csrf_token=csrf, password="operator-secret",
        request_subject="127.0.0.3", now=now,
    )
    operator = service.find_operator(operator_token, now=now)
    assert operator.expires_at == (now + timedelta(hours=8)).replace(tzinfo=None)


def test_operator_lockout_is_fixed_at_five_failures_for_fifteen_minutes():
    session = _session()
    service = BacktestOperatorAuthService(session, password="operator-secret")
    now = datetime(2026, 1, 2, 9, tzinfo=timezone.utc)
    preauth_token, csrf = service.issue_pre_auth(request_subject="127.0.0.4", now=now)
    for _ in range(4):
        with pytest.raises(PermissionError):
            service.login(preauth_token=preauth_token, csrf_token=csrf, password="wrong", request_subject="127.0.0.4", now=now)
    with pytest.raises(TimeoutError):
        service.login(preauth_token=preauth_token, csrf_token=csrf, password="wrong", request_subject="127.0.0.4", now=now)
    assert service.repository.is_login_locked(subject_hash=service.subject_hash("127.0.0.4"), now=now + timedelta(minutes=14))
    assert not service.repository.is_login_locked(subject_hash=service.subject_hash("127.0.0.4"), now=now + timedelta(minutes=15))


def test_backtest_auth_router_requires_preauth_csrf_then_rotates_the_cookie_session(monkeypatch):
    session = _session()
    app = FastAPI()
    app.include_router(backtest_auth.router, prefix="/api/v1/backtests")

    def database_override():
        yield session

    app.dependency_overrides[get_db_session] = database_override
    monkeypatch.setattr(
        backtest_auth, "get_settings",
        lambda: type("Settings", (), {
            "backtest_operator_password": "operator-secret",
        })(),
    )
    with TestClient(app, base_url="https://testserver") as client:
        csrf_response = client.get("/api/v1/backtests/auth/csrf")
        assert csrf_response.status_code == 200
        csrf_token = csrf_response.json()["csrf_token"]
        assert "HttpOnly" in csrf_response.headers["set-cookie"]
        assert "Secure" in csrf_response.headers["set-cookie"]
        bad_login = client.post("/api/v1/backtests/auth/login", json={"password": "operator-secret"})
        assert bad_login.status_code == 403
        login_response = client.post(
            "/api/v1/backtests/auth/login", json={"password": "operator-secret"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert login_response.status_code == 200
        operator_csrf = login_response.json()["csrf_token"]
        assert operator_csrf != csrf_token
        logout_response = client.post("/api/v1/backtests/auth/logout", headers={"X-CSRF-Token": operator_csrf})
        assert logout_response.status_code == 200
