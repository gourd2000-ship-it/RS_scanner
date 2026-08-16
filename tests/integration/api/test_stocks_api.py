"""Stocks API 통합 테스트."""

import pytest
from fastapi.testclient import TestClient

from tests.helpers.api_helpers import (
    assert_field_exists,
    assert_pagination_response,
    assert_response_error,
    assert_response_success,
)


class TestStocksAPI:
    """Stocks API 테스트."""

    def test_list_stocks_success(
        self,
        client: TestClient,
        sample_symbols,
    ):
        """종목 목록 조회 성공."""
        response = client.get("/api/v1/stocks?page=1&size=10")
        assert_response_success(response)

        data = response.json()

        # 페이지네이션 응답 검증
        assert_pagination_response(data)
        assert data["page"] == 1
        assert data["size"] == 10

        # 아이템 구조 검증
        if data["items"]:
            item = data["items"][0]
            assert_field_exists(
                item,
                "code",
                "name",
                "market",
                "sector",
                "industry",
                "is_active",
                "listed_at",
            )

    def test_list_stocks_filter_by_market(
        self,
        client: TestClient,
        sample_symbols,
    ):
        """시장별 필터링 테스트."""
        # KOSPI 종목만
        response = client.get("/api/v1/stocks?market=KOSPI")
        assert_response_success(response)

        data = response.json()

        # 모든 아이템이 KOSPI인지 확인
        for item in data["items"]:
            assert item["market"] == "KOSPI"

        # KOSDAQ 종목만
        response = client.get("/api/v1/stocks?market=KOSDAQ")
        assert_response_success(response)

        data = response.json()

        # 모든 아이템이 KOSDAQ인지 확인
        for item in data["items"]:
            assert item["market"] == "KOSDAQ"

    def test_list_stocks_filter_by_is_active(
        self,
        client: TestClient,
        sample_symbols,
    ):
        """상장 여부 필터링 테스트."""
        # 상장 종목만
        response = client.get("/api/v1/stocks?is_active=true")
        assert_response_success(response)

        data = response.json()

        # 모든 아이템이 is_active=true인지 확인
        for item in data["items"]:
            assert item["is_active"] is True

    def test_list_stocks_search_by_name(
        self,
        client: TestClient,
        sample_symbols,
    ):
        """종목명 검색 테스트."""
        # "삼성" 검색
        response = client.get("/api/v1/stocks?search=삼성")
        assert_response_success(response)

        data = response.json()

        # 검색 결과에 "삼성"이 포함되는지 확인
        for item in data["items"]:
            assert "삼성" in item["name"] or "삼성" in item["code"]

    def test_list_stocks_search_by_code(
        self,
        client: TestClient,
        sample_symbols,
    ):
        """종목코드 검색 테스트."""
        # "0059" 검색 (삼성전자: 005930)
        response = client.get("/api/v1/stocks?search=0059")
        assert_response_success(response)

        data = response.json()

        # 검색 결과 확인
        assert len(data["items"]) >= 1
        # 검색 결과에 005930이 포함되는지 확인
        found = any(item["code"] == "005930" for item in data["items"])
        assert found

    def test_list_stocks_combined_filters(
        self,
        client: TestClient,
        sample_symbols,
    ):
        """복합 필터 테스트."""
        # KOSPI + "삼성" 검색
        response = client.get("/api/v1/stocks?market=KOSPI&search=삼성")
        assert_response_success(response)

        data = response.json()

        # 모든 아이템이 KOSPI이면서 "삼성" 포함
        for item in data["items"]:
            assert item["market"] == "KOSPI"
            assert "삼성" in item["name"] or "삼성" in item["code"]

    def test_list_stocks_pagination(
        self,
        client: TestClient,
        sample_symbols,
    ):
        """페이지네이션 동작 확인."""
        # 첫 페이지
        response1 = client.get("/api/v1/stocks?page=1&size=2")
        assert_response_success(response1)
        data1 = response1.json()

        assert data1["page"] == 1
        assert data1["size"] == 2
        assert len(data1["items"]) <= 2

        # 두 번째 페이지
        response2 = client.get("/api/v1/stocks?page=2&size=2")
        assert_response_success(response2)
        data2 = response2.json()

        assert data2["page"] == 2
        assert data2["size"] == 2

        # 첫 페이지와 두 번째 페이지의 아이템이 다른지 확인
        if data1["items"] and data2["items"]:
            assert data1["items"][0]["code"] != data2["items"][0]["code"]

    def test_list_stocks_max_size_limit(
        self,
        client: TestClient,
        sample_symbols,
    ):
        """size 파라미터 최대값 제한 확인."""
        # 최대값 500
        response = client.get("/api/v1/stocks?size=500")
        assert_response_success(response)

        # 최대값 초과 시 422 에러
        response = client.get("/api/v1/stocks?size=501")
        assert_response_error(response, 422, "VALIDATION_ERROR")

    def test_list_stocks_invalid_market(self, client: TestClient):
        """잘못된 market 파라미터로 요청 시 422 에러."""
        response = client.get("/api/v1/stocks?market=INVALID")
        assert_response_error(response, 422, "VALIDATION_ERROR")

    def test_get_stock_detail_success(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """종목 상세 조회 성공."""
        code = "005930"
        response = client.get(f"/api/v1/stocks/{code}")
        assert_response_success(response)

        data = response.json()

        # 응답 구조 검증
        assert_field_exists(data, "symbol", "latest_price", "latest_rs", "benchmark_name")

        # Symbol 정보
        assert data["symbol"]["code"] == code
        assert data["symbol"]["name"] == "삼성전자"
        assert data["symbol"]["market"] == "KOSPI"

        # 최신 가격 정보
        assert data["latest_price"] is not None
        assert_field_exists(
            data["latest_price"],
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "change_rate",
        )

        # 최신 RS 정보
        assert data["latest_rs"] is not None
        assert_field_exists(
            data["latest_rs"],
            "trade_date",
            "rs_rating",
            "rank_in_market",
            "return_1m",
            "return_3m",
            "return_6m",
            "return_9m",
            "return_12m",
            "relative_return_score",
            "rs_percentile",
        )

        # 벤치마크
        assert data["benchmark_name"] == "KOSPI"

    def test_get_stock_detail_not_found(self, client: TestClient):
        """존재하지 않는 종목 조회 시 404 에러."""
        response = client.get("/api/v1/stocks/999999")
        assert_response_error(response, 404, "HTTP_404")

    def test_get_stock_detail_no_price(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
    ):
        """가격 데이터가 없는 종목."""
        code = "005930"
        response = client.get(f"/api/v1/stocks/{code}")
        assert_response_success(response)

        data = response.json()

        # Symbol 정보는 존재
        assert data["symbol"]["code"] == code

        # 가격과 RS 정보는 None
        assert data["latest_price"] is None
        assert data["latest_rs"] is None

    def test_get_rs_history_success(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """RS 이력 조회 성공."""
        code = "005930"
        response = client.get(f"/api/v1/stocks/{code}/rs-history?limit=10")
        assert_response_success(response)

        data = response.json()

        # 응답 구조 검증
        assert_field_exists(data, "code", "name", "market", "rs_scores")
        assert data["code"] == code
        assert data["name"] == "삼성전자"
        assert data["market"] == "KOSPI"

        # RS 점수 목록
        assert isinstance(data["rs_scores"], list)
        assert len(data["rs_scores"]) >= 0

        # RS 점수 아이템 구조 검증
        if data["rs_scores"]:
            rs_item = data["rs_scores"][0]
            assert_field_exists(
                rs_item,
                "trade_date",
                "rs_rating",
                "rank_in_market",
                "return_1m",
                "return_3m",
                "return_6m",
                "return_9m",
                "return_12m",
                "relative_return_score",
                "rs_percentile",
            )

    def test_get_rs_history_limit_param(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
        sample_rs_scores,
    ):
        """limit 파라미터 동작 확인."""
        code = "005930"

        # limit=5
        response = client.get(f"/api/v1/stocks/{code}/rs-history?limit=5")
        assert_response_success(response)
        data = response.json()
        assert len(data["rs_scores"]) <= 5

    def test_get_rs_history_max_limit(self, client: TestClient, sample_symbols):
        """limit 최대값 검증."""
        code = "005930"

        # 최대값 365
        response = client.get(f"/api/v1/stocks/{code}/rs-history?limit=365")
        assert_response_success(response)

        # 최대값 초과 시 422 에러
        response = client.get(f"/api/v1/stocks/{code}/rs-history?limit=366")
        assert_response_error(response, 422, "VALIDATION_ERROR")

    def test_get_rs_history_not_found(self, client: TestClient):
        """존재하지 않는 종목의 RS 이력 조회."""
        response = client.get("/api/v1/stocks/999999/rs-history")
        assert_response_error(response, 404, "HTTP_404")

    def test_get_price_history_success(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
    ):
        """가격 데이터 조회 성공."""
        code = "005930"
        response = client.get(f"/api/v1/stocks/{code}/prices?page=1&size=10")
        assert_response_success(response)

        data = response.json()

        # 페이지네이션 응답 검증
        assert_pagination_response(data)
        assert data["page"] == 1
        assert data["size"] == 10

        # 가격 데이터 아이템 검증
        if data["items"]:
            price_item = data["items"][0]
            assert_field_exists(
                price_item,
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "change_rate",
            )

    def test_get_price_history_pagination(
        self,
        client: TestClient,
        sample_symbols,
        sample_benchmarks,
        sample_prices,
    ):
        """가격 데이터 페이지네이션."""
        code = "005930"

        # 첫 페이지
        response1 = client.get(f"/api/v1/stocks/{code}/prices?page=1&size=5")
        assert_response_success(response1)
        data1 = response1.json()
        assert len(data1["items"]) <= 5

        # 두 번째 페이지
        response2 = client.get(f"/api/v1/stocks/{code}/prices?page=2&size=5")
        assert_response_success(response2)
        data2 = response2.json()

        # 페이지가 다르면 데이터도 달라야 함
        if data1["items"] and data2["items"]:
            assert data1["items"][0]["trade_date"] != data2["items"][0]["trade_date"]

    def test_get_price_history_max_size(self, client: TestClient, sample_symbols):
        """size 최대값 검증."""
        code = "005930"

        # 최대값 500
        response = client.get(f"/api/v1/stocks/{code}/prices?size=500")
        assert_response_success(response)

        # 최대값 초과 시 422 에러
        response = client.get(f"/api/v1/stocks/{code}/prices?size=501")
        assert_response_error(response, 422, "VALIDATION_ERROR")

    def test_get_price_history_not_found(self, client: TestClient):
        """존재하지 않는 종목의 가격 데이터 조회."""
        response = client.get("/api/v1/stocks/999999/prices")
        assert_response_error(response, 404, "HTTP_404")
