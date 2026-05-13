"""OpenClaw HTTP client with disk-backed memory injection."""
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from loguru import logger

from app.config import Settings


class OpenClawClient:
    """呼叫 OpenClaw chat-completion API，並維護 daily memory file。

    記憶層次：
      OpenClaw session — disk-backed，由 user="line-<USER_ID>" 衍生 sessionKey
                         由 OpenClaw 自己維護 (.openclaw/agents/main/sessions/...)
      MEMORY.md + daily file — 透過 system message 注入
    """

    def __init__(self, settings: Settings):
        self.url = settings.openclaw_url
        self.token = settings.openclaw_api_token
        self.workspace = Path(settings.openclaw_workspace)
        self.timeout = settings.openclaw_timeout
        self.retention_days = settings.memory_retention_days

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def ask(self, message: str, user_id: str | None = None) -> str | None:
        """發送訊息給 OpenClaw，回傳 AI 回覆；失敗或逾時回 None。"""
        if not self.enabled:
            logger.warning("OPENCLAW_API_TOKEN 未設定，跳過 OpenClaw")
            return None

        messages: list[dict] = []
        system_ctx = self._build_memory_system_message()
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
                reply = data["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            logger.warning(f"OpenClaw 逾時（>{self.timeout}s），切換 fallback")
            return None
        except Exception as e:
            logger.warning(f"OpenClaw 呼叫失敗：{e}，切換 fallback")
            return None

        self._write_daily_memory(message, reply)
        return reply

    def _build_memory_system_message(self) -> str | None:
        """讀取 MEMORY.md（結構化事實）+ 昨天/今天的 daily file（事件記憶）。"""
        parts: list[str] = []

        memory_md = self.workspace / "MEMORY.md"
        if memory_md.exists():
            content = memory_md.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"=== 長期記憶 ===\n{content}")

        for delta in (1, 0):
            date = (datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d")
            daily = self.workspace / "memory" / f"{date}.md"
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

    def _write_daily_memory(self, user_msg: str, ai_reply: str) -> None:
        """append 對話摘要到今天的 daily memory file。"""
        try:
            memory_dir = self.workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            daily_file = memory_dir / f"{today}.md"
            now = datetime.now().strftime("%H:%M")
            entry = f"[{now}] (LINE) {user_msg[:120]} → {ai_reply[:240]}\n"
            with open(daily_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            logger.warning(f"寫入 daily memory 失敗：{e}")

    def prune_old_memory(self) -> int:
        """刪除 memory/ 內超過 retention_days 的 YYYY-MM-DD.md 檔。回傳刪除數。"""
        memory_dir = self.workspace / "memory"
        if not memory_dir.exists():
            return 0

        cutoff = (datetime.now() - timedelta(days=self.retention_days)).date()
        deleted = 0
        for f in memory_dir.glob("*.md"):
            try:
                file_date = datetime.strptime(f.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if file_date < cutoff:
                try:
                    f.unlink()
                    deleted += 1
                except OSError as e:
                    logger.warning(f"刪除舊 memory 檔失敗 {f}: {e}")
        if deleted:
            logger.info(f"已清除 {deleted} 個超過 {self.retention_days} 天的 daily memory file")
        return deleted
