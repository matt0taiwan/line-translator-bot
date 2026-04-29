import httpx
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger

OPENCLAW_URL = os.environ.get(
    "OPENCLAW_URL",
    "http://host.docker.internal:18789/v1/chat/completions",
)
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_API_TOKEN", "")

MAX_HISTORY_TURNS = 20
SESSION_IDLE_SECONDS = 7200

# Layer 1: SQLite-backed conversation history
DB_PATH = os.environ.get("HISTORY_DB_PATH", "/app/data/history.db")

# Layer 2+3: OpenClaw workspace for memory injection
WORKSPACE_PATH = Path(os.environ.get("OPENCLAW_WORKSPACE", "/openclaw-workspace"))


def _init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  TEXT    NOT NULL,
            role     TEXT    NOT NULL,
            content  TEXT    NOT NULL,
            ts       REAL    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_ts ON messages(user_id, ts)")
    conn.commit()
    conn.close()


_db_ready = False


def _ensure_db() -> None:
    global _db_ready
    if not _db_ready:
        _init_db()
        _db_ready = True


def _get_history(user_id: str) -> list[dict]:
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT ts FROM messages WHERE user_id=? ORDER BY ts DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if row and time.time() - row[0] > SESSION_IDLE_SECONDS:
            conn.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
            conn.commit()
            logger.info(f"對話記憶逾時重置 [user: {user_id}]")
            return []
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE user_id=? ORDER BY ts DESC LIMIT ?",
            (user_id, MAX_HISTORY_TURNS * 2),
        ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]
    finally:
        conn.close()


def _append_history(user_id: str, role: str, content: str) -> None:
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO messages (user_id, role, content, ts) VALUES (?,?,?,?)",
            (user_id, role, content, time.time()),
        )
        # trim to sliding window
        conn.execute("""
            DELETE FROM messages
            WHERE user_id=? AND id NOT IN (
                SELECT id FROM messages WHERE user_id=? ORDER BY ts DESC LIMIT ?
            )
        """, (user_id, user_id, MAX_HISTORY_TURNS * 2))
        conn.commit()
    finally:
        conn.close()


def clear_history(user_id: str) -> None:
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    logger.info(f"對話記憶已清除 [user: {user_id}]")


def _build_memory_system_message() -> str | None:
    """Layer 2+3: 讀取 MEMORY.md（結構化事實）和今昨兩天的 daily file（事件記憶）。"""
    parts: list[str] = []

    # Layer 3: 長期結構化事實
    memory_md = WORKSPACE_PATH / "MEMORY.md"
    if memory_md.exists():
        content = memory_md.read_text(encoding="utf-8").strip()
        if content:
            parts.append(f"=== 長期記憶 ===\n{content}")

    # Layer 2: 近期事件記憶（昨天 → 今天）
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
    """Layer 2: 將對話摘要 append 到今天的 daily memory file。"""
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

    三層記憶：
      Layer 1 — SQLite 對話 history（持久，滑動視窗）
      Layer 2 — daily memory file 注入（事件記憶）
      Layer 3 — MEMORY.md 注入（長期結構化事實）
    """
    if not OPENCLAW_TOKEN:
        logger.warning("OPENCLAW_API_TOKEN 未設定，跳過 OpenClaw")
        return None
    try:
        history = _get_history(user_id) if user_id else []

        messages: list[dict] = []

        # Layer 2+3: 注入記憶作為 system message
        system_ctx = _build_memory_system_message()
        if system_ctx:
            messages.append({"role": "system", "content": system_ctx})

        messages += history + [{"role": "user", "content": message}]

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

        if user_id:
            _append_history(user_id, "user", message)
            _append_history(user_id, "assistant", reply)

        # Layer 2: 非同步寫入 daily memory（不阻塞回覆）
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
