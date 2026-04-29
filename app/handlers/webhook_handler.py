"""LINE Webhook 處理器 - 處理訊息事件並翻譯"""
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

from app.services.language_detector import LanguageDetector
from app.services.translator import TranslatorService
from app.services import admin_commands
from app.services import openclaw_client
from app.config import get_settings


class LineWebhookHandler:
    """LINE Webhook 處理器"""

    def __init__(self):
        settings = get_settings()
        self.handler = WebhookHandler(settings.line_channel_secret)

        # 設定 Messaging API
        configuration = Configuration(
            access_token=settings.line_channel_access_token
        )
        self.api_client = AsyncApiClient(configuration)
        self.messaging_api = AsyncMessagingApi(self.api_client)

        # 初始化服務
        self.detector = LanguageDetector()
        self.translator = TranslatorService()

        # 註冊事件處理器
        self._register_handlers()

    def _register_handlers(self):
        """註冊事件處理器"""

        @self.handler.add(MessageEvent, message=TextMessageContent)
        def handle_text_message(event: MessageEvent):
            """處理文字訊息"""
            import asyncio
            asyncio.create_task(self._process_text_message(event))

        @self.handler.add(JoinEvent)
        def handle_join(event: JoinEvent):
            """處理加入群組事件"""
            import asyncio
            asyncio.create_task(self._send_welcome_message(event))

        @self.handler.add(FollowEvent)
        def handle_follow(event: FollowEvent):
            """處理追蹤事件"""
            import asyncio
            asyncio.create_task(self._send_welcome_message(event))

    async def _get_user_profile(self, user_id: str, group_id: str = None):
        """
        取得使用者資料（頭像和名稱）

        Args:
            user_id: 使用者 ID
            group_id: 群組 ID（如果在群組中）

        Returns:
            (display_name, picture_url) 或 (None, None)
        """
        try:
            if group_id:
                # 群組中取得成員資料
                profile = await self.messaging_api.get_group_member_profile(
                    group_id=group_id,
                    user_id=user_id
                )
            else:
                # 一對一聊天取得資料
                profile = await self.messaging_api.get_profile(user_id=user_id)

            return profile.display_name, profile.picture_url
        except Exception as e:
            logger.warning(f"無法取得使用者資料: {e}")
            return None, None

    async def _process_text_message(self, event: MessageEvent):
        """處理文字訊息並進行翻譯"""
        text = event.message.text
        user_id = event.source.user_id

        # 取得群組 ID（如果在群組中）
        group_id = None
        if hasattr(event.source, 'group_id'):
            group_id = event.source.group_id

        # 管理員私訊：先走 OpenClaw AI，失敗才 fallback 到舊指令系統（群組中仍正常翻譯）
        OWNER_USER_ID = "U1f911f0ce71183e289de2b187335fb0d"
        if user_id == OWNER_USER_ID and group_id is None:
            import asyncio

            REPLY_WINDOW = 20  # reply_token 安全窗口（秒）

            # 發送 OpenClaw 請求（背景 task，不會被 cancel）
            task = asyncio.create_task(openclaw_client.ask(text, user_id=user_id))

            # 等最多 REPLY_WINDOW 秒，看能不能在 reply_token 過期前拿到回覆
            done, _ = await asyncio.wait({task}, timeout=REPLY_WINDOW)

            if done:
                ai_response = task.result()
                if ai_response:
                    logger.info(f"OpenClaw 回覆成功（{len(ai_response)} 字元，reply_token 內）")
                    await self._reply_message(event.reply_token, TextMessage(text=ai_response))
                    return
                # OpenClaw 回傳 None（錯誤），走 fallback
                logger.info("OpenClaw 回傳 None，嘗試 fallback 指令系統")
            else:
                # OpenClaw 還在思考，reply_token 即將過期
                # 先回覆「思考中」，背景等結果再用 Push API 推送
                logger.info("OpenClaw 超過 reply_token 窗口，切換為背景推送模式")
                await self._reply_message(
                    event.reply_token,
                    TextMessage(text="🦞 Sibyl 思考中，稍後回覆⋯"),
                )

                async def _push_when_ready():
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

                asyncio.create_task(_push_when_ready())
                return

            # Fallback：舊的固定指令系統
            logger.info("OpenClaw 無回應，嘗試 fallback 指令系統")
            parsed = admin_commands.parse(text)
            if parsed:
                cmd, args = parsed
                logger.info(f"Fallback 指令: {cmd} {args}")
                if cmd == "/help":
                    await self._reply_message(
                        event.reply_token,
                        TextMessage(text=admin_commands.build_help_reply()),
                    )
                else:
                    ok = admin_commands.enqueue(cmd, args, user_id)
                    ack = "⏳ OpenClaw 無回應，已切換備援指令，稍後回報" if ok else "❌ 佇列失敗，請查看 bot log"
                    await self._reply_message(event.reply_token, TextMessage(text=ack))
                return
            logger.info("收到管理員私訊，OpenClaw 及指令系統皆無法處理，跳過")
            return

        # 偵測語言
        detected_lang = self.detector.detect(text)
        logger.info(f"收到訊息 [user: {user_id}] [lang: {detected_lang}]: {text[:50]}")

        # 根據偵測結果翻譯
        translated_text = None

        if detected_lang == 'zh':
            translated_text = await self.translator.chinese_to_indonesian(text)
        elif detected_lang == 'id':
            translated_text = await self.translator.indonesian_to_chinese(text)
        else:
            logger.info("無法偵測語言，跳過翻譯")
            return

        if not translated_text:
            return

        # 取得發言者資料（用於 Sender 自訂）
        display_name, picture_url = await self._get_user_profile(user_id, group_id)

        # 建立訊息（帶有發言者頭像）
        sender = None
        if display_name:
            # 清理顯示名稱，移除 LINE Sender API 不允許的字元
            clean_name = self._sanitize_sender_name(display_name)
            if clean_name:
                sender = Sender(
                    name=clean_name,
                    icon_url=picture_url,  # 沒頭貼時為 None，LINE 會用 bot 預設圖示
                )
                logger.info(f"使用 Sender 自訂: {clean_name} (icon={'yes' if picture_url else 'no'})")

        # 建立回覆訊息
        message = TextMessage(
            text=translated_text,
            sender=sender
        )

        # 發送翻譯結果
        await self._reply_message(event.reply_token, message)

    async def _send_welcome_message(self, event):
        """發送歡迎訊息"""
        welcome_text = (
            "翻譯機器人已啟動！\n"
            "Bot Penerjemah Aktif!\n\n"
            "直接輸入文字即可自動翻譯\n"
            "Ketik langsung untuk terjemahan otomatis\n\n"
            "中文 <-> Bahasa Indonesia"
        )
        message = TextMessage(text=welcome_text)
        await self._reply_message(event.reply_token, message)

    async def _reply_message(self, reply_token: str, message: TextMessage):
        """回覆訊息（使用 reply_token，免費）"""
        try:
            await self.messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[message]
                )
            )
        except Exception as e:
            logger.error(f"回覆訊息失敗: {e}")

    async def _push_message(self, user_id: str, message: TextMessage):
        """主動推送訊息（用於 reply_token 過期後的非同步回覆）"""
        try:
            await self.messaging_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[message]
                )
            )
        except Exception as e:
            logger.error(f"推送訊息失敗: {e}")

    @staticmethod
    def _sanitize_sender_name(name: str) -> str:
        """
        清理 Sender 顯示名稱，移除 LINE API 不允許的字元和 NG 敏感詞。
        LINE Sender name 限制：1-20 字元，不可含特殊符號、品牌名稱等。
        """
        import re
        # 移除括號及其內容（全形和半形）
        clean = re.sub(r'[（(][^）)]*[）)]', '', name)
        # 移除 * 和其他可能被 LINE 視為 NG 的符號
        clean = re.sub(r'[*\[\]`~#|\\]', '', clean)
        # 移除 LINE 品牌相關 NG 敏感詞（不區分大小寫）
        clean = re.sub(r'\bline\b', '', clean, flags=re.IGNORECASE)
        # 移除多餘空格
        clean = re.sub(r'\s+', ' ', clean).strip()
        # LINE Sender name 上限 20 字元
        if len(clean) > 20:
            clean = clean[:20].strip()
        return clean

    def handle_webhook(self, body: str, signature: str):
        """
        處理 Webhook 請求

        Args:
            body: 請求主體
            signature: X-Line-Signature 標頭
        """
        self.handler.handle(body, signature)
