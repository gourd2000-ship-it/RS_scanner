import time
from collections import defaultdict
from typing import Callable

from app.core.config import get_settings

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

DEFAULT_LIMIT = 60
WINDOW_SECONDS = 60

PATH_LIMITS: dict[str, int] = {
    "/api/v1/rankings/rs": 30,
    "/api/v1/stocks": 30,
    "/api/v1/agent/v1": 60,
}


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _match_limit(path: str) -> int:
    if path.startswith("/api/v1/agent/v1"):
        return get_settings().agent_rate_limit
    for prefix, limit in PATH_LIMITS.items():
        if path.startswith(prefix):
            return limit
    return DEFAULT_LIMIT


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Callable) -> None:
        super().__init__(app)
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = _get_client_ip(request)
        path = request.url.path
        limit = _match_limit(path)
        key = f"{client_ip}:{path}"

        now = time.monotonic()
        window_start = now - WINDOW_SECONDS
        hits = self._hits[key]
        hits[:] = [t for t in hits if t > window_start]

        if len(hits) >= limit:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded: {limit} requests per minute"},
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )

        hits.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - len(hits)))
        return response
