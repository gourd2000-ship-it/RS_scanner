"""커스텀 예외 및 에러 핸들러."""

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# 도메인 예외
class CrawlError(Exception):
    """Raised when a crawl operation fails."""


class ParseError(Exception):
    """Raised when HTML parsing fails."""


class PriceParseError(ParseError):
    """Raised when a price response is malformed or contains no valid rows."""

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        invalid_rows: int = 0,
        response_bytes: int | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.invalid_rows = invalid_rows
        self.response_bytes = response_bytes


class PriceFetchError(CrawlError):
    """Raised when a price provider request cannot be completed."""

    def __init__(
        self,
        message: str,
        *,
        url: str,
        http_status: int | None = None,
        retry_count: int = 0,
        response_bytes: int | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.http_status = http_status
        self.retry_count = retry_count
        self.response_bytes = response_bytes


class ValidationError(Exception):
    """Raised when domain validation fails."""


# HTTP 예외
class ResourceNotFoundError(HTTPException):
    """리소스를 찾을 수 없음."""

    def __init__(self, resource_type: str, resource_id: str | int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource_type}을(를) 찾을 수 없습니다: {resource_id}",
        )


class DatabaseError(HTTPException):
    """데이터베이스 오류."""

    def __init__(self, message: str = "데이터베이스 오류가 발생했습니다"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=message,
        )


# 에러 응답 모델
class ErrorDetail(BaseModel):
    """에러 상세 정보."""
    code: str
    message: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    """에러 응답 모델."""
    error: ErrorDetail


# 예외 핸들러
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """HTTP 예외 핸들러."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": exc.detail,
            }
        },
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """요청 검증 예외 핸들러."""
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"][1:])  # 'body' 제외
        errors.append({
            "field": field,
            "message": error["msg"],
            "type": error["type"],
        })

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "요청 데이터 검증에 실패했습니다",
                "details": {"errors": errors},
            }
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """일반 예외 핸들러."""
    import logging

    logger = logging.getLogger(__name__)
    logger.error(f"Unexpected error: {exc}", exc_info=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "서버 내부 오류가 발생했습니다",
            }
        },
    )
