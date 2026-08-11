from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="local", alias="APP_ENV")
    app_name: str = Field(default="rs-scanner", alias="APP_NAME")
    database_url: str = Field(default="postgresql+psycopg://localhost/rs_scanner", alias="DATABASE_URL")

    naver_request_timeout: float = Field(default=10.0, alias="NAVER_REQUEST_TIMEOUT")
    naver_min_delay_ms: int = Field(default=800, alias="NAVER_MIN_DELAY_MS")
    naver_max_delay_ms: int = Field(default=2500, alias="NAVER_MAX_DELAY_MS")
    naver_max_retries: int = Field(default=5, alias="NAVER_MAX_RETRIES")
    naver_max_concurrency: int = Field(default=4, ge=1, alias="NAVER_MAX_CONCURRENCY")
    naver_max_requests_per_batch: int = Field(
        default=5000,
        ge=1,
        alias="NAVER_MAX_REQUESTS_PER_BATCH",
    )
    naver_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        alias="NAVER_USER_AGENT",
    )

    batch_timezone: str = Field(default="Asia/Seoul", alias="BATCH_TIMEZONE")
    batch_market_close_hour: int = Field(default=17, alias="BATCH_MARKET_CLOSE_HOUR")
    batch_chunk_size: int = Field(default=200, alias="BATCH_CHUNK_SIZE")

    # Universe completeness guard.  The ratio is applied per market when a
    # previous active universe exists; the absolute minimum protects a first
    # import from accepting an empty response as a completed snapshot.
    universe_min_symbols: int = Field(default=100, ge=1, alias="UNIVERSE_MIN_SYMBOLS")
    universe_min_symbol_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        alias="UNIVERSE_MIN_SYMBOL_RATIO",
    )

    # EOD provider rollout controls. The safe default is off until a provider
    # contract and canary approval exist; tests can still call sync_eod
    # directly with an explicit source.
    eod_provider_enabled: bool = Field(default=False, alias="EOD_PROVIDER_ENABLED")
    eod_canary_markets: str = Field(default="", alias="EOD_CANARY_MARKETS")
    eod_canary_codes: str = Field(default="", alias="EOD_CANARY_CODES")

    # Hermes Agent API
    agent_api_enabled: bool = Field(default=True, alias="AGENT_API_ENABLED")
    agent_service_tokens: str = Field(default="", alias="AGENT_SERVICE_TOKENS")
    agent_allowed_ips: str = Field(default="", alias="AGENT_ALLOWED_IPS")
    agent_freshness_max_age_hours: int = Field(default=36, ge=1, alias="AGENT_FRESHNESS_MAX_AGE_HOURS")
    agent_rate_limit: int = Field(default=60, ge=1, alias="AGENT_RATE_LIMIT")

    # Hermes client adapter
    hermes_api_base_url: str = Field(default="", alias="HERMES_API_BASE_URL")
    hermes_service_token: Optional[str] = Field(default=None, alias="HERMES_SERVICE_TOKEN")
    hermes_request_timeout: float = Field(default=10.0, alias="HERMES_REQUEST_TIMEOUT")
    hermes_max_retries: int = Field(default=2, ge=0, alias="HERMES_MAX_RETRIES")

    # 알림 설정
    notification_webhook_url: Optional[str] = Field(default=None, alias="NOTIFICATION_WEBHOOK_URL")
    notification_enabled: bool = Field(default=False, alias="NOTIFICATION_ENABLED")
    notification_on_success: bool = Field(default=False, alias="NOTIFICATION_ON_SUCCESS")

    # 텔레그램 알림 설정
    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")
    telegram_enabled: bool = Field(default=False, alias="TELEGRAM_ENABLED")

    # RS 윈저라이즈 설정 (극단치 클리핑 퍼센타일 경계)
    rs_winsorize_lower_pct: float = Field(default=1.0, alias="RS_WINSORIZE_LOWER_PCT")
    rs_winsorize_upper_pct: float = Field(default=99.0, alias="RS_WINSORIZE_UPPER_PCT")

    # 기업 이벤트 감지 임계값 (거래정지 전후 가격 변동 배율)
    corporate_action_threshold: float = Field(default=3.0, alias="CORPORATE_ACTION_THRESHOLD")


@lru_cache
def get_settings() -> Settings:
    return Settings()
