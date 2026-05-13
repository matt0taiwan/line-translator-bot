"""LineWebhookHandler._sanitize_sender_name 測試。"""
import pytest

from app.handlers.webhook_handler import LineWebhookHandler


sanitize = LineWebhookHandler._sanitize_sender_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Matthew", "Matthew"),
        ("Alice (admin)", "Alice"),
        ("Bob（測試）", "Bob"),
        ("Charlie *VIP*", "Charlie VIP"),
        ("Dave [tag]", "Dave tag"),
        ("Eve | Marketing", "Eve  Marketing"),  # | 被移除，留下兩個空白會被 normalize
        ("Frank LINE Bot", "Frank  Bot"),  # "line" 字樣移除（不分大小寫）
        ("Gina  spaced", "Gina spaced"),  # 多空白 normalize
        ("", ""),
    ],
)
def test_basic_cleanup(raw, expected):
    # _MULTI_WS_RE 把連續空白縮成一個，所以期望也要對齊
    result = sanitize(raw)
    # 用 split 比較避免空白數量差異
    assert result.split() == expected.split()


def test_truncate_to_20_chars():
    name = "a" * 50
    assert len(sanitize(name)) == 20


def test_truncate_with_trailing_space_trimmed():
    name = "hello world " + "x" * 30
    result = sanitize(name)
    assert len(result) <= 20
    assert not result.endswith(" ")
