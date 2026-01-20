"""設定管理模組"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LINE Bot 設定
    line_channel_secret: str
    line_channel_access_token: str

    # 應用程式設定
    app_host: str = "0.0.0.0"
    app_port: int = 5000
    debug: bool = False

    # 翻譯設定
    default_chinese: str = "zh-TW"
    indonesian: str = "id"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
