"""語言偵測服務 - 判斷訊息要往哪個方向翻譯"""
import re
from loguru import logger


class LanguageDetector:
    """偵測訊息是中文還是非中文。非中文一律交給 Google auto-detect 翻成中文。"""

    CHINESE_PATTERN = re.compile(r'[一-鿿㐀-䶿]')
    MENTION_PATTERN = re.compile(r'@\S+(?:\s+\S+)?')

    def _preprocess(self, text: str) -> str:
        """移除 @mentions，避免被提到的中文名字干擾比例計算"""
        clean = self.MENTION_PATTERN.sub('', text)
        clean = clean.strip()
        return clean if clean else text

    def detect(self, text: str) -> str:
        """
        判斷訊息方向。

        Returns:
            'zh'      - 中文訊息，要翻成印尼文
            'other'   - 非中文訊息，要交給 Google auto-detect 翻成中文
            'unknown' - 空白文字
        """
        if not text or not text.strip():
            return "unknown"

        clean_text = self._preprocess(text)

        if self._contains_chinese(clean_text):
            chinese_ratio = self._calculate_chinese_ratio(clean_text)
            if chinese_ratio > 0.3:
                logger.debug(f"偵測到中文 (比例: {chinese_ratio:.2f})")
                return "zh"

        logger.debug("非中文，交給 Google auto-detect 翻成中文")
        return "other"

    def _contains_chinese(self, text: str) -> bool:
        return bool(self.CHINESE_PATTERN.search(text))

    def _calculate_chinese_ratio(self, text: str) -> float:
        if not text:
            return 0.0
        chinese_chars = len(self.CHINESE_PATTERN.findall(text))
        total_chars = len(text.replace(" ", ""))
        return chinese_chars / total_chars if total_chars > 0 else 0.0
