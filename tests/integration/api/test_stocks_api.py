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
