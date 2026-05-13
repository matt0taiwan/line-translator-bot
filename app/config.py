"""設定管理模組"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LINE Bot
    line_channel_secret: str
    line_channel_access_token: str
    owner_user_id: str = ""

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 5000
    debug: bool = False

    # Translation
    default_chinese: str = "zh-TW"
    indonesian: str = "id"
    translator_workers: int = 4

    # OpenClaw
    openclaw_url: str = "http://host.docker.internal:18789/v1/chat/completions"
    openclaw_api_token: str = ""
    openclaw_workspace: str = "/openclaw-workspace"
    openclaw_timeout: float = 120.0
    openclaw_reply_window: int = 20

    # Memory retention
    memory_retention_days: int = 14

    # LINE profile cache
    profile_cache_ttl: int = 3600
    profile_cache_size: int = 512

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
