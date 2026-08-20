from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.v1.endpoints.agent import router as agent_router
from app.api.v1.endpoints.analysis import router as analysis_router
from app.api.v1.endpoints.crawl import router as crawl_router
from app.api.v1.endpoints.codex import router as codex_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.repair import router as repair_router
from app.api.v1.endpoints.rankings import router as rankings_router
from app.api.v1.endpoints.stocks import router as stocks_router
from app.core.database import init_db
from app.core.metrics import increment_metric
from app.core.exceptions import (
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.core.logging import configure_logging
from app.core.rate_limit import RateLimitMiddleware
from uuid import uuid4


configure_logging()
init_db()

# API 메타데이터
description = """
## RS Scanner API

IBD 스타일의 상대 강도(Relative Strength) 스캐너 API입니다.

KOSPI와 KOSDAQ 종목의 상대 강도를 계산하고, 랭킹을 제공합니다.

### 주요 기능

* **종목 조회**: 종목 상세 정보, 가격 데이터, RS 이력 조회
* **RS 랭킹**: 시장별 상대 강도 랭킹 제공
* **크롤링 모니터링**: 데이터 수집 작업 모니터링

### RS Rating 이란?

RS Rating은 IBD(Investor's Business Daily) 스타일의 상대 강도 지표입니다.

- **범위**: 1~99 (높을수록 강함)
- **계산**: 3M, 6M, 9M, 12M 수익률 가중 평균
- **기준**: 같은 시장(KOSPI/KOSDAQ) 내 백분위
"""

tags_metadata = [
    {
        "name": "health",
        "description": "서비스 상태 확인",
    },
    {
        "name": "stocks",
        "description": "종목 상세 정보 조회. 종목 코드로 기본 정보, 가격, RS 점수를 조회합니다.",
    },
    {
        "name": "rankings",
        "description": "RS 랭킹 조회. KOSPI/KOSDAQ 시장별 상대 강도 순위를 제공합니다.",
    },
    {
        "name": "crawl",
        "description": "크롤링 모니터링. 네이버 금융에서 데이터를 수집하는 배치 작업의 상태를 모니터링합니다.",
    },
    {
        "name": "agent",
        "description": "Hermes용 인증된 읽기 전용 RS 데이터 facade.",
    },
    {
        "name": "repair",
        "description": "Sam 전용 읽기 업무 queue API.",
    },
    {
        "name": "crawl-analysis",
        "description": "사용자가 요청한 Sam 크롤링 품질 분석 API.",
    },
]

app = FastAPI(
    title="RS Scanner API",
    version="0.1.0",
    description=description,
    openapi_tags=tags_metadata,
    contact={
        "name": "RS Scanner",
        "url": "https://github.com/yourusername/rs_scanner",
    },
    license_info={
        "name": "MIT",
    },
)

# Rate Limiting (IP 기반, 기본 60req/min, 랭킹/종목 30req/min)
app.add_middleware(RateLimitMiddleware)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://incommutable-subabsolutely-luanne.ngrok-free.dev",
    ],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "").strip()[:128] or uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/agent/v1") and response.status_code >= 400:
        increment_metric("hermes_api_errors_total")
    response.headers["X-Request-Id"] = request_id
    return response

# 예외 핸들러 등록
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# 라우터 등록
app.include_router(health_router, prefix="/api/v1", tags=["health"])
app.include_router(agent_router, prefix="/api/v1/agent/v1", tags=["agent"])
app.include_router(repair_router, prefix="/internal/v1/repair", tags=["repair"])
app.include_router(analysis_router, prefix="/internal/v1/crawl-analysis", tags=["crawl-analysis"])
app.include_router(codex_router, prefix="/internal/v1/codex-change-requests", tags=["crawl-analysis"])
app.include_router(rankings_router, prefix="/api/v1", tags=["rankings"])
app.include_router(stocks_router, prefix="/api/v1/stocks", tags=["stocks"])
app.include_router(crawl_router, prefix="/api/v1/crawl", tags=["crawl"])


_INTERNAL_SCOPE_BY_OPERATION = {
    ("/internal/v1/crawl-analysis/quality-reports", "get"): "analysis:read",
    ("/internal/v1/crawl-analysis/quality-reports/{report_id}", "get"): "analysis:read",
    ("/internal/v1/crawl-analysis/failures", "get"): "analysis:read",
    ("/internal/v1/crawl-analysis/target-results", "get"): "analysis:read",
    ("/internal/v1/crawl-analysis/stock-history/{symbol}", "get"): "analysis:read",
    ("/internal/v1/crawl-analysis/requests", "post"): "analysis:request",
    ("/internal/v1/crawl-analysis/requests/{request_id}", "get"): "analysis:read",
    ("/internal/v1/crawl-analysis/requests/{request_id}/quality-reports", "get"): "analysis:read",
    ("/internal/v1/crawl-analysis/requests/{request_id}/accept", "post"): "analysis:accept",
    ("/internal/v1/crawl-analysis/requests/{request_id}/report-hash", "post"): "analysis:submit",
    ("/internal/v1/crawl-analysis/requests/{request_id}/report", "post"): "analysis:submit",
    ("/internal/v1/codex-change-requests", "post"): "codex:request",
    ("/internal/v1/codex-change-requests/{change_request_id}", "get"): "analysis:read",
    ("/internal/v1/codex-change-requests/{change_request_id}/review", "post"): "analysis:review",
    ("/internal/v1/codex-change-requests/{change_request_id}/result", "post"): "codex:result",
}


def custom_openapi():
    """OpenAPI 스키마 커스터마이징."""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )

    # 서버 정보 추가
    openapi_schema["servers"] = [
        {
            "url": "http://localhost:8000",
            "description": "개발 서버",
        },
    ]
    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["InternalBearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "opaque service token",
        "description": (
            "Internal API only. A role-specific bearer token is required. "
            "The x-required-scopes extension on each operation lists the exact scope. "
            "Do not place token values in reports, source control, or OpenAPI examples."
        ),
    }
    for (path, method), required_scope in _INTERNAL_SCOPE_BY_OPERATION.items():
        operation = openapi_schema.get("paths", {}).get(path, {}).get(method)
        if operation is not None:
            operation["security"] = [{"InternalBearerAuth": []}]
            operation["x-required-scopes"] = [required_scope]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
