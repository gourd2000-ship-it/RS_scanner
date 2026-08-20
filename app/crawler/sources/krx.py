"""KRX Open API 기반 기준일 유니버스 source."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from app.crawler.krx_client import KrxHttpClient
from app.crawler.parsers.krx import (
    KrxStockMembership,
    KrxUniverseNoDataError,
    parse_krx_membership,
)
from app.core.market_calendar import krx_market_day_status


class KrxJsonClient(Protocol):
    def get_json(self, api_id: str, *, params: dict[str, str]) -> dict: ...


@dataclass(frozen=True)
class KrxUniverseFetchResult:
    """KRX 시장별 호출을 합친 shadow membership 수집 결과."""

    as_of_date: date
    members: list[KrxStockMembership]
    complete: bool
    error_message: str | None = None


class KrxUniverseSource:
    """KRX 일별매매정보에서 주식 membership 후보를 읽는다."""

    provider_name = "krx_open_api"
    _STOCK_APIS = (
        ("stk_bydd_trd", "KOSPI", "stock"),
        ("ksq_bydd_trd", "KOSDAQ", "stock"),
    )
    _ETP_APIS = (
        # ETF/ETN 일별매매정보에는 시장 필드가 없으며 유가증권시장 상품이다.
        ("etf_bydd_trd", "KOSPI", "etf"),
        ("etn_bydd_trd", "KOSPI", "etn"),
    )

    def __init__(self, client: KrxJsonClient | None = None) -> None:
        self.client = client or KrxHttpClient()

    def fetch_stock_membership(self, as_of_date: date) -> KrxUniverseFetchResult:
        """현재 상장 membership으로 승인된 KOSPI/KOSDAQ 주식만 수집한다."""
        return self._fetch_membership(as_of_date, self._STOCK_APIS)

    def fetch_latest_stock_membership(self, requested_as_of_date: date) -> KrxUniverseFetchResult:
        """KRX가 공개한 가장 최근 거래일의 주식 membership을 가져온다.

        일별매매정보는 장 마감 뒤에도 당일분이 비어 있을 수 있다. 두 주식 feed가
        모두 아직 미공개인 경우에만 직전 KRX 거래일을 한 번 조회한다. 부분 응답이나
        계약 오류에는 이전 데이터를 덮어쓰지 않고 원래 결과를 보존한다.
        """
        fetched = self.fetch_stock_membership(requested_as_of_date)
        if fetched.complete or not self._all_stock_feeds_not_published(fetched):
            return fetched

        previous_open_day = _previous_krx_open_day(requested_as_of_date)
        return self.fetch_stock_membership(previous_open_day)

    def fetch_etp_observations(self, as_of_date: date) -> KrxUniverseFetchResult:
        """ETF/ETN 거래 관측을 shadow로 수집한다.

        이 결과는 API contract의 count/code 대조가 승인되기 전까지 가격 대상
        membership으로 승격하지 않는다.
        """
        return self._fetch_membership(as_of_date, self._ETP_APIS)

    def _fetch_membership(
        self,
        as_of_date: date,
        feeds: tuple[tuple[str, str, str], ...],
    ) -> KrxUniverseFetchResult:
        params = {"basDd": as_of_date.strftime("%Y%m%d")}
        members: list[KrxStockMembership] = []
        errors: list[str] = []

        for api_id, market, security_type in feeds:
            try:
                payload = self.client.get_json(api_id, params=params)
                members.extend(
                    parse_krx_membership(
                        payload,
                        expected_market=market,
                        expected_security_type=security_type,
                        expected_as_of_date=as_of_date,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{security_type}:{market}:{type(exc).__name__}")

        return KrxUniverseFetchResult(
            as_of_date=as_of_date,
            members=members,
            complete=not errors,
            error_message=";".join(errors) if errors else None,
        )

    @classmethod
    def _all_stock_feeds_not_published(cls, fetched: KrxUniverseFetchResult) -> bool:
        if fetched.members or not fetched.error_message:
            return False
        errors = set(fetched.error_message.split(";"))
        expected = {
            f"{security_type}:{market}:{KrxUniverseNoDataError.__name__}"
            for _, market, security_type in cls._STOCK_APIS
        }
        return errors == expected


def _previous_krx_open_day(value: date) -> date:
    candidate = value - timedelta(days=1)
    while not krx_market_day_status(candidate).is_open:
        candidate -= timedelta(days=1)
    return candidate
