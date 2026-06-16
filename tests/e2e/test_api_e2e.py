"""API 엔드포인트 E2E 테스트 (PostgreSQL)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload, SymbolPayload
from app.services.batch.context import BatchContext
from app.services.batch.run_daily_job import run_daily_job
from tests.harness.fake_source import FakePriceSource


def make_prices(start_close: int, step: int, days: int = 260):
    """테스트용 가격 데이터 생성."""
    start = date(2025, 1, 1)
    return [
        DailyPricePayload(
            trade_date=start + timedelta(days=index),
            open=Decimal(start_close + step * index),
            high=Decimal(start_close + step * index),
            low=Decimal(start_close + step * index),
            close=Decimal(start_close + step * index),
            volume=1000,
            change_rate=Decimal("0"),
        )
        for index in range(days)
    ]


def make_benchmark(market: str, days: int = 260):
    """테스트용 벤치마크 데이터 생성."""
    start = date(2025, 1, 1)
    benchmark_code = "KOSPI_INDEX" if market == "KOSPI" else "KOSDAQ_INDEX"
    return [
        BenchmarkPricePayload(
            benchmark_code=benchmark_code,
            market=market,
            trade_date=start + timedelta(days=index),
            open=Decimal(100 + index),
            high=Decimal(100 + index),
            low=Decimal(100 + index),
            close=Decimal(100 + index),
            volume=None,
            change_rate=Decimal("0"),
        )
        for index in range(days)
    ]


@pytest.fixture
def setup_batch_data(e2e_batch_context: BatchContext, e2e_session: Session):
    """배치 데이터 준비 픽스처."""
    symbols = [
        SymbolPayload(code="005930", name="삼성전자", market="KOSPI"),
        SymbolPayload(code="000660", name="SK하이닉스", market="KOSPI"),
        SymbolPayload(code="035720", name="카카오", market="KOSDAQ"),
        SymbolPayload(code="086520", name="에코프로", market="KOSDAQ"),
    ]
    source = FakePriceSource(
        symbols=symbols,
        prices_by_code={
            "005930": make_prices(70000, 500, 260),  # 강한 상승
            "000660": make_prices(130000, 200, 260),  # 중간 상승
            "035720": make_prices(50000, 300, 260),  # 중간 상승
            "086520": make_prices(100000, 100, 260),  # 약한 상승
        },
        benchmark_prices_by_market={
            "KOSPI": make_benchmark("KOSPI", 260),
            "KOSDAQ": make_benchmark("KOSDAQ", 260),
        },
    )

    # 배치 실행
    result = run_daily_job(e2e_batch_context, source)
    e2e_session.commit()  # 명시적 커밋

    return result


@pytest.mark.e2e
def test_health_endpoint_e2e(e2e_client: TestClient, setup_batch_data):
    """Health 엔드포인트 E2E 테스트."""
    # When: health check 호출
    response = e2e_client.get("/api/v1/health")

    # Then: 정상 응답
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert data["db_connected"] is True
    assert "last_batch_at" in data
    assert data["last_batch_status"] == "completed"


@pytest.mark.e2e
def test_rankings_api_e2e(e2e_client: TestClient, setup_batch_data):
    """Rankings API E2E 테스트."""
    # When: KOSPI 랭킹 조회
    response = e2e_client.get("/api/v1/rankings/rs?market=KOSPI")

    # Then: 정상 응답 및 데이터 검증
    assert response.status_code == 200
    data = response.json()

    assert data["market"] == "KOSPI"
    assert data["total_count"] == 2
    assert len(data["items"]) == 2

    # RS Rating 순으로 정렬되어야 함
    items = data["items"]
    assert items[0]["rs_rating"] >= items[1]["rs_rating"]

    # 종목 정보 포함 확인
    assert "code" in items[0]
    assert "name" in items[0]
    assert "close" in items[0]
    assert "change_rate" in items[0]


@pytest.mark.e2e
def test_rankings_filtering_e2e(e2e_client: TestClient, setup_batch_data):
    """Rankings 필터링 E2E 테스트."""
    # When: RS Rating 90 이상 필터링
    response = e2e_client.get("/api/v1/rankings/rs?market=KOSPI&min_rs=90")

    # Then: 필터링된 결과
    assert response.status_code == 200
    data = response.json()

    for item in data["items"]:
        assert item["rs_rating"] >= 90


@pytest.mark.e2e
def test_rankings_sorting_e2e(e2e_client: TestClient, setup_batch_data):
    """Rankings 정렬 E2E 테스트."""
    # When: return_3m 기준 내림차순 정렬
    response = e2e_client.get("/api/v1/rankings/rs?market=KOSPI&sort_by=return_3m&order=desc")

    # Then: 정렬 확인
    assert response.status_code == 200
    data = response.json()

    items = data["items"]
    if len(items) >= 2:
        assert float(items[0]["return_3m"]) >= float(items[1]["return_3m"])


@pytest.mark.e2e
def test_rankings_pagination_e2e(e2e_client: TestClient, setup_batch_data):
    """Rankings 페이지네이션 E2E 테스트."""
    # When: 페이지 크기 1로 조회
    response = e2e_client.get("/api/v1/rankings/rs?market=KOSPI&page=1&size=1")

    # Then: 페이지네이션 확인
    assert response.status_code == 200
    data = response.json()

    assert data["total_count"] == 2
    assert len(data["items"]) == 1
    assert data["page"] == 1
    assert data["size"] == 1


@pytest.mark.e2e
def test_stocks_list_api_e2e(e2e_client: TestClient, setup_batch_data):
    """종목 목록 API E2E 테스트."""
    # When: 전체 종목 조회
    response = e2e_client.get("/api/v1/stocks")

    # Then: 정상 응답
    assert response.status_code == 200
    data = response.json()

    assert data["total_count"] == 4
    assert len(data["items"]) == 4


@pytest.mark.e2e
def test_stocks_list_market_filter_e2e(e2e_client: TestClient, setup_batch_data):
    """종목 목록 시장별 필터링 E2E 테스트."""
    # When: KOSDAQ 종목만 조회
    response = e2e_client.get("/api/v1/stocks?market=KOSDAQ")

    # Then: KOSDAQ 종목만 반환
    assert response.status_code == 200
    data = response.json()

    assert data["total_count"] == 2
    for item in data["items"]:
        assert item["market"] == "KOSDAQ"


@pytest.mark.e2e
def test_stocks_list_search_e2e(e2e_client: TestClient, setup_batch_data):
    """종목 목록 검색 E2E 테스트."""
    # When: "삼성" 검색
    response = e2e_client.get("/api/v1/stocks?search=삼성")

    # Then: 삼성전자만 반환
    assert response.status_code == 200
    data = response.json()

    assert data["total_count"] == 1
    assert data["items"][0]["code"] == "005930"


@pytest.mark.e2e
def test_stock_detail_api_e2e(e2e_client: TestClient, setup_batch_data):
    """종목 상세 API E2E 테스트."""
    # When: 삼성전자 상세 조회
    response = e2e_client.get("/api/v1/stocks/005930")

    # Then: 정상 응답 및 상세 데이터 검증
    assert response.status_code == 200
    data = response.json()

    # SymbolDetailResponse 구조: symbol, latest_price, latest_rs, benchmark_name
    assert "symbol" in data
    assert data["symbol"]["code"] == "005930"
    assert data["symbol"]["name"] == "삼성전자"
    assert data["symbol"]["market"] == "KOSPI"

    # 최신 가격 정보
    assert "latest_price" in data
    assert data["latest_price"] is not None
    assert "close" in data["latest_price"]

    # 최신 RS 정보
    assert "latest_rs" in data
    assert data["latest_rs"] is not None
    assert "rs_rating" in data["latest_rs"]


@pytest.mark.e2e
def test_stock_prices_history_e2e(e2e_client: TestClient, setup_batch_data):
    """종목 가격 이력 API E2E 테스트."""
    # When: 삼성전자 가격 이력 조회
    response = e2e_client.get("/api/v1/stocks/005930/prices")

    # Then: 정상 응답 및 데이터 검증
    assert response.status_code == 200
    data = response.json()

    # PaginatedResponse 구조: total_count, page, size, items
    assert "total_count" in data
    assert "items" in data
    assert len(data["items"]) > 0
    assert data["total_count"] > 0

    # 가격 데이터 필드 확인
    item = data["items"][0]
    assert "trade_date" in item
    assert "open" in item
    assert "high" in item
    assert "low" in item
    assert "close" in item
    assert "volume" in item


@pytest.mark.e2e
def test_stock_prices_date_range_e2e(e2e_client: TestClient, setup_batch_data):
    """종목 가격 이력 페이지네이션 E2E 테스트."""
    # When: 첫 페이지 조회 (size=10)
    response = e2e_client.get("/api/v1/stocks/005930/prices?page=1&size=10")

    # Then: 페이지네이션 확인
    assert response.status_code == 200
    data = response.json()

    assert data["page"] == 1
    assert data["size"] == 10
    assert len(data["items"]) <= 10
    assert data["total_count"] > 0


@pytest.mark.e2e
def test_stock_rs_history_e2e(e2e_client: TestClient, setup_batch_data):
    """종목 RS 이력 API E2E 테스트."""
    # When: 삼성전자 RS 이력 조회 (올바른 URL: /rs-history)
    response = e2e_client.get("/api/v1/stocks/005930/rs-history")

    # Then: 정상 응답 및 데이터 검증
    assert response.status_code == 200
    data = response.json()

    # RsSeriesResponse 구조: code, name, market, rs_scores
    assert data["code"] == "005930"
    assert data["name"] == "삼성전자"
    assert "rs_scores" in data
    assert len(data["rs_scores"]) > 0

    # RS 데이터 필드 확인
    item = data["rs_scores"][0]
    assert "trade_date" in item
    assert "rs_rating" in item
    assert "return_3m" in item
    assert "return_6m" in item
    assert "return_9m" in item
    assert "return_12m" in item


@pytest.mark.e2e
def test_crawl_stats_api_e2e(e2e_client: TestClient, setup_batch_data):
    """크롤링 통계 API E2E 테스트."""
    # When: 크롤링 통계 조회
    response = e2e_client.get("/api/v1/crawl/stats")

    # Then: 정상 응답
    assert response.status_code == 200
    data = response.json()

    assert "total_jobs" in data
    assert data["total_jobs"] >= 1
    assert "completed_jobs" in data
    assert "running_jobs" in data
    assert "failed_jobs" in data


@pytest.mark.e2e
def test_full_workflow_e2e(e2e_client: TestClient, e2e_batch_context: BatchContext, e2e_session: Session):
    """전체 워크플로우 E2E 테스트 (배치 → API 조회)."""
    # Given: 테스트 데이터 준비
    symbols = [
        SymbolPayload(code="TEST01", name="테스트1", market="KOSPI"),
        SymbolPayload(code="TEST02", name="테스트2", market="KOSPI"),
    ]
    source = FakePriceSource(
        symbols=symbols,
        prices_by_code={
            "TEST01": make_prices(10000, 100, 260),
            "TEST02": make_prices(20000, 50, 260),
        },
        benchmark_prices_by_market={
            "KOSPI": make_benchmark("KOSPI", 260),
            "KOSDAQ": make_benchmark("KOSDAQ", 260),
        },
    )

    # When: 1. 배치 실행
    batch_result = run_daily_job(e2e_batch_context, source)
    e2e_session.commit()

    assert batch_result["symbols"] == 2
    assert batch_result["rs_results"]["KOSPI"] == 2

    # When: 2. Rankings API 조회
    rankings_response = e2e_client.get("/api/v1/rankings/rs?market=KOSPI")
    assert rankings_response.status_code == 200
    rankings_data = rankings_response.json()

    # Then: 배치 결과가 API에 반영됨
    test_codes = {item["code"] for item in rankings_data["items"] if item["code"].startswith("TEST")}
    assert "TEST01" in test_codes
    assert "TEST02" in test_codes

    # When: 3. 종목 상세 조회
    detail_response = e2e_client.get("/api/v1/stocks/TEST01")
    assert detail_response.status_code == 200
    detail_data = detail_response.json()

    # Then: 종목 상세 정보 확인
    assert detail_data["symbol"]["code"] == "TEST01"
    assert detail_data["symbol"]["name"] == "테스트1"
    assert detail_data["latest_price"] is not None
    assert detail_data["latest_rs"] is not None

    # When: 4. 가격 이력 조회
    prices_response = e2e_client.get("/api/v1/stocks/TEST01/prices")
    assert prices_response.status_code == 200
    prices_data = prices_response.json()

    # Then: 가격 데이터 확인
    assert prices_data["total_count"] == 260
    assert len(prices_data["items"]) <= 100  # 기본 size=100

    # When: 5. RS 이력 조회
    rs_response = e2e_client.get("/api/v1/stocks/TEST01/rs-history")
    assert rs_response.status_code == 200
    rs_data = rs_response.json()

    # Then: RS 데이터 확인
    assert len(rs_data["rs_scores"]) >= 1
