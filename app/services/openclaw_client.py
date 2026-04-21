import httpx
import os
from loguru import logger

OPENCLAW_URL = os.environ.get(
    "OPENCLAW_URL",
    "http://host.docker.internal:18789/v1/chat/completions",
)
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_API_TOKEN", "")


async def ask(message: str, timeout: float = 120.0) -> str | None:
    """向 OpenClaw 發送訊息，返回 AI 回應文字；失敗或逾時返回 None（觸發 fallback）。"""
    if not OPENCLAW_TOKEN:
        logger.warning("OPENCLAW_API_TOKEN 未設定，跳過 OpenClaw")
        return None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENCLAW_URL,
                headers={"Authorization": f"Bearer {OPENCLAW_TOKEN}"},
                json={
                    "model": "openclaw",
                    "messages": [{"role": "user", "content": message}],
                    "stream": False,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except httpx.TimeoutException:
        logger.warning(f"OpenClaw 逾時（>{timeout}s），切換 fallback")
        return None
    except Exception as e:
        logger.warning(f"OpenClaw 呼叫失敗：{e}，切換 fallback")
        return None
