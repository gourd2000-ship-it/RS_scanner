"""Crawl API 통합 테스트."""

import pytest
from fastapi.testclient import TestClient

from tests.helpers.api_helpers import (
    assert_field_exists,
    assert_pagination_response,
    assert_response_error,
    assert_response_success,
)


class TestCrawlAPI:
    """Crawl 모니터링 API 테스트."""

    def test_get_crawl_stats_success(
        self,
        client: TestClient,
        sample_crawl_jobs,
        sample_crawl_failures,
    ):
        """크롤링 통계 조회 성공."""
        response = client.get("/api/v1/crawl/stats")
        assert_response_success(response)

        data = response.json()

        # 응답 구조 검증
        assert_field_exists(
            data,
            "total_jobs",
            "running_jobs",
            "completed_jobs",
            "failed_jobs",
            "total_failures",
            "latest_job",
        )

        # 통계 값 검증
        assert data["total_jobs"] == 2
        assert data["running_jobs"] == 1
        assert data["completed_jobs"] == 1
        assert data["failed_jobs"] == 0
        assert data["total_failures"] == 1

        # 최근 작업 정보
        if data["latest_job"]:
            assert_field_exists(
                data["latest_job"],
                "id",
                "job_type",
                "started_at",
                "status",
                "symbols_total",
                "symbols_succeeded",
                "symbols_failed",
            )

    def test_get_crawl_stats_empty(self, client: TestClient):
        """크롤링 데이터가 없는 경우."""
        response = client.get("/api/v1/crawl/stats")
        assert_response_success(response)

        data = response.json()

        assert data["total_jobs"] == 0
        assert data["running_jobs"] == 0
        assert data["completed_jobs"] == 0
        assert data["failed_jobs"] == 0
        assert data["total_failures"] == 0
        assert data["latest_job"] is None

    def test_list_crawl_jobs_success(
        self,
        client: TestClient,
        sample_crawl_jobs,
    ):
        """크롤링 작업 목록 조회 성공."""
        response = client.get("/api/v1/crawl/jobs?page=1&size=10")
        assert_response_success(response)

        data = response.json()

        # 페이지네이션 응답 검증
        assert_pagination_response(data, expected_total=2)
        assert len(data["items"]) == 2

        # 작업 아이템 구조 검증
        job_item = data["items"][0]
        assert_field_exists(
            job_item,
            "id",
            "job_type",
            "started_at",
            "finished_at",
            "status",
            "symbols_total",
            "symbols_succeeded",
            "symbols_failed",
            "message",
            "duration_seconds",
            "success_rate",
        )

    def test_list_crawl_jobs_status_filter(
        self,
        client: TestClient,
        sample_crawl_jobs,
    ):
        """status 필터 동작 확인."""
        # 완료된 작업만 조회
        response = client.get("/api/v1/crawl/jobs?status=completed")
        assert_response_success(response)

        data = response.json()
        assert data["total_count"] == 1
        assert all(item["status"] == "completed" for item in data["items"])

        # 실행 중인 작업만 조회
        response = client.get("/api/v1/crawl/jobs?status=running")
        assert_response_success(response)

        data = response.json()
        assert data["total_count"] == 1
        assert all(item["status"] == "running" for item in data["items"])

    def test_list_crawl_jobs_pagination(
        self,
        client: TestClient,
        sample_crawl_jobs,
    ):
        """페이지네이션 동작 확인."""
        # 첫 페이지
        response1 = client.get("/api/v1/crawl/jobs?page=1&size=1")
        assert_response_success(response1)
        data1 = response1.json()
        assert len(data1["items"]) == 1

        # 두 번째 페이지
        response2 = client.get("/api/v1/crawl/jobs?page=2&size=1")
        assert_response_success(response2)
        data2 = response2.json()
        assert len(data2["items"]) == 1

        # 다른 작업인지 확인
        assert data1["items"][0]["id"] != data2["items"][0]["id"]

    def test_get_crawl_job_success(
        self,
        client: TestClient,
        sample_crawl_jobs,
    ):
        """특정 크롤링 작업 상세 조회 성공."""
        job_id = sample_crawl_jobs[0].id
        response = client.get(f"/api/v1/crawl/jobs/{job_id}")
        assert_response_success(response)

        data = response.json()

        # 작업 정보 검증
        assert data["id"] == job_id
        assert data["status"] == "completed"
        assert data["symbols_total"] == 100
        assert data["symbols_succeeded"] == 98
        assert data["symbols_failed"] == 2

        # duration_seconds 계산 검증
        assert data["duration_seconds"] is not None
        assert data["duration_seconds"] > 0

        # success_rate 계산 검증
        assert data["success_rate"] is not None
        assert data["success_rate"] == 98.0  # 98/100 * 100

    def test_get_crawl_job_not_found(self, client: TestClient):
        """존재하지 않는 작업 조회 시 404 에러."""
        response = client.get("/api/v1/crawl/jobs/99999")
        assert_response_error(response, 404, "HTTP_404")

    def test_get_crawl_job_running(
        self,
        client: TestClient,
        sample_crawl_jobs,
    ):
        """실행 중인 작업 조회."""
        job_id = sample_crawl_jobs[1].id  # running 상태
        response = client.get(f"/api/v1/crawl/jobs/{job_id}")
        assert_response_success(response)

        data = response.json()

        assert data["status"] == "running"
        assert data["finished_at"] is None
        # 실행 중인 작업은 duration_seconds가 None
        assert data["duration_seconds"] is None

    def test_list_crawl_failures_success(
        self,
        client: TestClient,
        sample_crawl_jobs,
        sample_crawl_failures,
    ):
        """크롤링 실패 목록 조회 성공."""
        response = client.get("/api/v1/crawl/failures?page=1&size=50")
        assert_response_success(response)

        data = response.json()

        # 페이지네이션 응답 검증
        assert_pagination_response(data, expected_total=1)
        assert len(data["items"]) == 1

        # 실패 아이템 구조 검증
        failure_item = data["items"][0]
        assert_field_exists(
            failure_item,
            "id",
            "job_id",
            "target_type",
            "target_key",
            "url",
            "http_status",
            "error_class",
            "error_message",
            "retry_count",
            "created_at",
        )

        assert failure_item["target_type"] == "symbol"
        assert failure_item["target_key"] == "999999"
        assert failure_item["http_status"] == 404
        assert failure_item["error_class"] == "HTTPError"

    def test_list_crawl_failures_job_id_filter(
        self,
        client: TestClient,
        sample_crawl_jobs,
        sample_crawl_failures,
    ):
        """job_id 필터 동작 확인."""
        job_id = sample_crawl_jobs[0].id
        response = client.get(f"/api/v1/crawl/failures?job_id={job_id}")
        assert_response_success(response)

        data = response.json()
        assert data["total_count"] == 1
        assert all(item["job_id"] == job_id for item in data["items"])

    def test_list_crawl_failures_empty(self, client: TestClient, sample_crawl_jobs):
        """실패가 없는 경우."""
        response = client.get("/api/v1/crawl/failures")
        assert_response_success(response)

        data = response.json()
        assert data["total_count"] == 0
        assert len(data["items"]) == 0

    def test_crawl_stats_success_rate_calculation(
        self,
        client: TestClient,
        sample_crawl_jobs,
    ):
        """success_rate 계산 검증."""
        response = client.get("/api/v1/crawl/stats")
        assert_response_success(response)

        data = response.json()

        if data["latest_job"]:
            job = data["latest_job"]
            # 수동 계산
            expected_rate = (job["symbols_succeeded"] / job["symbols_total"]) * 100
            assert job["success_rate"] == expected_rate
