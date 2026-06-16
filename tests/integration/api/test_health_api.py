"""Health API 통합 테스트."""

import pytest
from fastapi.testclient import TestClient

from tests.helpers.api_helpers import assert_field_exists, assert_response_success


class TestHealthAPI:
    """Health API 테스트."""

    def test_health_check_success(
        self,
        client: TestClient,
        sample_symbols,
    ):
        """헬스체크 성공."""
        response = client.get("/api/v1/health")
        assert_response_success(response)

        data = response.json()

        # 응답 구조 검증
        assert_field_exists(
            data,
            "status",
            "db_connected",
            "cache",
            "last_batch_at",
            "last_batch_status",
        )

        # DB 연결 상태
        assert data["status"] == "ok"
        assert data["db_connected"] is True

        # 캐시 통계
        assert "cache" in data
        cache = data["cache"]
        assert_field_exists(
            cache,
            "rankings_cache_size",
            "stats_cache_size",
            "stock_detail_cache_size",
            "cache_enabled",
        )

        # 캐시 크기는 0 이상
        assert cache["rankings_cache_size"] >= 0
        assert cache["stats_cache_size"] >= 0
        assert cache["stock_detail_cache_size"] >= 0

        # 캐시 활성화 여부는 boolean
        assert isinstance(cache["cache_enabled"], bool)

    def test_health_check_cache_disabled_in_dev(
        self,
        client: TestClient,
    ):
        """개발 환경에서 캐시 비활성화 확인."""
        response = client.get("/api/v1/health")
        assert_response_success(response)

        data = response.json()

        # 개발 환경(APP_ENV=development)에서는 캐시 비활성화
        # 테스트에서는 기본적으로 development 환경
        cache = data["cache"]
        assert cache["cache_enabled"] is False

    def test_health_check_no_dependencies(
        self,
        client: TestClient,
    ):
        """의존성 없이 헬스체크 호출 가능."""
        # 샘플 데이터 없이도 헬스체크는 동작해야 함
        response = client.get("/api/v1/health")
        assert_response_success(response)

        data = response.json()
        assert "status" in data
        assert "db_connected" in data

    def test_health_check_response_fields(
        self,
        client: TestClient,
    ):
        """헬스체크 응답 필드 타입 검증."""
        response = client.get("/api/v1/health")
        assert_response_success(response)

        data = response.json()

        # status는 문자열
        assert isinstance(data["status"], str)
        assert data["status"] in ["ok", "degraded", "error"]

        # db_connected는 boolean
        assert isinstance(data["db_connected"], bool)

        # cache는 딕셔너리
        assert isinstance(data["cache"], dict)

    def test_health_check_batch_info_when_no_jobs(
        self,
        client: TestClient,
    ):
        """배치 작업 이력이 없을 때 null 확인."""
        response = client.get("/api/v1/health")
        assert_response_success(response)

        data = response.json()

        # 배치 정보 필드 존재 확인
        assert "last_batch_at" in data
        assert "last_batch_status" in data

        # 배치 이력이 없으면 None
        assert data["last_batch_at"] is None
        assert data["last_batch_status"] is None

    def test_health_check_batch_info_with_jobs(
        self,
        client: TestClient,
        sample_crawl_jobs,
    ):
        """배치 작업 이력이 있을 때 정보 확인."""
        response = client.get("/api/v1/health")
        assert_response_success(response)

        data = response.json()

        # 배치 정보 필드 존재 확인
        assert "last_batch_at" in data
        assert "last_batch_status" in data

        # 배치 이력이 있으면 값이 존재
        if sample_crawl_jobs:
            # last_batch_at은 datetime 문자열 또는 None
            # last_batch_status는 문자열 또는 None
            if data["last_batch_at"] is not None:
                assert isinstance(data["last_batch_at"], str)
            if data["last_batch_status"] is not None:
                assert isinstance(data["last_batch_status"], str)
                assert data["last_batch_status"] in ["running", "completed", "failed"]

    def test_health_check_batch_info_types(
        self,
        client: TestClient,
    ):
        """배치 정보 필드 타입 검증."""
        response = client.get("/api/v1/health")
        assert_response_success(response)

        data = response.json()

        # last_batch_at은 문자열 또는 None
        assert data["last_batch_at"] is None or isinstance(data["last_batch_at"], str)

        # last_batch_status는 문자열 또는 None
        assert data["last_batch_status"] is None or isinstance(data["last_batch_status"], str)
