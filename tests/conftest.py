"""共用 fixtures。"""
import os

import pytest

# 在 import app.config 之前注入最少必要環境變數，讓 Settings 能順利建構
os.environ.setdefault("LINE_CHANNEL_SECRET", "dummy_secret_for_tests")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "dummy_token_for_tests")

from app.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    """每次測試一個乾淨的 workspace。"""
    return Settings(
        line_channel_secret="dummy_secret",
        line_channel_access_token="dummy_token",
        owner_user_id="Uowner",
        openclaw_api_token="dummy_openclaw",
        openclaw_workspace=str(tmp_path),
        memory_retention_days=7,
    )
