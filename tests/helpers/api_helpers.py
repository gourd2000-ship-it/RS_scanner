"""API 테스트 헬퍼 함수."""

from typing import Any


def assert_response_success(response, expected_status: int = 200):
    """응답이 성공 상태인지 확인."""
    assert response.status_code == expected_status, (
        f"Expected status {expected_status}, got {response.status_code}. "
        f"Response: {response.text}"
    )


def assert_response_error(response, expected_status: int, expected_code: str | None = None):
    """응답이 에러 상태인지 확인."""
    assert response.status_code == expected_status, (
        f"Expected status {expected_status}, got {response.status_code}. "
        f"Response: {response.text}"
    )

    if expected_code:
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == expected_code


def assert_pagination_response(data: dict, expected_total: int | None = None):
    """페이지네이션 응답 구조 검증."""
    assert "total_count" in data
    assert "page" in data
    assert "size" in data
    assert "items" in data
    assert isinstance(data["items"], list)

    if expected_total is not None:
        assert data["total_count"] == expected_total


def assert_field_exists(data: dict, *fields: str):
    """필드가 존재하는지 확인."""
    for field in fields:
        assert field in data, f"Field '{field}' not found in response"


def assert_field_type(data: dict, field: str, expected_type: type):
    """필드 타입이 일치하는지 확인."""
    assert field in data, f"Field '{field}' not found in response"
    assert isinstance(data[field], expected_type), (
        f"Field '{field}' expected type {expected_type}, "
        f"got {type(data[field])}"
    )


def assert_sorted_by(items: list[dict], key: str, reverse: bool = False):
    """리스트가 특정 키로 정렬되어 있는지 확인."""
    values = [item[key] for item in items]
    sorted_values = sorted(values, reverse=reverse)
    assert values == sorted_values, f"Items not sorted by '{key}'"


def assert_unique_values(items: list[dict], key: str):
    """리스트의 특정 키 값이 중복되지 않는지 확인."""
    values = [item[key] for item in items]
    assert len(values) == len(set(values)), f"Duplicate values found in '{key}'"
