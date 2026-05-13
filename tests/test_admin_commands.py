"""admin_commands 解析 + queue 寫檔測試。"""
import json
from pathlib import Path

import pytest

from app.services import admin_commands


class TestParse:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("/help", ("/help", [])),
            ("/status", ("/status", [])),
            ("/logs nginx 100", ("/logs", ["nginx", "100"])),
            ("/restart line-translator-bot", ("/restart", ["line-translator-bot"])),
            ("  /help  ", ("/help", [])),
            ("/HELP", ("/help", [])),  # case-insensitive
        ],
    )
    def test_valid_commands(self, text, expected):
        assert admin_commands.parse(text) == expected

    @pytest.mark.parametrize(
        "text",
        ["hello", "", "/", "/unknown", "not a command"],
    )
    def test_invalid_commands(self, text):
        assert admin_commands.parse(text) is None


class TestEnqueue:
    def test_writes_atomic_file(self, tmp_path, monkeypatch):
        queue_dir = tmp_path / "queue"
        monkeypatch.setattr(admin_commands, "QUEUE_DIR", queue_dir)

        ok = admin_commands.enqueue("/status", [], "Uuser123")
        assert ok is True

        files = list(queue_dir.glob("*.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text())
        assert payload["cmd"] == "/status"
        assert payload["args"] == []
        assert payload["user_id"] == "Uuser123"
        assert "id" in payload
        assert "ts" in payload

    def test_no_tmp_leftover(self, tmp_path, monkeypatch):
        queue_dir = tmp_path / "queue"
        monkeypatch.setattr(admin_commands, "QUEUE_DIR", queue_dir)
        admin_commands.enqueue("/uptime", [], "Uuser")
        assert list(queue_dir.glob(".*.tmp")) == []
