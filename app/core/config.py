from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
