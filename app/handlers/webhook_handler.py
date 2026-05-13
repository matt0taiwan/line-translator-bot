"""LINE Webhook 處理器 - 處理訊息事件並翻譯"""
import asyncio
import re
import time

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    Sender,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    JoinEvent,
    FollowEvent,
)
from loguru import logger

from app.config import Settings, get_settings
from app.services import admin_commands
from app.services.language_detector import LanguageDetector
from app.services.openclaw_client import OpenClawClient
from app.services.translator import TranslatorService


# Sender 名稱清洗用 regex（compile 一次）
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_NG_CHARS_RE = re.compile(r"[*\[\]`~#|\\]")
_LINE_WORD_RE = re.compile(r"\bline\b", flags=re.IGNORECASE)
_MULTI_WS_RE = re.compile(r"\s+")


class LineWebhookHandler:
    """LINE Webhook 處理器"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.handler = WebhookHandler(self.settings.line_channel_secret)

        configuration = Configuration(
            access_token=self.settings.line_channel_access_token
        )
        self.api_client = AsyncApiClient(configuration)
        self.messaging_api = AsyncMessagingApi(self.api_client)

        self.detector = LanguageDetector()
        self.translator = TranslatorService(self.settings)
        self.openclaw = OpenClawClient(self.settings)

        # (user_id, group_id) -> (expire_ts, display_name, picture_url)
        self._profile_cache: dict[tuple[str, str | None], tuple[float, str | None, str | None]] = {}

        self._register_handlers()

    # ───────────────────────── event registration ─────────────────────────

    def _register_handlers(self) -> None:
        @self.handler.add(MessageEvent, message=TextMessageContent)
        def handle_text_message(event: MessageEvent):
            asyncio.create_task(self._process_text_message(event))

        @self.handler.add(JoinEvent)
        def handle_join(event: JoinEvent):
            asyncio.create_task(self._send_welcome_message(event))

        @self.handler.add(FollowEvent)
        def handle_follow(event: FollowEvent):
            asyncio.create_task(self._send_welcome_message(event))

    def handle_webhook(self, body: str, signature: str) -> None:
        self.handler.handle(body, signature)

    # ───────────────────────── text dispatch ─────────────────────────

    async def _process_text_message(self, event: MessageEvent) -> None:
        text, user_id, group_id = self._extract_context(event)
        if not text or not text.strip():
            return

        if self._is_owner_direct_message(user_id, group_id):
            await self._handle_admin_message(event, user_id, text)
        else:
            await self._handle_translation_message(event, user_id, group_id, text)

    @staticmethod
    def _extract_context(event: MessageEvent) -> tuple[str, str, str | None]:
        text = event.message.text
        user_id = event.source.user_id
        group_id = getattr(event.source, "group_id", None)
        return text, user_id, group_id

    def _is_owner_direct_message(self, user_id: str, group_id: str | None) -> bool:
        owner = self.settings.owner_user_id
        return bool(owner) and user_id == owner and group_id is None

    # ───────────────────────── admin path ─────────────────────────

    async def _handle_admin_message(self, event: MessageEvent, user_id: str, text: str) -> None:
        """私訊 owner：先試 OpenClaw（限時 reply_window），逾時改 push，皆失敗才 fallback 指令系統。"""
        reply_window = self.settings.openclaw_reply_window
        task = asyncio.create_task(self.openclaw.ask(text, user_id=user_id))

        done, _ = await asyncio.wait({task}, timeout=reply_window)

        if done:
            ai_response = task.result()
            if ai_response:
                logger.info(f"OpenClaw 回覆成功（{len(ai_response)} 字元，reply_token 內）")
                await self._reply_message(event.reply_token, TextMessage(text=ai_response))
                return
            logger.info("OpenClaw 回傳 None，嘗試 fallback 指令系統")
            await self._handle_admin_fallback(event, user_id, text)
            return

        # 還在思考 → 先 placeholder，背景 push
        logger.info("OpenClaw 超過 reply_token 窗口，切換為背景推送模式")
        await self._reply_message(
            event.reply_token,
            TextMessage(text="🧠 Sibyl 思考中，稍後回覆⋯"),
        )
        asyncio.create_task(self._push_when_ready(user_id, task))

    async def _push_when_ready(self, user_id: str, task: asyncio.Task) -> None:
        """OpenClaw 還在跑時的背景推送。"""
        try:
            result = await task
            if result:
                logger.info(f"OpenClaw 背景回覆成功（{len(result)} 字元），Push 推送")
                await self._push_message(user_id, TextMessage(text=result))
            else:
                logger.warning("OpenClaw 背景任務回傳 None")
                await self._push_message(
                    user_id,
                    TextMessage(text="⚠️ Sibyl 處理失敗，請稍後再試或使用 /help 查看備援指令"),
                )
        except Exception as e:
            logger.error(f"OpenClaw 背景推送失敗：{e}")

    async def _handle_admin_fallback(self, event: MessageEvent, user_id: str, text: str) -> None:
        """OpenClaw 失敗時的固定指令系統。"""
        parsed = admin_commands.parse(text)
        if not parsed:
            logger.info("OpenClaw 及指令系統皆無法處理，跳過")
            return

        cmd, args = parsed
        logger.info(f"Fallback 指令: {cmd} {args}")
        if cmd == "/help":
            await self._reply_message(
                event.reply_token,
                TextMessage(text=admin_commands.build_help_reply()),
            )
            return

        ok = admin_commands.enqueue(cmd, args, user_id)
        ack = "⏳ OpenClaw 無回應，已切換備援指令，稍後回報" if ok else "❌ 佇列失敗，請查看 bot log"
        await self._reply_message(event.reply_token, TextMessage(text=ack))

    # ───────────────────────── translation path ─────────────────────────

    async def _handle_translation_message(
        self,
        event: MessageEvent,
        user_id: str,
        group_id: str | None,
        text: str,
    ) -> None:
        detected_lang = self.detector.detect(text)
        logger.info(
            f"收到訊息 [user: …{user_id[-6:]}] [lang: {detected_lang}] [len: {len(text)}]"
        )

        if detected_lang == "zh":
            translated_text = await self.translator.chinese_to_indonesian(text)
        elif detected_lang == "other":
            translated_text = await self.translator.to_chinese(text)
        else:
            logger.info("空白訊息，跳過翻譯")
            return

        if not translated_text:
            return

        sender = await self._build_sender(user_id, group_id)
        await self._reply_message(
            event.reply_token,
            TextMessage(text=translated_text, sender=sender),
        )

    async def _build_sender(self, user_id: str, group_id: str | None) -> Sender | None:
        display_name, picture_url = await self._get_user_profile_cached(user_id, group_id)
        if not display_name:
            return None
        clean_name = self._sanitize_sender_name(display_name)
        if not clean_name:
            return None
        logger.info(f"使用 Sender 自訂: {clean_name} (icon={'yes' if picture_url else 'no'})")
        return Sender(name=clean_name, icon_url=picture_url)

    # ───────────────────────── profile cache ─────────────────────────

    async def _get_user_profile_cached(
        self, user_id: str, group_id: str | None
    ) -> tuple[str | None, str | None]:
        key = (user_id, group_id)
        now = time.monotonic()

        cached = self._profile_cache.get(key)
        if cached and cached[0] > now:
            return cached[1], cached[2]

        display_name, picture_url = await self._fetch_profile(user_id, group_id)

        # 命中或 miss 都快取（含 None），避免暴衝錯誤；TTL 到了會重新打
        expire = now + self.settings.profile_cache_ttl
        self._profile_cache[key] = (expire, display_name, picture_url)
        self._evict_profile_cache_if_needed()
        return display_name, picture_url

    async def _fetch_profile(
        self, user_id: str, group_id: str | None
    ) -> tuple[str | None, str | None]:
        try:
            if group_id:
                profile = await self.messaging_api.get_group_member_profile(
                    group_id=group_id, user_id=user_id
                )
            else:
                profile = await self.messaging_api.get_profile(user_id=user_id)
            return profile.display_name, profile.picture_url
        except Exception as e:
            logger.warning(f"無法取得使用者資料: {e}")
            return None, None

    def _evict_profile_cache_if_needed(self) -> None:
        max_size = self.settings.profile_cache_size
        if len(self._profile_cache) <= max_size:
            return
        # 簡易 eviction：清掉所有已過期的，再不夠就砍最舊一半
        now = time.monotonic()
        expired = [k for k, v in self._profile_cache.items() if v[0] <= now]
        for k in expired:
            del self._profile_cache[k]
        if len(self._profile_cache) <= max_size:
            return
        # 按 expire 時間排序，砍掉最早到期那一半
        sorted_keys = sorted(self._profile_cache.items(), key=lambda kv: kv[1][0])
        for k, _ in sorted_keys[: len(sorted_keys) // 2]:
            del self._profile_cache[k]

    # ───────────────────────── welcome / send ─────────────────────────

    async def _send_welcome_message(self, event) -> None:
        welcome_text = (
            "翻譯機器人已啟動！\n"
            "Bot Penerjemah Aktif!\n\n"
            "直接輸入文字即可自動翻譯\n"
            "Ketik langsung untuk terjemahan otomatis\n\n"
            "中文 <-> Bahasa Indonesia"
        )
        await self._reply_message(event.reply_token, TextMessage(text=welcome_text))

    async def _reply_message(self, reply_token: str, message: TextMessage) -> None:
        try:
            await self.messaging_api.reply_message(
                ReplyMessageRequest(reply_token=reply_token, messages=[message])
            )
        except Exception as e:
            logger.error(f"回覆訊息失敗: {e}")

    async def _push_message(self, user_id: str, message: TextMessage) -> None:
        try:
            await self.messaging_api.push_message(
                PushMessageRequest(to=user_id, messages=[message])
            )
        except Exception as e:
            logger.error(f"推送訊息失敗: {e}")

    # ───────────────────────── helpers ─────────────────────────

    @staticmethod
    def _sanitize_sender_name(name: str) -> str:
        """清理 Sender 顯示名稱：去括號 / NG 字元 / line 字樣，限 20 字。"""
        clean = _PAREN_RE.sub("", name)
        clean = _NG_CHARS_RE.sub("", clean)
        clean = _LINE_WORD_RE.sub("", clean)
        clean = _MULTI_WS_RE.sub(" ", clean).strip()
        if len(clean) > 20:
            clean = clean[:20].strip()
        return clean
