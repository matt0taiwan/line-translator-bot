import httpx
import os
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger

OPENCLAW_URL = os.environ.get(
    "OPENCLAW_URL",
    "http://host.docker.internal:18789/v1/chat/completions",
)
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_API_TOKEN", "")

# OpenClaw workspace for memory injection
WORKSPACE_PATH = Path(os.environ.get("OPENCLAW_WORKSPACE", "/openclaw-workspace"))


def _build_memory_system_message() -> str | None:
    """讀取 MEMORY.md（結構化事實）和今昨兩天的 daily file（事件記憶）。"""
    parts: list[str] = []

    # 長期結構化事實
    memory_md = WORKSPACE_PATH / "MEMORY.md"
    if memory_md.exists():
        content = memory_md.read_text(encoding="utf-8").strip()
        if content:
            parts.append(f"=== 長期記憶 ===\n{content}")

    # 近期事件記憶（昨天 → 今天）
    for delta in [1, 0]:
        date = (datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d")
        daily = WORKSPACE_PATH / "memory" / f"{date}.md"
        if daily.exists():
            content = daily.read_text(encoding="utf-8").strip()
            if content:
                label = "今天" if delta == 0 else "昨天"
                parts.append(f"=== {label}的對話記錄 ({date}) ===\n{content}")

    if not parts:
        return None
    return (
        "以下是你的記憶，請在回答時參考（不必逐條複述）：\n\n"
        + "\n\n".join(parts)
    )


def _write_daily_memory(user_msg: str, ai_reply: str) -> None:
    """將對話摘要 append 到今天的 daily memory file。"""
    try:
        memory_dir = WORKSPACE_PATH / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        daily_file = memory_dir / f"{today}.md"
        now = datetime.now().strftime("%H:%M")
        entry = f"[{now}] (LINE) {user_msg[:120]} → {ai_reply[:240]}\n"
        with open(daily_file, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.warning(f"寫入 daily memory 失敗：{e}")


async def ask(message: str, timeout: float = 120.0, user_id: str | None = None) -> str | None:
    """向 OpenClaw 發送訊息，返回 AI 回應文字；失敗或逾時返回 None。

    記憶層次：
      OpenClaw session — disk-backed，由 user="line-XXX" 衍生 sessionKey 自動維護
                         (.openclaw/agents/main/sessions/<id>.jsonl)
      MEMORY.md + daily file — 透過 system message 注入
    """
    if not OPENCLAW_TOKEN:
        logger.warning("OPENCLAW_API_TOKEN 未設定，跳過 OpenClaw")
        return None
    try:
        messages: list[dict] = []

        system_ctx = _build_memory_system_message()
        if system_ctx:
            messages.append({"role": "system", "content": system_ctx})

        messages.append({"role": "user", "content": message})

        body: dict = {
            "model": "openclaw",
            "messages": messages,
            "stream": False,
        }
        if user_id:
            body["user"] = f"line-{user_id}"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENCLAW_URL,
                headers={"Authorization": f"Bearer {OPENCLAW_TOKEN}"},
                json=body,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]

        try:
            _write_daily_memory(message, reply)
        except Exception:
            pass

        return reply
    except httpx.TimeoutException:
        logger.warning(f"OpenClaw 逾時（>{timeout}s），切換 fallback")
        return None
    except Exception as e:
        logger.warning(f"OpenClaw 呼叫失敗：{e}，切換 fallback")
        return None
