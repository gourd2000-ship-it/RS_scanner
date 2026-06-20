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
