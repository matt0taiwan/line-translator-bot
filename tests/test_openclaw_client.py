"""OpenClawClient 的記憶相關邏輯測試（不打網路）。"""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.services.openclaw_client import OpenClawClient


@pytest.fixture
def client(settings) -> OpenClawClient:
    return OpenClawClient(settings)


class TestBuildMemorySystemMessage:
    def test_returns_none_when_workspace_empty(self, client):
        assert client._build_memory_system_message() is None

    def test_includes_memory_md(self, client, tmp_path):
        (tmp_path / "MEMORY.md").write_text("user is Matthew\n", encoding="utf-8")
        msg = client._build_memory_system_message()
        assert msg is not None
        assert "長期記憶" in msg
        assert "user is Matthew" in msg

    def test_includes_today_and_yesterday(self, client, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("today entry\n", encoding="utf-8")
        (memory_dir / f"{yesterday}.md").write_text("yesterday entry\n", encoding="utf-8")

        msg = client._build_memory_system_message()
        assert msg is not None
        assert "today entry" in msg
        assert "yesterday entry" in msg
        assert "今天" in msg
        assert "昨天" in msg

    def test_skips_empty_daily_file(self, client, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("   \n", encoding="utf-8")
        assert client._build_memory_system_message() is None


class TestWriteDailyMemory:
    def test_appends_to_today_file(self, client, tmp_path):
        client._write_daily_memory("hi", "hello")
        today = datetime.now().strftime("%Y-%m-%d")
        daily = tmp_path / "memory" / f"{today}.md"
        assert daily.exists()
        content = daily.read_text(encoding="utf-8")
        assert "hi" in content
        assert "hello" in content
        assert "(LINE)" in content

    def test_truncates_long_messages(self, client, tmp_path):
        client._write_daily_memory("u" * 200, "a" * 500)
        today = datetime.now().strftime("%Y-%m-%d")
        content = (tmp_path / "memory" / f"{today}.md").read_text(encoding="utf-8")
        # user_msg 截 120、ai_reply 截 240
        assert "u" * 120 in content
        assert "a" * 240 in content
        assert "u" * 121 not in content
        assert "a" * 241 not in content


class TestPruneOldMemory:
    def _make_file(self, root: Path, days_ago: int) -> Path:
        memory_dir = root / "memory"
        memory_dir.mkdir(exist_ok=True)
        date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        f = memory_dir / f"{date}.md"
        f.write_text("x\n", encoding="utf-8")
        return f

    def test_keeps_recent_deletes_old(self, client, tmp_path):
        recent = self._make_file(tmp_path, 1)
        boundary = self._make_file(tmp_path, 7)  # retention_days=7 → 邊界保留
        old = self._make_file(tmp_path, 30)

        deleted = client.prune_old_memory()
        assert deleted == 1
        assert recent.exists()
        assert boundary.exists()
        assert not old.exists()

    def test_returns_zero_when_no_memory_dir(self, client, tmp_path):
        assert client.prune_old_memory() == 0

    def test_ignores_non_date_filenames(self, client, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        weird = memory_dir / "not-a-date.md"
        weird.write_text("x", encoding="utf-8")
        client.prune_old_memory()
        assert weird.exists()
