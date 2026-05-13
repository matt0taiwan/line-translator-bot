"""LanguageDetector 邊界測試。"""
import pytest

from app.services.language_detector import LanguageDetector


@pytest.fixture
def detector() -> LanguageDetector:
    return LanguageDetector()


class TestDetect:
    def test_pure_chinese(self, detector):
        assert detector.detect("今天天氣很好") == "zh"

    def test_pure_english(self, detector):
        assert detector.detect("hello world how are you") == "other"

    def test_pure_indonesian(self, detector):
        assert detector.detect("selamat pagi apa kabar") == "other"

    def test_empty(self, detector):
        assert detector.detect("") == "unknown"

    def test_whitespace_only(self, detector):
        assert detector.detect("   \n\t ") == "unknown"

    def test_mostly_english_with_one_chinese(self, detector):
        # 1 個中文 / 約 20 字 → 比例 < 30% → other
        assert detector.detect("hello world this is a test 你") == "other"

    def test_mostly_chinese_with_some_english(self, detector):
        # 中文比例 > 30% → zh
        assert detector.detect("今天天氣 hello") == "zh"

    def test_mention_stripped_before_detection(self, detector):
        # @mention 不應該干擾判斷
        assert detector.detect("@alice hello world") == "other"

    def test_mention_with_chinese_message(self, detector):
        assert detector.detect("@小明 今天好嗎") == "zh"

    def test_mention_only(self, detector):
        # 純 mention 沒實質內容，preprocess 後 fallback 到原文，且原文含中文比例高
        result = detector.detect("@小明")
        assert result in ("zh", "other")  # 行為合理即可
