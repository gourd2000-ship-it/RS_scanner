"""Planning primitives for a resumable historical price backfill."""

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from typing import Any, Callable, Iterable

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.crawler.sources.kiwoom_history import KiwoomHistoryPage
from app.models.historical_backfill_run import HistoricalBackfillTargetState
from app.models.instrument import ProviderSymbol
from app.models.symbol import Symbol
from app.services.historical_universe import HistoricalUniverseManifest
from app.repositories.historical_backfill_repository import HistoricalBackfillRepository
from app.repositories.price_repository import HistoricalPriceSaveResult, PriceRepository


@dataclass(frozen=True)
class HistoricalBackfillTarget:
    instrument_id: int
    provider_code: str
    symbol_id: int | None
    market: str
    expected_dates: tuple[date, ...]

    def serialized(self) -> dict:
        return {
            "instrument_id": self.instrument_id,
            "provider_code": self.provider_code,
            "symbol_id": self.symbol_id,
            "market": self.market,
            "expected_dates": [value.isoformat() for value in self.expected_dates],
        }


@dataclass(frozen=True)
class HistoricalBackfillPlan:
    start: date
    end: date
    provider: str
    adjustment_type: str
    base_date: str
    request_budget: int
    targets: tuple[HistoricalBackfillTarget, ...]
    dry_run: bool = False

    def serialized(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "provider": self.provider,
            "adjustment_type": self.adjustment_type,
            "base_date": self.base_date,
            "request_budget": self.request_budget,
            "dry_run": self.dry_run,
            "targets": [target.serialized() for target in sorted(self.targets, key=lambda item: item.instrument_id)],
        }

    @property
    def manifest_hash(self) -> str:
        return sha256(json.dumps(self.serialized(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass
class HistoricalBackfillReport:
    run_id: str
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    conflict: int = 0
    failed: int = 0
    unsupported: int = 0
    completed_targets: int = 0
    dry_run: bool = False
    requests_used: int = 0
    budget_exhausted_targets: int = 0
    target_count: int = 0
    expected_rows: int = 0
    unresolved_targets: int = 0


PageFactory = Callable[[HistoricalBackfillTargetState, int], Iterable[KiwoomHistoryPage]]


def plan_from_manifest(
    session: Session,
    manifest: HistoricalUniverseManifest,
    *,
    provider: str,
    adjustment_type: str,
    base_date: str,
    request_budget: int,
    dry_run: bool = False,
) -> HistoricalBackfillPlan:
    """Resolve dated provider and legacy symbol identities before collection.

    A target whose provider mapping or legacy price owner is ambiguous is
    retained with an empty provider code so the run reports it as failed rather
    than writing a reused short code to the wrong symbol.
    """
    dates_by_instrument: dict[tuple[int, str], list[date]] = {}
    for entry in manifest.entries:
        if entry.price_expectation == "expected":
            dates_by_instrument.setdefault((entry.instrument_id, entry.market), []).append(entry.trade_date)
    targets: list[HistoricalBackfillTarget] = []
    for (instrument_id, market), dates in sorted(dates_by_instrument.items()):
        mappings = list(session.scalars(select(ProviderSymbol).where(
            ProviderSymbol.instrument_id == instrument_id,
            ProviderSymbol.provider == provider,
            ProviderSymbol.mapping_status == "matched",
        )))
        codes = {
            mapping.provider_symbol
            for mapping in mappings
            if all(_mapping_covers(mapping, trade_date) for trade_date in dates)
        }
        symbols = list(session.scalars(select(Symbol).where(Symbol.instrument_id == instrument_id)))
        targets.append(HistoricalBackfillTarget(
            instrument_id=instrument_id,
            provider_code=next(iter(codes)) if len(codes) == 1 else "",
            symbol_id=symbols[0].id if len(symbols) == 1 else None,
            market=market,
            expected_dates=tuple(sorted(set(dates))),
        ))
    return HistoricalBackfillPlan(
        start=manifest.request.start, end=manifest.request.end, provider=provider,
        adjustment_type=adjustment_type, base_date=base_date, request_budget=request_budget,
        targets=tuple(targets), dry_run=dry_run,
    )


def plan_from_serialized(value: dict[str, Any]) -> HistoricalBackfillPlan:
    """저장된 immutable manifest를 재개용 plan으로 정확히 복원한다."""
    return HistoricalBackfillPlan(
        start=date.fromisoformat(value["start"]),
        end=date.fromisoformat(value["end"]),
        provider=value["provider"],
        adjustment_type=value["adjustment_type"],
        base_date=value["base_date"],
        request_budget=value["request_budget"],
        dry_run=value["dry_run"],
        targets=tuple(
            HistoricalBackfillTarget(
                instrument_id=target["instrument_id"],
                provider_code=target["provider_code"],
                symbol_id=target["symbol_id"],
                market=target["market"],
                expected_dates=tuple(date.fromisoformat(item) for item in target["expected_dates"]),
            )
            for target in value["targets"]
        ),
    )


class HistoricalBackfillService:
    """Writes page chunks and their durable date checkpoints atomically."""

    def __init__(
        self,
        session: Session,
        state_repository: HistoricalBackfillRepository,
        price_repository: PriceRepository,
    ) -> None:
        self.session = session
        self.state_repository = state_repository
        self.price_repository = price_repository

    def execute(
        self,
        run_id: str,
        plan: HistoricalBackfillPlan,
        page_factory: PageFactory,
        *,
        additional_request_budget: int = 0,
        process_statuses: tuple[str, ...] = ("pending", "running"),
    ) -> HistoricalBackfillReport:
        run, _created = self.state_repository.create_or_resume(run_id, plan)
        if additional_request_budget:
            if _created:
                raise ValueError("새 run에는 additional request budget을 사용할 수 없습니다")
            run = self.state_repository.extend_request_budget(
                run_id=run_id, additional_requests=additional_request_budget,
            )
        report = HistoricalBackfillReport(
            run_id=run_id,
            dry_run=plan.dry_run,
            requests_used=run.requests_used,
            target_count=len(run.targets),
            expected_rows=sum(len(target.expected_dates) for target in run.targets),
            unresolved_targets=sum(
                not target.provider_code or target.symbol_id is None for target in run.targets
            ),
        )
        if plan.dry_run:
            run.status = "dry_run"
            self.session.commit()
            return report
        # ``request_budget`` can be extended on an approved frozen manifest;
        # use the durable run value rather than the original plan value.
        remaining_requests = max(0, run.request_budget - run.requests_used)
        for position, target in enumerate(run.targets):
            if target.status == "completed":
                report.completed_targets += 1
                continue
            if target.status not in process_statuses:
                continue
            if remaining_requests < 1:
                report.budget_exhausted_targets += sum(
                    state.status in process_statuses for state in run.targets[position:]
                )
                run.status = "budget_exhausted"
                self.session.commit()
                break
            try:
                if not target.provider_code or target.symbol_id is None:
                    self.state_repository.mark_target_failure(
                        run_id=run.run_id, instrument_id=target.instrument_id,
                        market=target.market,
                        reason="unresolved_target_identity",
                        evidence={"provider_code": target.provider_code, "symbol_id": target.symbol_id},
                    )
                    report.failed += 1
                    self.session.commit()
                    continue
                pages = page_factory(target, remaining_requests)
                accounted_requests = 0
                for page in pages:
                    accounted_requests, remaining_requests = self._record_request_usage(
                        run, report, pages, accounted_requests, remaining_requests
                    )
                    # A provider may replay the final committed page after a
                    # cursor expires.  Re-evaluate already confirmed dates so
                    # the report records ``unchanged`` instead of hiding it.
                    wanted = set(target.expected_dates)
                    rows = [row for row in page.rows if row.trade_date.isoformat() in wanted]
                    if not rows:
                        continue
                    result = self.price_repository.save_historical_prices(
                        symbol_id=_required_symbol_id(target), prices=rows, provider=run.provider,
                        adjustment_type=run.adjustment_type, historical_backfill_run_id=run.id,
                        source_payload_hash=page.source_payload_hash, parser_version="kiwoom-history-v1",
                    )
                    _merge_report(report, result)
                    self.state_repository.mark_target_progress(
                        run_id=run.run_id, instrument_id=target.instrument_id,
                        market=target.market, confirmed_dates=result.confirmed_dates, retry_count=page.retry_count,
                    )
                    # Price/observation rows and their date checkpoint share the commit boundary.
                    self.session.commit()
                _, remaining_requests = self._record_request_usage(
                    run, report, pages, accounted_requests, remaining_requests
                )
                terminal_reason = getattr(getattr(pages, "summary", None), "terminal_reason", None)
                if terminal_reason in {"collection_start_reached", "provider_exhausted"}:
                    self.state_repository.mark_target_collection_complete(
                        run_id=run.run_id, instrument_id=target.instrument_id, market=target.market,
                    )
                    self.session.commit()
                elif terminal_reason in {"fetch_failed", "provider_unsupported"}:
                    self.state_repository.mark_target_failure(
                        run_id=run.run_id, instrument_id=target.instrument_id, reason=terminal_reason,
                        market=target.market,
                        evidence=getattr(getattr(pages, "summary", None), "error", None),
                    )
                    report.failed += 1
                    report.unsupported += terminal_reason == "provider_unsupported"
                    self.session.commit()
            except Exception as exc:
                self.session.rollback()
                self.state_repository.mark_target_failure(
                    run_id=run.run_id, instrument_id=target.instrument_id, reason="write_failed",
                    market=target.market,
                    evidence={"class": type(exc).__name__, "message": str(exc)},
                )
                report.failed += 1
                self.session.commit()
        refreshed = self.state_repository.get_run(run_id)
        report.completed_targets = sum(target.status == "completed" for target in refreshed.targets)
        self._finalize_run_status(refreshed)
        self.session.commit()
        return report

    def reconcile_targets_with_confirmed_start(self, run_id: str) -> int:
        """Complete legacy checkpoints whose durable rows reach their first expected date.

        Earlier versions retained ``running`` whenever any expected date was
        absent, even after fetching to the beginning of the requested range.
        Replaying those targets would only duplicate observations.  This
        reconciliation uses the strongest persisted proof available: the
        earliest expected date itself was observed.  Later missing dates stay
        in ``remaining_dates`` for the gap validator.
        """
        run = self.state_repository.get_run(run_id)
        if run is None:
            raise KeyError(f"backfill run을 찾을 수 없습니다: {run_id}")
        reconciled = 0
        for target in run.targets:
            if (
                target.status == "running"
                and target.expected_dates
                and target.expected_dates[0] in target.confirmed_dates
            ):
                self.state_repository.mark_target_collection_complete(
                    run_id=run_id, instrument_id=target.instrument_id, market=target.market,
                )
                reconciled += 1
        refreshed = self.state_repository.get_run(run_id)
        self._finalize_run_status(refreshed)
        self.session.commit()
        return reconciled

    def _finalize_run_status(self, run) -> None:
        """Set a terminal run state once every target is collected or explicit failed."""
        statuses = {target.status for target in run.targets}
        if statuses and statuses <= {"completed", "failed"}:
            run.status = "completed" if statuses == {"completed"} else "completed_partial"
            run.completed_at = datetime.utcnow()
            self.session.flush()

    def _record_request_usage(
        self,
        run,
        report: HistoricalBackfillReport,
        pages: Iterable[KiwoomHistoryPage],
        accounted_requests: int,
        remaining_requests: int,
    ) -> tuple[int, int]:
        measured_requests = getattr(getattr(pages, "summary", None), "request_count", 0)
        delta = min(max(0, measured_requests - accounted_requests), remaining_requests)
        if delta:
            run.requests_used += delta
            report.requests_used = run.requests_used
            remaining_requests -= delta
        return measured_requests, remaining_requests


def _required_symbol_id(target: HistoricalBackfillTargetState) -> int:
    if target.symbol_id is None:
        raise ValueError("unresolved_symbol_identity")
    return target.symbol_id


def _merge_report(report: HistoricalBackfillReport, result: HistoricalPriceSaveResult) -> None:
    report.inserted += result.inserted
    report.updated += result.updated
    report.unchanged += result.unchanged
    report.conflict += result.conflict


def _mapping_covers(mapping: ProviderSymbol, trade_date: date) -> bool:
    return (
        (mapping.valid_from is None or mapping.valid_from <= trade_date)
        and (mapping.valid_to is None or trade_date < mapping.valid_to)
    )
