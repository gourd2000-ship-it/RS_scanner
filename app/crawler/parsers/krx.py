"""KRX Open API 유니버스 응답 parser."""

from dataclasses import dataclass
from datetime import date
import re
from typing import Any


class KrxUniverseParseError(ValueError):
    """KRX 유니버스 응답이 승인된 계약을 만족하지 않을 때 발생한다."""


class KrxUniverseNoDataError(KrxUniverseParseError):
    """KRX가 해당 기준일의 일별매매정보를 아직 공개하지 않았을 때 발생한다."""


@dataclass(frozen=True)
class KrxStockMembership:
    as_of_date: date
    code: str
    name: str
    market: str
    security_type: str
    listing_status: str
    trading_status: str
    raw_fields: dict[str, Any]


_CODE_PATTERN = re.compile(r"[0-9A-Za-z]{6}")
_REQUIRED_FIELDS = ("BAS_DD", "ISU_CD", "ISU_NM", "MKT_NM")


def parse_krx_stock_membership(
    payload: dict[str, Any],
    *,
    expected_market: str,
    expected_as_of_date: date,
) -> list[KrxStockMembership]:
    """일별매매정보를 기준일 주식 membership 후보로 정규화한다."""
    return parse_krx_membership(
        payload,
        expected_market=expected_market,
        expected_security_type="stock",
        expected_as_of_date=expected_as_of_date,
    )


def parse_krx_membership(
    payload: dict[str, Any],
    *,
    expected_market: str,
    expected_security_type: str,
    expected_as_of_date: date,
) -> list[KrxStockMembership]:
    """정해진 KRX feed의 membership 후보를 보존적으로 정규화한다.

    ETF/ETN 일별매매정보에는 ``MKT_NM``이 없으므로, feed 계약에서 정한
    시장을 사용한다. 주식 feed는 응답의 시장 값도 반드시 일치해야 한다.
    """
    rows = payload.get("OutBlock_1")
    if not isinstance(rows, list) or not rows:
        raise KrxUniverseNoDataError("KRX OutBlock_1 응답이 비어 있습니다")

    normalized_market = expected_market.upper()
    members: list[KrxStockMembership] = []
    seen_codes: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise KrxUniverseParseError(f"KRX 응답 행 형식이 올바르지 않습니다: {index}")
        required_fields = tuple(field for field in _REQUIRED_FIELDS if field != "MKT_NM")
        missing_fields = [field for field in required_fields if not str(row.get(field, "")).strip()]
        if missing_fields:
            raise KrxUniverseParseError(
                f"KRX 응답 필수 필드가 없습니다: {','.join(missing_fields)}"
            )

        row_date = _parse_krx_date(str(row["BAS_DD"]))
        if row_date != expected_as_of_date:
            raise KrxUniverseParseError(
                f"KRX 기준일이 일치하지 않습니다: {row_date} != {expected_as_of_date}"
            )

        source_market = str(row.get("MKT_NM", "")).strip().upper()
        if source_market and source_market != normalized_market:
            raise KrxUniverseParseError(
                f"KRX 시장이 일치하지 않습니다: {source_market} != {normalized_market}"
            )

        code = str(row["ISU_CD"]).strip()
        if not _CODE_PATTERN.fullmatch(code):
            raise KrxUniverseParseError(f"KRX 종목코드 형식이 올바르지 않습니다: {code}")
        if code in seen_codes:
            raise KrxUniverseParseError(f"KRX 응답에 중복 종목코드가 있습니다: {code}")
        seen_codes.add(code)

        members.append(
            KrxStockMembership(
                as_of_date=row_date,
                code=code,
                name=str(row["ISU_NM"]).strip(),
                market=normalized_market,
                security_type=expected_security_type,
                listing_status="listed_observed",
                trading_status="unknown",
                raw_fields=dict(row),
            )
        )
    return members


def _parse_krx_date(value: str) -> date:
    if not re.fullmatch(r"\d{8}", value):
        raise KrxUniverseParseError(f"KRX 기준일 형식이 올바르지 않습니다: {value}")
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError as exc:
        raise KrxUniverseParseError(f"KRX 기준일 값이 올바르지 않습니다: {value}") from exc
