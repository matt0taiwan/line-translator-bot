"""語言偵測服務 - 偵測輸入文字是中文還是印尼文"""
import re
from langdetect import detect, LangDetectException
from loguru import logger


class LanguageDetector:
    """語言偵測器"""

    # 中文字元範圍（包含繁簡體）
    CHINESE_PATTERN = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

    def detect(self, text: str) -> str:
        """
        偵測文字語言

        Args:
            text: 要偵測的文字

        Returns:
            語言代碼: 'zh' (中文) 或 'id' (印尼文) 或 'unknown'
        """
        if not text or not text.strip():
            return "unknown"

        # 優先使用正則表達式檢測中文
        if self._contains_chinese(text):
            chinese_ratio = self._calculate_chinese_ratio(text)
            if chinese_ratio > 0.3:
                logger.debug(f"偵測到中文 (比例: {chinese_ratio:.2f})")
                return "zh"

        # 使用 langdetect 進行偵測
        try:
            detected = detect(text)
            logger.debug(f"langdetect 偵測結果: {detected}")

            # 中文相關語言碼
            if detected in ('zh-cn', 'zh-tw', 'zh', 'ko', 'ja'):
                if self._contains_chinese(text):
                    return "zh"

            # 印尼文或馬來文
            if detected in ('id', 'ms'):
                return "id"

            # 檢查印尼文常見詞
            if self._likely_indonesian(text):
                return "id"

        except LangDetectException as e:
            logger.warning(f"語言偵測失敗: {e}")

        return "unknown"

    def _contains_chinese(self, text: str) -> bool:
        """檢查是否包含中文字元"""
        return bool(self.CHINESE_PATTERN.search(text))

    def _calculate_chinese_ratio(self, text: str) -> float:
        """計算中文字元比例"""
        if not text:
            return 0.0
        chinese_chars = len(self.CHINESE_PATTERN.findall(text))
        total_chars = len(text.replace(" ", ""))
        return chinese_chars / total_chars if total_chars > 0 else 0.0

    def _likely_indonesian(self, text: str) -> bool:
        """檢查是否可能是印尼文（基於常見詞）"""
        indonesian_markers = [
            'yang', 'dan', 'di', 'ini', 'itu', 'untuk', 'dengan',
            'tidak', 'dari', 'pada', 'ke', 'saya', 'anda', 'kamu',
            'ada', 'akan', 'bisa', 'sudah', 'juga', 'atau', 'seperti',
            'apa', 'siapa', 'dimana', 'kapan', 'mengapa', 'bagaimana',
            'terima kasih', 'selamat', 'pagi', 'siang', 'malam',
            'makan', 'minum', 'tidur', 'kerja', 'pulang', 'pergi'
        ]
        text_lower = text.lower()
        return any(marker in text_lower for marker in indonesian_markers)
