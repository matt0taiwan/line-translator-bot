"""Admin command handler — 管理員透過 LINE 私訊跟伺服器互動。

容器端只負責：解析指令、驗證擁有者、寫入佇列檔。實際執行由 host 端
systemd worker 處理，並透過 LINE push 直接回報結果。
"""
import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from loguru import logger


QUEUE_DIR = Path("/app/admin-queue/requests")

HELP_TEXT = (
    "🤖 管理員指令\n"
    "/help — 顯示此說明\n"
    "/status — docker ps + uptime + df + free\n"
    "/uptime — 系統 uptime\n"
    "/df — 磁碟使用量\n"
    "/logs <service> [lines] — 容器日誌尾端（預設 50 行）\n"
    "/restart <service> — 重啟服務（僅 nginx / line-translator-bot）\n"
    "/update — 手動觸發 apt 更新"
)

LOCAL_COMMANDS = {"/help"}
QUEUED_COMMANDS = {"/status", "/uptime", "/df", "/logs", "/restart", "/update"}
ALL_COMMANDS = LOCAL_COMMANDS | QUEUED_COMMANDS


def parse(text: str) -> Optional[tuple[str, list[str]]]:
    """把訊息解析成 (cmd, args)。不是指令回 None。"""
    text = text.strip()
    if not text.startswith("/"):
        return None
    parts = text.split()
    cmd = parts[0].lower()
    if cmd not in ALL_COMMANDS:
        return None
    return cmd, parts[1:]


def build_help_reply() -> str:
    return HELP_TEXT


def enqueue(cmd: str, args: list[str], user_id: str) -> bool:
    """寫入佇列檔，回傳成功與否。"""
    try:
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        req_id = f"{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"
        payload = {
            "id": req_id,
            "cmd": cmd,
            "args": args,
            "user_id": user_id,
            "ts": time.time(),
        }
        tmp = QUEUE_DIR / f".{req_id}.tmp"
        final = QUEUE_DIR / f"{req_id}.json"
        tmp.write_text(json.dumps(payload, ensure_ascii=False))
        tmp.rename(final)
        logger.info(f"已寫入管理員指令佇列: {cmd} {args}")
        return True
    except Exception as e:
        logger.error(f"寫入管理員指令佇列失敗: {e}")
        return False
