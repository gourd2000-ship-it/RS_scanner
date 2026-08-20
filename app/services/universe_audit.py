"""종목 universe의 legacy·stale 후보를 읽기 전용으로 진단한다."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable


_PROVIDER_CODE_PATTERN = re.compile(r"[0-9A-Za-z]{6}")


@dataclass(frozen=True)
class AuditSymbol:
    """감사에 필요한 종목 상태의 최소 표현."""

    code: str
    name: str
    market: str
    symbol_type: str
    is_active: bool
    last_snapshot_id: int | None


@dataclass(frozen=True)
class UniverseAuditCandidate:
    """자동 반영 전 운영자 검토가 필요한 종목 후보."""

    code: str
    name: str
    market: str
    symbol_type: str
    last_snapshot_id: int | None
    reason_codes: tuple[str, ...]
    replacement_code: str | None
    prefix_matches: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class UniverseAuditReport:
    """하나의 completed snapshot을 기준으로 만든 dry-run 결과."""

    latest_completed_snapshot_id: int | None
    candidates: tuple[UniverseAuditCandidate, ...]
    reason_counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "latest_completed_snapshot_id": self.latest_completed_snapshot_id,
            "candidate_count": len(self.candidates),
            "reason_counts": self.reason_counts,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _is_valid_provider_code(code: str) -> bool:
    return bool(_PROVIDER_CODE_PATTERN.fullmatch(code))


def _prefix_matches(
    symbol: AuditSymbol,
    active_symbols: Iterable[AuditSymbol],
) -> tuple[str, ...]:
    """같은 종목 메타데이터를 가진 유효한 확장 code만 반환한다."""
    matches = {
        candidate.code
        for candidate in active_symbols
        if (
            candidate.code != symbol.code
            and _is_valid_provider_code(candidate.code)
            and candidate.code.startswith(symbol.code)
            and candidate.name == symbol.name
            and candidate.market == symbol.market
            and candidate.symbol_type == symbol.symbol_type
        )
    }
    return tuple(sorted(matches))


def build_universe_audit_report(
    *,
    symbols: Iterable[AuditSymbol],
    latest_completed_snapshot_id: int | None,
) -> UniverseAuditReport:
    """active 종목을 검사해 사람이 승인할 후보만 반환한다.

    이 함수는 입력 객체와 저장소를 변경하지 않는다. ``replacement_code``는 이름·시장·유형이
    모두 같은 단일 prefix 후보일 때만 제안하며, 실제 정정이나 비활성화는 별도 승인 단계의
    책임이다.
    """
    active_symbols = tuple(symbol for symbol in symbols if symbol.is_active)
    candidates: list[UniverseAuditCandidate] = []
    reason_counts: Counter[str] = Counter()

    for symbol in active_symbols:
        reason_codes: list[str] = []
        prefix_matches: tuple[str, ...] = ()

        if not _is_valid_provider_code(symbol.code):
            reason_codes.append("invalid_legacy")
            prefix_matches = _prefix_matches(symbol, active_symbols)
            if prefix_matches:
                reason_codes.append("prefix_collision")

        if (
            latest_completed_snapshot_id is not None
            and symbol.last_snapshot_id != latest_completed_snapshot_id
        ):
            reason_codes.extend(
                ["missing_from_latest_snapshot", "stale_active"]
            )

        if not reason_codes:
            continue

        replacement_code = prefix_matches[0] if len(prefix_matches) == 1 else None
        candidate = UniverseAuditCandidate(
            code=symbol.code,
            name=symbol.name,
            market=symbol.market,
            symbol_type=symbol.symbol_type,
            last_snapshot_id=symbol.last_snapshot_id,
            reason_codes=tuple(reason_codes),
            replacement_code=replacement_code,
            prefix_matches=prefix_matches,
        )
        candidates.append(candidate)
        reason_counts.update(reason_codes)

    return UniverseAuditReport(
        latest_completed_snapshot_id=latest_completed_snapshot_id,
        candidates=tuple(sorted(candidates, key=lambda item: item.code)),
        reason_counts=dict(sorted(reason_counts.items())),
    )
