"""공급자 독립적인 bulk EOD source 계약."""

from dataclasses import dataclass
from datetime import date
import hashlib
from typing import Protocol

from app.schemas.market_data import DailyPricePayload
from app.services.validation.market_data import validate_prices


@dataclass(frozen=True)
class EodBatch:
    """시장 단위 EOD 파일/API 응답의 정규화된 형태."""

    provider: str
    trade_date: date
    rows_by_code: dict[str, list[DailyPricePayload]]
    checksum: str | None = None
    checksum_algorithm: str = "sha256"
    checksum_verified: bool | None = None
    raw_payload: bytes | str | None = None
    expected_row_count: int | None = None
    market: str | None = None
    adjusted_prices: bool | None = None
    complete: bool = True
    request_url: str | None = None
    response_bytes: int | None = None
    error_message: str | None = None


class BulkEodSource(Protocol):
    """계약된 EOD 공급자가 구현해야 하는 최소 인터페이스."""

    def fetch_eod_prices(self, market: str, trade_date: date) -> EodBatch: ...


@dataclass(frozen=True)
class EodCanaryPolicy:
    """Feature-flagged market/code allowlist for a provider canary."""

    enabled: bool = True
    markets: frozenset[str] = frozenset()
    codes: frozenset[str] = frozenset()

    def allows(self, *, market: str, code: str) -> bool:
        if not self.enabled:
            return False
        if self.markets and market not in self.markets:
            return False
        if self.codes and code not in self.codes:
            return False
        return True

    @classmethod
    def from_settings(cls, settings) -> "EodCanaryPolicy":
        markets = frozenset(
            value.strip().upper()
            for value in settings.eod_canary_markets.split(",")
            if value.strip()
        )
        codes = frozenset(
            value.strip()
            for value in settings.eod_canary_codes.split(",")
            if value.strip()
        )
        return cls(
            enabled=settings.eod_provider_enabled,
            markets=markets,
            codes=codes,
        )


class EodBatchValidationError(ValueError):
    """bulk 응답이 저장 계약을 만족하지 못할 때 발생한다."""


def validate_eod_batch(
    batch: EodBatch,
    *,
    eligible_codes: set[str],
    expected_trade_date: date,
    expected_market: str | None = None,
) -> None:
    """파일 전체를 저장하기 전에 구조·기준일·종목·가격을 검증한다."""
    if not batch.provider.strip():
        raise EodBatchValidationError("EOD provider is empty")
    if batch.market is not None and batch.market not in {"ALL", "KOSPI", "KOSDAQ"}:
        raise EodBatchValidationError(f"EOD market is invalid: {batch.market}")
    if (
        expected_market is not None
        and batch.market is not None
        and batch.market not in {"ALL", expected_market}
    ):
        raise EodBatchValidationError(
            f"EOD market mismatch: {batch.market} != {expected_market}"
        )
    if batch.trade_date != expected_trade_date:
        raise EodBatchValidationError(
            f"EOD trade date mismatch: {batch.trade_date} != {expected_trade_date}"
        )
    if not batch.complete:
        raise EodBatchValidationError(batch.error_message or "EOD batch is incomplete")
    if not batch.rows_by_code:
        raise EodBatchValidationError("EOD batch has no rows")

    if batch.checksum:
        algorithm = batch.checksum_algorithm.lower().replace("-", "")
        try:
            digest = hashlib.new(algorithm)
        except ValueError as exc:
            raise EodBatchValidationError(
                f"unsupported EOD checksum algorithm: {batch.checksum_algorithm}"
            ) from exc

        if batch.raw_payload is not None:
            payload = (
                batch.raw_payload.encode("utf-8")
                if isinstance(batch.raw_payload, str)
                else batch.raw_payload
            )
            digest.update(payload)
            if digest.hexdigest().lower() != batch.checksum.strip().lower():
                raise EodBatchValidationError("EOD checksum mismatch")
        elif batch.checksum_verified is not True:
            raise EodBatchValidationError("EOD checksum was not verified")

    if batch.expected_row_count is not None:
        actual_row_count = sum(len(rows) for rows in batch.rows_by_code.values())
        if actual_row_count != batch.expected_row_count:
            raise EodBatchValidationError(
                f"EOD row count mismatch: {actual_row_count} != {batch.expected_row_count}"
            )

    unknown_codes = set(batch.rows_by_code) - eligible_codes
    if unknown_codes:
        sample = ", ".join(sorted(unknown_codes)[:5])
        raise EodBatchValidationError(f"EOD batch contains unknown symbols: {sample}")

    for code, rows in batch.rows_by_code.items():
        if not code or code not in eligible_codes:
            raise EodBatchValidationError(f"EOD symbol code is not eligible: {code}")
        if not rows:
            raise EodBatchValidationError(f"EOD rows are empty: {code}")
        dates = [row.trade_date for row in rows]
        if any(row_date != batch.trade_date for row_date in dates):
            raise EodBatchValidationError(f"EOD row date mismatch: {code}")
        if len(set(dates)) != len(dates):
            raise EodBatchValidationError(f"EOD duplicate trade date: {code}")

        validate_prices(rows)
