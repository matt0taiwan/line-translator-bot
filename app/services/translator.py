"""翻譯服務 - 使用 deep-translator 進行中印互譯"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from deep_translator import GoogleTranslator
from deep_translator.exceptions import (
    RequestError,
    TooManyRequests,
    TranslationNotFound,
)
from loguru import logger

from app.config import Settings


class TranslatorService:
    """翻譯服務"""

    def __init__(self, settings: Settings):
        self.zh_to_id = GoogleTranslator(source="zh-TW", target="id")
        self.auto_to_zh = GoogleTranslator(source="auto", target="zh-TW")
        self._executor = ThreadPoolExecutor(
            max_workers=settings.translator_workers,
            thread_name_prefix="translator",
        )

    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> str | None:
        """非同步翻譯文字。失敗回 None；某些錯誤狀況回固定提示字串給使用者。"""
        if not text or not text.strip():
            return None

        if source_lang == "zh" and target_lang == "id":
            translator = self.zh_to_id
        elif source_lang == "auto" and target_lang == "zh":
            translator = self.auto_to_zh
        else:
            logger.error(f"不支援的語言組合: {source_lang} -> {target_lang}")
            return None

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._executor,
                partial(translator.translate, text),
            )
            logger.info(
                f"翻譯成功: [{source_lang}] {text[:30]}... -> [{target_lang}] {result[:30]}..."
            )
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
        return await self.translate(text, "zh", "id")

    async def to_chinese(self, text: str) -> str | None:
        return await self.translate(text, "auto", "zh")
