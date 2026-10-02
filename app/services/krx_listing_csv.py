"""KRX CP949 상장·상폐 CSV를 검토 가능한 listing-event JSON으로 변환한다."""

import csv
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from io import StringIO
from typing import Iterable


@dataclass(frozen=True)
class CanonicalInstrument:
    id: int
    krx_short_code: str
    market: str
    listed_at: date | None
    delisted_at: date | None


@dataclass(frozen=True)
class ExistingInstrument:
    """DB에 이미 있는 identity의 reconciliation 전용 최소 표현."""

    id: int
    krx_short_code: str
    market: str
    listed_at: date | None
    delisted_at: date | None
    listing_status: str


@dataclass(frozen=True)
class KrxLifecycle:
    """KRX CSV가 직접 관측한 하나의 code·market·상장일 생애주기."""

    krx_short_code: str
    market: str
    listed_at: date
    delisted_at: date | None
    name: str
    delisted_dates: tuple[date, ...]
    source_files: tuple[dict, ...]


@dataclass(frozen=True)
class IdentityUpdate:
    instrument_id: int
    listed_at: date


@dataclass(frozen=True)
class IdentityCreate:
    krx_short_code: str
    name: str
    market: str
    listed_at: date
    delisted_at: date
    listing_status: str


@dataclass(frozen=True)
class IdentityReconciliationPlan:
    updates: list[IdentityUpdate]
    creates: list[IdentityCreate]
    unresolved: list[dict]


@dataclass(frozen=True)
class PreparedListingEvents:
    events: list[dict]
    unresolved: list[dict]
    excluded: dict[str, int]
    source_files: list[dict]


def build_krx_lifecycles(files: Iterable[tuple[str, bytes]]) -> list[KrxLifecycle]:
    """CSV 증거를 code 재사용에 안전한 lifecycle 단위로 합친다.

    표시명은 DB의 표시값으로만 보존하며, identity 결합에 사용하지 않는다.
    상장 목록과 상폐 목록이 서로 다른 폐지일을 말하면 날짜를 선택하지 않고
    ``delisted_dates``를 모두 남긴다.
    """
    observations: dict[tuple[str, str, date], list[dict]] = {}
    for source_file, raw in files:
        source_hash = sha256(raw).hexdigest()
        rows = csv.DictReader(StringIO(_decode_csv(raw)))
        is_delisting_file = "폐지일" in (rows.fieldnames or ())
        for row in rows:
            if _text(row, "증권구분") != "주권" or _text(row, "주식종류") != "보통주":
                continue
            code = _text(row, "종목코드")
            market = _text(row, "시장구분")
            listed_at = _date(row, "상장일")
            if not code or not market or listed_at is None:
                continue
            delisted_at = _date(row, "폐지일" if is_delisting_file else "상장폐지일")
            observations.setdefault((code, market, listed_at), []).append({
                "name": _text(row, "종목명"),
                "delisted_at": delisted_at,
                "source_file": source_file,
                "source_file_hash": source_hash,
            })

    lifecycles: list[KrxLifecycle] = []
    for (code, market, listed_at), rows in observations.items():
        delisted_dates = tuple(sorted({row["delisted_at"] for row in rows if row["delisted_at"] is not None}))
        source_files = tuple(sorted(
            ({"path": row["source_file"], "sha256": row["source_file_hash"]} for row in rows),
            key=lambda item: (item["path"], item["sha256"]),
        ))
        names = sorted({row["name"] for row in rows if row["name"]})
        lifecycles.append(KrxLifecycle(
            krx_short_code=code,
            market=market,
            listed_at=listed_at,
            delisted_at=delisted_dates[0] if len(delisted_dates) == 1 else None,
            name=names[0] if names else code,
            delisted_dates=delisted_dates,
            source_files=source_files,
        ))
    return sorted(lifecycles, key=lambda item: (item.krx_short_code, item.market, item.listed_at))


def plan_identity_reconciliation(
    lifecycles: Iterable[KrxLifecycle],
    instruments: Iterable[ExistingInstrument],
) -> IdentityReconciliationPlan:
    """검증된 종료 identity만 만들고, 유일한 현재 identity만 날짜를 보완한다."""
    lifecycle_rows = tuple(lifecycles)
    existing_rows = tuple(instruments)
    existing_by_pair: dict[tuple[str, str], list[ExistingInstrument]] = {}
    existing_by_identity: dict[tuple[str, str, date, date | None], list[ExistingInstrument]] = {}
    for instrument in existing_rows:
        existing_by_pair.setdefault((instrument.krx_short_code, instrument.market), []).append(instrument)
        if instrument.listed_at is not None:
            key = (instrument.krx_short_code, instrument.market, instrument.listed_at, instrument.delisted_at)
            existing_by_identity.setdefault(key, []).append(instrument)

    valid_open_by_pair: dict[tuple[str, str], list[KrxLifecycle]] = {}
    conflict_by_pair: set[tuple[str, str]] = set()
    for lifecycle in lifecycle_rows:
        pair = (lifecycle.krx_short_code, lifecycle.market)
        if len(lifecycle.delisted_dates) > 1:
            conflict_by_pair.add(pair)
        elif lifecycle.delisted_at is None:
            valid_open_by_pair.setdefault(pair, []).append(lifecycle)

    updates: list[IdentityUpdate] = []
    creates: list[IdentityCreate] = []
    unresolved: list[dict] = []
    for lifecycle in lifecycle_rows:
        pair = (lifecycle.krx_short_code, lifecycle.market)
        if len(lifecycle.delisted_dates) > 1:
            unresolved.append({
                "code": lifecycle.krx_short_code,
                "market": lifecycle.market,
                "listed_at": lifecycle.listed_at.isoformat(),
                "reason": "conflicting_delisted_at",
                "delisted_dates": [value.isoformat() for value in lifecycle.delisted_dates],
            })
            continue
        if lifecycle.delisted_at is not None and lifecycle.delisted_at <= lifecycle.listed_at:
            unresolved.append({
                "code": lifecycle.krx_short_code,
                "market": lifecycle.market,
                "listed_at": lifecycle.listed_at.isoformat(),
                "reason": "invalid_lifecycle_interval",
            })
            continue

        exact = existing_by_identity.get((
            lifecycle.krx_short_code, lifecycle.market, lifecycle.listed_at, lifecycle.delisted_at,
        ), [])
        if len(exact) == 1:
            continue
        if len(exact) > 1:
            unresolved.append(_identity_unresolved(lifecycle, "duplicate_existing_identity"))
            continue

        if lifecycle.delisted_at is not None:
            dated_existing = [row for row in existing_by_pair.get(pair, []) if row.listed_at is not None]
            if dated_existing:
                unresolved.append(_identity_unresolved(lifecycle, "existing_identity_date_conflict"))
                continue
            creates.append(IdentityCreate(
                krx_short_code=lifecycle.krx_short_code,
                name=lifecycle.name,
                market=lifecycle.market,
                listed_at=lifecycle.listed_at,
                delisted_at=lifecycle.delisted_at,
                listing_status="delisted",
            ))
            continue

        candidates = existing_by_pair.get(pair, [])
        open_lifecycles = valid_open_by_pair.get(pair, [])
        can_update = (
            pair not in conflict_by_pair
            and len(candidates) == 1
            and candidates[0].listed_at is None
            and candidates[0].delisted_at is None
            and candidates[0].listing_status != "delisted"
            and len(open_lifecycles) == 1
        )
        if can_update:
            updates.append(IdentityUpdate(candidates[0].id, lifecycle.listed_at))
        else:
            unresolved.append(_identity_unresolved(lifecycle, "unmatched_or_ambiguous_open_lifecycle"))

    updates.sort(key=lambda row: row.instrument_id)
    creates.sort(key=lambda row: (row.krx_short_code, row.market, row.listed_at))
    unresolved.sort(key=lambda row: (row["code"], row["market"], row["listed_at"], row["reason"]))
    return IdentityReconciliationPlan(updates, creates, unresolved)


def prepare_listing_events(
    files: Iterable[tuple[str, bytes]],
    instruments: Iterable[CanonicalInstrument],
) -> PreparedListingEvents:
    """정확한 code·market·유효일 identity만 event에 연결한다.

    이름은 사람이 검토할 증거일 뿐 mapping key가 아니다. 코드 재사용이나 날짜
    불일치는 ``unresolved``로 남겨 수동 검토 전에는 import하지 않는다.
    """
    identities = tuple(instruments)
    events: list[dict] = []
    unresolved: list[dict] = []
    excluded: dict[str, int] = {}
    source_files: list[dict] = []

    for source_file, raw in files:
        source_hash = sha256(raw).hexdigest()
        source_files.append({"path": source_file, "sha256": source_hash})
        rows = csv.DictReader(StringIO(_decode_csv(raw)))
        is_delisting_file = "폐지일" in (rows.fieldnames or ())
        for row in rows:
            security_kind = _text(row, "증권구분")
            stock_kind = _text(row, "주식종류")
            if security_kind != "주권":
                _increment(excluded, f"security_kind_{security_kind or 'missing'}")
                continue
            if stock_kind != "보통주":
                _increment(excluded, f"stock_kind_{stock_kind or 'missing'}")
                continue
            code = _text(row, "종목코드")
            market = _text(row, "시장구분")
            event_type = "delisted" if is_delisting_file else "listed"
            effective_date = _date(row, "폐지일" if is_delisting_file else "상장일")
            if not code or not market or effective_date is None:
                unresolved.append(_unresolved(source_file, code, market, event_type, effective_date, "missing_required_value"))
                continue
            instrument = _resolve(identities, code, market, effective_date, event_type)
            if instrument is None:
                unresolved.append(_unresolved(source_file, code, market, event_type, effective_date, "no_exact_instrument"))
                continue
            events.append({
                "instrument_id": instrument.id,
                "source_record_key": f"krx:{event_type}:{code}:{market}:{effective_date.isoformat()}",
                "event_type": event_type,
                "effective_from": effective_date.isoformat(),
                "market": market,
                "provider_code": code,
                "evidence_state": "observed",
                "payload": {
                    "source_file": source_file,
                    "source_file_hash": source_hash,
                    "code": code,
                    "name": _text(row, "종목명"),
                    "market": market,
                    "security_kind": security_kind,
                    "stock_kind": stock_kind,
                    "listed_at": _date_text(row, "상장일"),
                    "delisted_at": _date_text(row, "폐지일") or _date_text(row, "상장폐지일"),
                },
            })
    events.sort(key=lambda item: (item["effective_from"], item["event_type"], item["instrument_id"]))
    unresolved.sort(key=lambda item: (item["source_file"], item["event_type"], item["code"], item["effective_date"] or ""))
    return PreparedListingEvents(events, unresolved, excluded, source_files)


def _decode_csv(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("KRX CSV must be UTF-8 or CP949")


def _resolve(
    instruments: tuple[CanonicalInstrument, ...],
    code: str,
    market: str,
    effective_date: date,
    event_type: str,
) -> CanonicalInstrument | None:
    candidates = [
        instrument for instrument in instruments
        if instrument.krx_short_code == code and instrument.market == market
        and (instrument.delisted_at == effective_date if event_type == "delisted" else instrument.listed_at == effective_date)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _text(row: dict[str, str | None], field: str) -> str:
    return (row.get(field) or "").strip()


def _date(row: dict[str, str | None], field: str) -> date | None:
    value = _text(row, field)
    return date.fromisoformat(value.replace("/", "-")) if value else None


def _date_text(row: dict[str, str | None], field: str) -> str | None:
    value = _date(row, field)
    return value.isoformat() if value else None


def _unresolved(source_file, code, market, event_type, effective_date, reason) -> dict:
    return {
        "source_file": source_file, "code": code, "market": market,
        "event_type": event_type,
        "effective_date": effective_date.isoformat() if effective_date else None,
        "reason": reason,
    }


def _identity_unresolved(lifecycle: KrxLifecycle, reason: str) -> dict:
    return {
        "code": lifecycle.krx_short_code,
        "market": lifecycle.market,
        "listed_at": lifecycle.listed_at.isoformat(),
        "reason": reason,
    }


def _increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1
