"""翻譯服務 - 使用 deep-translator 進行中印互譯"""
import asyncio
from collections import OrderedDict
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
        self._retries = settings.translate_retries
        self._retry_base_delay = settings.translate_retry_base_delay
        self._executor = ThreadPoolExecutor(
            max_workers=settings.translator_workers,
            thread_name_prefix="translator",
        )
        # 翻譯結果 LRU 快取：同一句重複翻譯直接命中，不再打 Google。
        # 讀寫都在 event loop 單一執行緒內進行，故不需鎖。
        self._cache_size = settings.translate_cache_size
        self._cache: "OrderedDict[tuple[str, str, str], str]" = OrderedDict()

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

        cache_key = (source_lang, target_lang, text)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info(f"翻譯快取命中: [{source_lang}->{target_lang}] {text[:30]}...")
            return cached

        loop = asyncio.get_running_loop()
        # Google 免費翻譯端點偶爾回傳暫時性 5xx（包成 RequestError）或
        # 限流（TooManyRequests），這類錯誤多半重試一兩次即可成功，
        # 因此採指數退避重試，全部用完才回傳失敗提示給使用者。
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                result = await loop.run_in_executor(
                    self._executor,
                    partial(translator.translate, text),
                )
                logger.info(
                    f"翻譯成功: [{source_lang}] {text[:30]}... -> [{target_lang}] {result[:30]}..."
                )
                if result:
                    self._cache_put(cache_key, result)
                return result
            except (RequestError, TooManyRequests) as e:
                last_error = e
                if attempt < self._retries:
                    delay = self._retry_base_delay * (2 ** attempt)
                    logger.warning(
                        f"翻譯暫時性錯誤（第 {attempt + 1}/{self._retries} 次重試，"
                        f"{delay:.1f}s 後重試）: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                break
            except TranslationNotFound:
                logger.error(f"找不到翻譯: {text}")
                return None
            except Exception as e:
                logger.error(f"翻譯發生未知錯誤: {e}")
                return None

        if isinstance(last_error, TooManyRequests):
            logger.error("翻譯 API 請求過於頻繁，重試後仍失敗")
            return "[翻譯失敗：請求過於頻繁，請稍後再試]"
        logger.error(f"翻譯請求錯誤，重試後仍失敗: {last_error}")
        return "[翻譯失敗：網路錯誤]"

    # ───────────────────────── LRU 快取 ─────────────────────────

    def _cache_get(self, key: "tuple[str, str, str]") -> str | None:
        value = self._cache.get(key)
        if value is not None:
            self._cache.move_to_end(key)  # 標記為最近使用
        return value

    def _cache_put(self, key: "tuple[str, str, str]", value: str) -> None:
        if self._cache_size <= 0:
            return
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)  # 淘汰最久未使用

    async def chinese_to_indonesian(self, text: str) -> str | None:
        return await self.translate(text, "zh", "id")

    async def to_chinese(self, text: str) -> str | None:
        return await self.translate(text, "auto", "zh")
