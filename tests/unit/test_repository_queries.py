"""레포지토리 쿼리 기능 단위 테스트."""

from datetime import date
from decimal import Decimal

import pytest

from app.repositories.memory_rs_repository import MemoryRsRepository
from app.repositories.memory_symbol_repository import MemorySymbolRepository
from app.schemas.market_data import RsResultPayload, SymbolPayload


class TestRsRepository:
    """RsRepository 확장 기능 테스트."""

    @pytest.fixture
    def rs_repo(self):
        """테스트용 RS 레포지토리."""
        repo = MemoryRsRepository()
        # 샘플 데이터 생성
        test_date = date(2024, 5, 28)
        samples = [
            RsResultPayload(
                code="005930",
                market="KOSPI",
                trade_date=test_date,
                return_3m=Decimal("15.5"),
                return_6m=Decimal("20.3"),
                return_9m=Decimal("25.1"),
                return_12m=Decimal("30.2"),
                relative_return_score=Decimal("22.5"),
                rs_percentile=Decimal("0.95"),
                rs_rating=95,
                rank_in_market=5,
            ),
            RsResultPayload(
                code="000660",
                market="KOSPI",
                trade_date=test_date,
                return_3m=Decimal("5.2"),
                return_6m=Decimal("8.1"),
                return_9m=Decimal("10.5"),
                return_12m=Decimal("12.3"),
                relative_return_score=Decimal("8.5"),
                rs_percentile=Decimal("0.50"),
                rs_rating=50,
                rank_in_market=100,
            ),
            RsResultPayload(
                code="035720",
                market="KOSPI",
                trade_date=test_date,
                return_3m=Decimal("25.8"),
                return_6m=Decimal("35.2"),
                return_9m=Decimal("40.5"),
                return_12m=Decimal("45.1"),
                relative_return_score=Decimal("35.5"),
                rs_percentile=Decimal("0.99"),
                rs_rating=99,
                rank_in_market=1,
            ),
        ]
        repo.save_many("KOSPI", samples)
        return repo

    def test_filter_by_rs_rating(self, rs_repo):
        """RS Rating 필터링 테스트."""
        # RS Rating 90 이상만 조회
        items, total_count, _ = rs_repo.list_market_with_prices(
            market="KOSPI",
            min_rs=90,
        )

        assert total_count == 2
        assert len(items) == 2
        assert all(item["rs_rating"] >= 90 for item in items)

    def test_filter_by_rs_rating_range(self, rs_repo):
        """RS Rating 범위 필터링 테스트."""
        # RS Rating 50~95 범위
        items, total_count, _ = rs_repo.list_market_with_prices(
            market="KOSPI",
            min_rs=50,
            max_rs=95,
        )

        assert total_count == 2
        assert len(items) == 2
        assert all(50 <= item["rs_rating"] <= 95 for item in items)

    def test_sort_by_return_3m_desc(self, rs_repo):
        """return_3m 기준 내림차순 정렬 테스트."""
        items, total_count, _ = rs_repo.list_market_with_prices(
            market="KOSPI",
            sort_by="return_3m",
            order="desc",
        )

        assert total_count == 3
        assert len(items) == 3
        # 내림차순 확인
        assert items[0]["return_3m"] >= items[1]["return_3m"]
        assert items[1]["return_3m"] >= items[2]["return_3m"]

    def test_sort_by_rs_rating_asc(self, rs_repo):
        """rs_rating 기준 오름차순 정렬 테스트."""
        items, total_count, _ = rs_repo.list_market_with_prices(
            market="KOSPI",
            sort_by="rs_rating",
            order="asc",
        )

        assert total_count == 3
        assert len(items) == 3
        # 오름차순 확인
        assert items[0]["rs_rating"] == 50
        assert items[1]["rs_rating"] == 95
        assert items[2]["rs_rating"] == 99

    def test_pagination(self, rs_repo):
        """페이지네이션 테스트."""
        # 페이지 크기 2
        items_page1, total_count, _ = rs_repo.list_market_with_prices(
            market="KOSPI",
            page=1,
            size=2,
        )

        assert total_count == 3
        assert len(items_page1) == 2

        # 2페이지
        items_page2, total_count, _ = rs_repo.list_market_with_prices(
            market="KOSPI",
            page=2,
            size=2,
        )

        assert total_count == 3
        assert len(items_page2) == 1


class TestSymbolRepository:
    """SymbolRepository 확장 기능 테스트."""

    @pytest.fixture
    def symbol_repo(self):
        """테스트용 Symbol 레포지토리."""
        repo = MemorySymbolRepository()
        # 샘플 데이터 생성
        samples = [
            SymbolPayload(code="005930", name="삼성전자", market="KOSPI"),
            SymbolPayload(code="000660", name="SK하이닉스", market="KOSPI"),
            SymbolPayload(code="035720", name="카카오", market="KOSDAQ"),
            SymbolPayload(code="035420", name="NAVER", market="KOSDAQ"),
            SymbolPayload(code="068270", name="셀트리온", market="KOSPI"),
        ]
        repo.upsert_many(samples)
        return repo

    def test_filter_by_market(self, symbol_repo):
        """시장별 필터링 테스트."""
        # KOSPI 종목만
        items, total_count = symbol_repo.list_filtered(market="KOSPI")

        assert total_count == 3
        assert len(items) == 3
        assert all(item.market == "KOSPI" for item in items)

        # KOSDAQ 종목만
        items, total_count = symbol_repo.list_filtered(market="KOSDAQ")

        assert total_count == 2
        assert len(items) == 2
        assert all(item.market == "KOSDAQ" for item in items)

    def test_filter_by_is_active(self, symbol_repo):
        """상장 여부 필터링 테스트."""
        # in-memory 레포지토리는 모두 is_active=True로 설정
        items, total_count = symbol_repo.list_filtered(is_active=True)

        assert total_count == 5
        assert len(items) == 5
        assert all(item.is_active for item in items)

    def test_search_by_name(self, symbol_repo):
        """종목명 검색 테스트."""
        # "삼성" 검색
        items, total_count = symbol_repo.list_filtered(search="삼성")

        assert total_count == 1
        assert len(items) == 1
        assert items[0].code == "005930"

        # "카" 검색 (카카오 매칭)
        items, total_count = symbol_repo.list_filtered(search="카")

        assert total_count == 1
        assert items[0].code == "035720"

    def test_search_by_code(self, symbol_repo):
        """종목코드 검색 테스트."""
        # "0059" 검색
        items, total_count = symbol_repo.list_filtered(search="0059")

        assert total_count == 1
        assert items[0].code == "005930"

    def test_search_case_insensitive(self, symbol_repo):
        """대소문자 무시 검색 테스트."""
        # "NAVER" 검색 (대문자)
        items, total_count = symbol_repo.list_filtered(search="NAVER")

        assert total_count == 1
        assert items[0].code == "035420"

        # "naver" 검색 (소문자)
        items, total_count = symbol_repo.list_filtered(search="naver")

        assert total_count == 1
        assert items[0].code == "035420"

    def test_combined_filters(self, symbol_repo):
        """복합 필터 테스트."""
        # KOSPI + "S" 검색 (SK하이닉스 매칭)
        items, total_count = symbol_repo.list_filtered(
            market="KOSPI",
            search="SK",
        )

        assert total_count == 1
        assert items[0].code == "000660"

    def test_pagination(self, symbol_repo):
        """페이지네이션 테스트."""
        # 페이지 크기 2
        items_page1, total_count = symbol_repo.list_filtered(
            page=1,
            size=2,
        )

        assert total_count == 5
        assert len(items_page1) == 2

        # 3페이지
        items_page3, total_count = symbol_repo.list_filtered(
            page=3,
            size=2,
        )

        assert total_count == 5
        assert len(items_page3) == 1

    def test_sorting(self, symbol_repo):
        """정렬 테스트 (market, code 순)."""
        items, total_count = symbol_repo.list_filtered()

        assert total_count == 5
        # KOSDAQ이 KOSPI보다 먼저 오고, 같은 market 내에서는 code 순
        # KOSDAQ: 035420, 035720
        # KOSPI: 000660, 005930, 068270
        assert items[0].code == "035420"  # KOSDAQ
        assert items[1].code == "035720"  # KOSDAQ
        assert items[2].code == "000660"  # KOSPI
        assert items[3].code == "005930"  # KOSPI
        assert items[4].code == "068270"  # KOSPI
