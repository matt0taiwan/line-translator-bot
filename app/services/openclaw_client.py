"""OpenClaw HTTP client.

對話歷史完全由 OpenClaw 自己的 session（user="line-<USER_ID>" 衍生 sessionKey）維護，
bot 端不再注入額外記憶層。
"""
import httpx
from loguru import logger

from app.config import Settings


class OpenClawClient:
    def __init__(self, settings: Settings):
        self.url = settings.openclaw_url
        self.token = settings.openclaw_api_token
        self.timeout = settings.openclaw_timeout

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def ask(self, message: str, user_id: str | None = None) -> str | None:
        """發送訊息給 OpenClaw，回傳 AI 回覆；失敗或逾時回 None。"""
        if not self.enabled:
            logger.warning("OPENCLAW_API_TOKEN 未設定，跳過 OpenClaw")
            return None

        body: dict = {
            "model": "openclaw",
            "messages": [{"role": "user", "content": message}],
            "stream": False,
        }
        if user_id:
            body["user"] = f"line-{user_id}"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.token}"},
                    json=body,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            logger.warning(f"OpenClaw 逾時（>{self.timeout}s），切換 fallback")
            return None
        except Exception as e:
            logger.warning(f"OpenClaw 呼叫失敗：{e}，切換 fallback")
            return None
