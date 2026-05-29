"""간단한 in-memory 캐싱 유틸리티."""

import functools
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Callable

from app.core.config import get_settings


class CacheConfig:
    """캐시 설정."""

    def __init__(self):
        self.enabled = get_settings().app_env != "development"
        self.rankings_ttl = 3600  # 1시간
        self.stats_ttl = 300  # 5분
        self.stock_detail_ttl = 600  # 10분

    def is_enabled(self) -> bool:
        """캐시 활성화 여부."""
        return self.enabled


_cache_config = CacheConfig()


def make_cache_key(*args, **kwargs) -> str:
    """캐시 키 생성.

    인자들을 JSON으로 직렬화하고 해시를 생성합니다.
    """
    key_data = {
        "args": args,
        "kwargs": sorted(kwargs.items()),
    }
    key_str = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.md5(key_str.encode()).hexdigest()


class TTLCache:
    """TTL(Time To Live) 기반 캐시.

    만료 시간이 있는 간단한 in-memory 캐시입니다.
    """

    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[Any, datetime]] = {}

    def get(self, key: str) -> Any | None:
        """캐시에서 값을 가져옵니다.

        만료된 항목은 자동으로 삭제됩니다.
        """
        if key not in self._cache:
            return None

        value, expires_at = self._cache[key]
        if datetime.utcnow() > expires_at:
            del self._cache[key]
            return None

        return value

    def set(self, key: str, value: Any) -> None:
        """캐시에 값을 저장합니다."""
        expires_at = datetime.utcnow() + timedelta(seconds=self.ttl_seconds)
        self._cache[key] = (value, expires_at)

    def clear(self) -> None:
        """캐시를 모두 삭제합니다."""
        self._cache.clear()

    def size(self) -> int:
        """캐시 크기를 반환합니다."""
        return len(self._cache)


# 전역 캐시 인스턴스
_rankings_cache = TTLCache(ttl_seconds=_cache_config.rankings_ttl)
_stats_cache = TTLCache(ttl_seconds=_cache_config.stats_ttl)
_stock_detail_cache = TTLCache(ttl_seconds=_cache_config.stock_detail_ttl)


def cached_rankings(func: Callable) -> Callable:
    """랭킹 API 캐싱 데코레이터.

    market, page, size를 키로 사용합니다.
    """
    @functools.wraps(func)
    def wrapper(market: str, page: int = 1, size: int = 100, **kwargs):
        if not _cache_config.is_enabled():
            return func(market=market, page=page, size=size, **kwargs)

        cache_key = make_cache_key("rankings", market, page, size)
        cached_result = _rankings_cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        result = func(market=market, page=page, size=size, **kwargs)
        _rankings_cache.set(cache_key, result)
        return result

    return wrapper


def cached_stats(func: Callable) -> Callable:
    """통계 API 캐싱 데코레이터."""
    @functools.wraps(func)
    def wrapper(**kwargs):
        if not _cache_config.is_enabled():
            return func(**kwargs)

        cache_key = make_cache_key("stats")
        cached_result = _stats_cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        result = func(**kwargs)
        _stats_cache.set(cache_key, result)
        return result

    return wrapper


def cached_stock_detail(func: Callable) -> Callable:
    """종목 상세 API 캐싱 데코레이터.

    code를 키로 사용합니다.
    """
    @functools.wraps(func)
    def wrapper(code: str, **kwargs):
        if not _cache_config.is_enabled():
            return func(code=code, **kwargs)

        cache_key = make_cache_key("stock_detail", code)
        cached_result = _stock_detail_cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        result = func(code=code, **kwargs)
        _stock_detail_cache.set(cache_key, result)
        return result

    return wrapper


def clear_all_caches() -> None:
    """모든 캐시를 삭제합니다."""
    _rankings_cache.clear()
    _stats_cache.clear()
    _stock_detail_cache.clear()


def get_cache_stats() -> dict[str, int]:
    """캐시 통계를 반환합니다."""
    return {
        "rankings_cache_size": _rankings_cache.size(),
        "stats_cache_size": _stats_cache.size(),
        "stock_detail_cache_size": _stock_detail_cache.size(),
        "cache_enabled": _cache_config.is_enabled(),
    }
