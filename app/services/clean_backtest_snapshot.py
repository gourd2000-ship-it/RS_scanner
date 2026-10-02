"""감사와 동일한 가격 선택 정책으로 불변 OHLCV 데이터셋을 만든다."""

from collections import Counter
from dataclasses import replace
from hashlib import sha256
from itertools import groupby
import json

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.models.backtest_dataset import BacktestDataset, BacktestDatasetMembership, BacktestDatasetPrice
from app.models.data_quality import CorporateAction
from app.models.instrument import Instrument
from app.repositories.listing_history_repository import ListingHistoryRepository
from app.services.validation.cleansing_policy import CleansingSelection, select_cleansing_universe
from app.services.validation.historical_clean_reader import CleanPriceDecision, select_clean_day_decisions
from app.services.validation.ohlcv_audit import QUALITY_RULE_VERSION, classify_transition


def create_clean_backtest_dataset(
    session: Session,
    *,
    selection: CleansingSelection,
    adjustment_policy: str,
) -> BacktestDataset:
    """한 읽기 snapshot에서 입력 hash를 확인하고 검증된 가격만 복사한다."""
    provider, separator, adjustment_type = adjustment_policy.partition(":")
    if not separator or not provider or not adjustment_type:
        raise ValueError("adjustment_policy must be provider:adjustment_type")
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        if session.connection().get_isolation_level().upper() != "REPEATABLE READ":
            raise ValueError("PostgreSQL clean dataset requires REPEATABLE READ")

    selected = select_cleansing_universe(session, selection)
    instruments = {row.id: row for row in session.scalars(select(Instrument).order_by(Instrument.id))}
    instrument_ids = sorted({entry.instrument_id for entry in selected.universe.entries})
    listing_rows = ListingHistoryRepository(session).list_current_for_instruments(
        instrument_ids, as_known_at=selection.observation_cutoff
    )
    revisions: dict[int, list[str]] = {}
    for row in listing_rows:
        revisions.setdefault(row.instrument_id, []).append(row.content_hash)

    selected_rows = list(_selected_rows(session, selected, provider, adjustment_type))
    counts: Counter[str] = Counter(decision.status for _, decision in selected_rows)
    expected_by_segment: dict[tuple[int, int], list[CleanPriceDecision]] = {}
    for entry, decision in selected_rows:
        if entry.price_expectation == "expected":
            expected_by_segment.setdefault((entry.instrument_id, entry.trade_date.year), []).append(decision)
    complete_segments = {
        segment
        for segment, decisions in expected_by_segment.items()
        if decisions and all(decision.status == "valid" and decision.values is not None for decision in decisions)
    }
    published_rows = [
        (entry, decision)
        for entry, decision in selected_rows
        if entry.price_expectation == "expected"
        and (entry.instrument_id, entry.trade_date.year) in complete_segments
    ]

    digest = sha256()
    for entry, decision in published_rows:
        counts[decision.status] += 1
        material = _row_material(entry, decision, instruments[entry.instrument_id])
        digest.update(json.dumps(material, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), default=str).encode())
        digest.update(b"\n")

    manifest = {
        "version": "ohlcv-cleansed-v1",
        "range": {"start": selection.start.isoformat(), "end": selection.end.isoformat()},
        "selection_as_of": selection.selection_as_of.isoformat(),
        "observation_cutoff": selection.observation_cutoff.isoformat(),
        "markets": list(selection.markets), "security_type": "stock",
        "exclude_delisted": selection.exclude_delisted,
        "excluded_delisted_ids": list(selected.excluded_delisted_ids),
        "unknown_instrument_ids": list(selected.unknown_instrument_ids),
        "adjustment_policy": adjustment_policy,
        "quality_policy": QUALITY_RULE_VERSION,
        "publication_scope": "complete_segments_only",
        "complete_segments": [
            {"instrument_id": instrument_id, "year": year}
            for instrument_id, year in sorted(complete_segments)
        ],
        "membership_revisions": {str(key): sorted(value) for key, value in sorted(revisions.items())},
        "audited_coverage": dict(sorted(counts.items())),
        "coverage": {"valid": len(published_rows), "complete_segments": len(complete_segments)},
        "input_hash": digest.hexdigest(),
    }
    manifest_hash = _hash(manifest)
    existing = session.scalar(select(BacktestDataset).where(BacktestDataset.manifest_hash == manifest_hash))
    if existing is not None:
        return existing

    dataset = BacktestDataset(
        dataset_id=f"clean-{manifest_hash[:24]}", manifest_hash=manifest_hash,
        final_manifest_hash=manifest_hash, range_start=selection.start, range_end=selection.end,
        markets=list(selection.markets), reconstruction_mode="historical_reconstructed",
        as_known_at=None, adjustment_policy=adjustment_policy, policy_version=QUALITY_RULE_VERSION,
        preparation_start=None, manifest=manifest,
    )
    session.add(dataset)
    session.flush()
    memberships: list[dict] = []
    prices: list[dict] = []
    for entry, decision in published_rows:
        instrument = instruments[entry.instrument_id]
        memberships.append({
            "backtest_dataset_id": dataset.id,
            "instrument_id": entry.instrument_id,
            "trade_date": entry.trade_date,
            "market": entry.market,
            "security_type": entry.security_type,
            "membership_evidence_state": entry.membership_evidence_state,
            "trading_status": entry.trading_status,
            "price_expectation": entry.price_expectation,
            "event_revision_hashes": revisions.get(entry.instrument_id, []),
            "code": instrument.krx_short_code, "name": instrument.name,
            "quality_status": decision.status, "quality_reason": decision.reason,
            "quality_evidence": {
                "source_observation_id": decision.source_observation_id,
                "source_payload_hash": decision.source_payload_hash,
                "correction_ids": decision.correction_ids,
            },
        })
        if decision.status == "valid" and decision.values is not None:
            prices.append({
                "backtest_dataset_id": dataset.id,
                "instrument_id": entry.instrument_id,
                "source_symbol_id": decision.source_symbol_id,
                "source_observation_id": decision.source_observation_id,
                "code": instrument.krx_short_code, "name": instrument.name,
                "market": entry.market, "trade_date": entry.trade_date,
                **decision.values,
                "provider": provider, "adjustment_type": adjustment_type,
                "source_payload_hash": decision.source_payload_hash,
                "correction_ids": list(decision.correction_ids),
            })
        if len(memberships) >= 10_000:
            session.execute(insert(BacktestDatasetMembership), memberships)
            memberships.clear()
        if len(prices) >= 10_000:
            session.execute(insert(BacktestDatasetPrice), prices)
            prices.clear()
    if memberships:
        session.execute(insert(BacktestDatasetMembership), memberships)
    if prices:
        session.execute(insert(BacktestDatasetPrice), prices)
    session.flush()
    return dataset


def _selected_rows(session: Session, selected, provider: str, adjustment_type: str):
    last_close: dict[int, tuple[int, object]] = {}
    for day_index, (day, entries) in enumerate(groupby(selected.universe.entries, key=lambda entry: entry.trade_date)):
        action_symbols = {row.symbol_id for row in session.scalars(select(CorporateAction).where(
            CorporateAction.event_date == day
        ))}
        decisions = select_clean_day_decisions(
            session, trade_date=day, provider=provider, adjustment_type=adjustment_type,
            observation_cutoff=selected.selection.observation_cutoff,
        )
        for entry in entries:
            if entry.price_expectation != "expected":
                decision = CleanPriceDecision("non_tradable", "confirmed_trading_halt", None,
                                              None, None, None, ())
            else:
                decision = decisions.get(entry.instrument_id) or CleanPriceDecision(
                    "missing", "selected_source_missing", None, None, None, None, ()
                )
            if decision.status == "valid" and decision.values is not None:
                previous = last_close.get(entry.instrument_id)
                if previous is not None:
                    reason = classify_transition(
                        previous[1], decision.values["close"],
                        corporate_action=decision.source_symbol_id in action_symbols,
                        consecutive=previous[0] == day_index - 1,
                    )
                    if reason is not None:
                        decision = replace(decision, status="review_required", reason=reason, values=None)
                if decision.status == "valid":
                    last_close[entry.instrument_id] = (day_index, decision.values["close"])
            if decision.status != "valid":
                last_close.pop(entry.instrument_id, None)
            yield entry, decision


def _row_material(entry, decision, instrument: Instrument) -> list:
    return [
        entry.instrument_id, instrument.krx_short_code, instrument.name,
        entry.trade_date.isoformat(), entry.market, entry.trading_status,
        entry.price_expectation, decision.status, decision.reason,
        decision.source_symbol_id, decision.source_observation_id,
        decision.source_payload_hash, decision.correction_ids,
        decision.values,
    ]


def _hash(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), default=str).encode()).hexdigest()
