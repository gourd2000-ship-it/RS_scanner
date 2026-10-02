"""현재 KRX identity에 대한 Kiwoom provider mapping을 보수적으로 준비한다."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CurrentMappingCandidate:
    instrument_id: int
    krx_short_code: str
    market: str
    listed_at: date | None
    listing_status: str
    symbol_code: str | None
    symbol_market: str | None
    naver_provider_symbol: str | None
    has_kiwoom_mapping: bool


@dataclass(frozen=True)
class KiwoomMappingCreate:
    instrument_id: int
    provider_symbol: str
    valid_from: date


@dataclass(frozen=True)
class KiwoomMappingPlan:
    creates: list[KiwoomMappingCreate]
    unresolved: list[dict]


def plan_kiwoom_current_mappings(candidates: list[CurrentMappingCandidate]) -> KiwoomMappingPlan:
    """현재 Symbol·Naver 증거가 code/market에 모두 일치할 때만 Kiwoom을 추가한다."""
    creates: list[KiwoomMappingCreate] = []
    unresolved: list[dict] = []
    for candidate in sorted(candidates, key=lambda row: row.instrument_id):
        if candidate.has_kiwoom_mapping:
            continue
        exact = (
            candidate.listing_status == "listed"
            and candidate.listed_at is not None
            and candidate.symbol_code == candidate.krx_short_code
            and candidate.symbol_market == candidate.market
            and candidate.naver_provider_symbol == candidate.krx_short_code
        )
        if not exact:
            unresolved.append({"instrument_id": candidate.instrument_id, "reason": "non_exact_current_evidence"})
            continue
        creates.append(KiwoomMappingCreate(
            candidate.instrument_id, candidate.krx_short_code, candidate.listed_at,
        ))
    return KiwoomMappingPlan(creates, unresolved)
