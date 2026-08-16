"""Rankings API 통합 테스트."""

import pytest
from fastapi.testclient import TestClient

from tests.helpers.api_helpers import (
    assert_field_exists,
    assert_pagination_response,
    assert_response_error,
    assert_response_success,
    assert_sorted_by,
)


class TestRankingsAPI:
    """Rankings API 테스트."""

    def test_get_kospi_rankings_success(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """KOSPI 랭킹 조회 성공."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI&page=1&size=10")
        assert_response_success(response)

        data = response.json()

        # 응답 구조 검증
        assert data["market"] == "KOSPI"
        assert data["trade_date"] == "2024-05-28"
        assert_pagination_response(data)

        # KOSPI 종목만 반환되는지 확인
        kospi_count = len([s for s in sample_symbols.values() if s.market == "KOSPI"])
        assert data["total_count"] == kospi_count
        assert len(data["items"]) == kospi_count

        # 첫 번째 아이템 구조 검증
        if data["items"]:
            item = data["items"][0]
            assert_field_exists(
                item,
                "code",
                "name",
                "market",
                "trade_date",
                "rs_rating",
                "rank_in_market",
                "return_1m",
                "return_3m",
                "return_6m",
                "return_9m",
                "return_12m",
                "relative_return_score",
                "close",
                "change_rate",
            )
            assert item["market"] == "KOSPI"

        # rank_in_market 오름차순 정렬 확인
        assert_sorted_by(data["items"], "rank_in_market")

    def test_get_kosdaq_rankings_success(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """KOSDAQ 랭킹 조회 성공."""
        response = client.get("/api/v1/rankings/rs?market=KOSDAQ")
        assert_response_success(response)

        data = response.json()

        # KOSDAQ 종목만 반환되는지 확인
        kosdaq_count = len([s for s in sample_symbols.values() if s.market == "KOSDAQ"])
        assert data["total_count"] == kosdaq_count
        assert data["market"] == "KOSDAQ"

        # 모든 아이템이 KOSDAQ인지 확인
        for item in data["items"]:
            assert item["market"] == "KOSDAQ"

    def test_rankings_pagination(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """페이지네이션 동작 확인."""
        # 첫 페이지
        response1 = client.get("/api/v1/rankings/rs?market=KOSPI&page=1&size=2")
        assert_response_success(response1)
        data1 = response1.json()

        assert data1["page"] == 1
        assert data1["size"] == 2
        assert len(data1["items"]) <= 2

        # 두 번째 페이지
        response2 = client.get("/api/v1/rankings/rs?market=KOSPI&page=2&size=2")
        assert_response_success(response2)
        data2 = response2.json()

        assert data2["page"] == 2
        assert data2["size"] == 2

        # 첫 페이지와 두 번째 페이지의 아이템이 다른지 확인
        if data1["items"] and data2["items"]:
            assert data1["items"][0]["code"] != data2["items"][0]["code"]

    def test_rankings_invalid_market(self, client: TestClient):
        """잘못된 market 파라미터로 요청 시 422 에러."""
        response = client.get("/api/v1/rankings/rs?market=INVALID")
        assert_response_error(response, 422, "VALIDATION_ERROR")

    def test_rankings_missing_market_param(self, client: TestClient):
        """market 파라미터 누락 시 422 에러."""
        response = client.get("/api/v1/rankings/rs")
        assert_response_error(response, 422, "VALIDATION_ERROR")

    def test_rankings_empty_data(self, client: TestClient, sample_symbols, sample_benchmarks):
        """RS 데이터가 없는 경우."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI")
        assert_response_success(response)

        data = response.json()
        assert data["total_count"] == 0
        assert data["trade_date"] is None
        assert len(data["items"]) == 0

    def test_rankings_include_price_info(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """랭킹 응답에 가격 정보가 포함되는지 확인."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI")
        assert_response_success(response)

        data = response.json()

        if data["items"]:
            item = data["items"][0]
            # 가격 정보 존재 확인
            assert "close" in item
            assert "change_rate" in item
            # 가격이 숫자 형태로 반환되는지 확인
            assert isinstance(item["close"], str)  # Decimal은 JSON에서 문자열로 직렬화
            assert isinstance(item["change_rate"], str)

    def test_rankings_include_symbol_name(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """랭킹 응답에 종목명이 포함되는지 확인."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI")
        assert_response_success(response)

        data = response.json()

        if data["items"]:
            item = data["items"][0]
            # 종목명 존재 확인
            assert "name" in item
            assert isinstance(item["name"], str)
            assert len(item["name"]) > 0

    def test_rankings_max_size_limit(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """size 파라미터 최대값 제한 확인."""
        # 최대값 500
        response = client.get("/api/v1/rankings/rs?market=KOSPI&size=500")
        assert_response_success(response)

        # 최대값 초과 시 422 에러
        response = client.get("/api/v1/rankings/rs?market=KOSPI&size=501")
        assert_response_error(response, 422, "VALIDATION_ERROR")

    def test_rankings_min_page_validation(self, client: TestClient):
        """page 파라미터 최소값 검증."""
        # page는 1 이상이어야 함
        response = client.get("/api/v1/rankings/rs?market=KOSPI&page=0")
        assert_response_error(response, 422, "VALIDATION_ERROR")

        response = client.get("/api/v1/rankings/rs?market=KOSPI&page=-1")
        assert_response_error(response, 422, "VALIDATION_ERROR")

    def test_filter_by_min_rs(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """min_rs 필터링 테스트."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI&min_rs=90")
        assert_response_success(response)

        data = response.json()

        # 모든 아이템의 rs_rating이 90 이상인지 확인
        for item in data["items"]:
            assert item["rs_rating"] >= 90

    def test_filter_by_max_rs(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """max_rs 필터링 테스트."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI&max_rs=50")
        assert_response_success(response)

        data = response.json()

        # 모든 아이템의 rs_rating이 50 이하인지 확인
        for item in data["items"]:
            assert item["rs_rating"] <= 50

    def test_filter_by_rs_range(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """min_rs와 max_rs 범위 필터링 테스트."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI&min_rs=30&max_rs=70")
        assert_response_success(response)

        data = response.json()

        # 모든 아이템의 rs_rating이 30~70 범위인지 확인
        for item in data["items"]:
            assert 30 <= item["rs_rating"] <= 70

    def test_filter_invalid_rs_range(self, client: TestClient):
        """min_rs > max_rs인 경우 400 에러."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI&min_rs=80&max_rs=20")
        assert_response_error(response, 400)

    def test_sort_by_rs_rating_desc(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """rs_rating 기준 내림차순 정렬 테스트."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI&sort_by=rs_rating&order=desc")
        assert_response_success(response)

        data = response.json()

        # rs_rating 내림차순 정렬 확인
        if len(data["items"]) > 1:
            for i in range(len(data["items"]) - 1):
                assert data["items"][i]["rs_rating"] >= data["items"][i + 1]["rs_rating"]

    def test_sort_by_return_3m_desc(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """return_3m 기준 내림차순 정렬 테스트."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI&sort_by=return_3m&order=desc")
        assert_response_success(response)

        data = response.json()

        # return_3m 내림차순 정렬 확인
        if len(data["items"]) > 1:
            for i in range(len(data["items"]) - 1):
                current = float(data["items"][i]["return_3m"])
                next_item = float(data["items"][i + 1]["return_3m"])
                assert current >= next_item

    def test_sort_by_return_1m_desc(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """return_1m 기준 내림차순 정렬 테스트."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI&sort_by=return_1m&order=desc")
        assert_response_success(response)

        items = response.json()["items"]
        for index in range(len(items) - 1):
            assert float(items[index]["return_1m"]) >= float(items[index + 1]["return_1m"])

    def test_sort_by_rank_in_market_asc(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """rank_in_market 기준 오름차순 정렬 테스트 (기본값)."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI")
        assert_response_success(response)

        data = response.json()

        # rank_in_market 오름차순 정렬 확인 (기본 동작)
        assert_sorted_by(data["items"], "rank_in_market")

    def test_sort_invalid_field(self, client: TestClient):
        """유효하지 않은 정렬 기준으로 요청 시 422 에러."""
        response = client.get("/api/v1/rankings/rs?market=KOSPI&sort_by=invalid_field")
        assert_response_error(response, 422, "VALIDATION_ERROR")

    def test_combined_filter_and_sort(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """필터와 정렬 동시 적용 테스트."""
        response = client.get(
            "/api/v1/rankings/rs?market=KOSPI&min_rs=50&sort_by=return_3m&order=desc"
        )
        assert_response_success(response)

        data = response.json()

        # 필터 조건 확인 (rs_rating >= 50)
        for item in data["items"]:
            assert item["rs_rating"] >= 50

        # 정렬 확인 (return_3m 내림차순)
        if len(data["items"]) > 1:
            for i in range(len(data["items"]) - 1):
                current = float(data["items"][i]["return_3m"])
                next_item = float(data["items"][i + 1]["return_3m"])
                assert current >= next_item
