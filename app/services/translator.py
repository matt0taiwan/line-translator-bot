"""翻譯服務 - 使用 deep-translator 進行中印互譯"""
import asyncio
from functools import partial
from deep_translator import GoogleTranslator
from deep_translator.exceptions import (
    TranslationNotFound,
    RequestError,
    TooManyRequests
)
from loguru import logger


class TranslatorService:
    """翻譯服務"""

    def __init__(self):
        self.zh_to_id = GoogleTranslator(source='zh-TW', target='id')
        self.auto_to_zh = GoogleTranslator(source='auto', target='zh-TW')

    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str
    ) -> str | None:
        """
        非同步翻譯文字

        Args:
            text: 要翻譯的文字
            source_lang: 來源語言 ('zh' 或 'auto')
            target_lang: 目標語言 ('zh' 或 'id')

        Returns:
            翻譯後的文字，失敗時返回 None
        """
        if not text or not text.strip():
            return None

        try:
            loop = asyncio.get_event_loop()

            if source_lang == 'zh' and target_lang == 'id':
                translator = self.zh_to_id
            elif source_lang == 'auto' and target_lang == 'zh':
                translator = self.auto_to_zh
            else:
                logger.error(f"不支援的語言組合: {source_lang} -> {target_lang}")
                return None

            # 在執行緒池中執行同步翻譯
            result = await loop.run_in_executor(
                None,
                partial(translator.translate, text)
            )

            logger.info(f"翻譯成功: [{source_lang}] {text[:30]}... -> [{target_lang}] {result[:30]}...")
            return result

        except TooManyRequests:
            logger.error("翻譯 API 請求過於頻繁")
            return "[翻譯失敗：請求過於頻繁，請稍後再試]"
        except TranslationNotFound:
            logger.error(f"找不到翻譯: {text}")
            return None
        except RequestError as e:
            logger.error(f"翻譯請求錯誤: {e}")
            return "[翻譯失敗：網路錯誤]"
        except Exception as e:
            logger.error(f"翻譯發生未知錯誤: {e}")
            return None

    async def chinese_to_indonesian(self, text: str) -> str | None:
        """中文翻譯成印尼文"""
        return await self.translate(text, 'zh', 'id')

    async def to_chinese(self, text: str) -> str | None:
        """非中文翻譯成中文（由 Google auto-detect 判斷來源語言）"""
        return await self.translate(text, 'auto', 'zh')
