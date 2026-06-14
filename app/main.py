"""FastAPI 主應用程式"""
import sys
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import get_settings
from app.handlers.webhook_handler import LineWebhookHandler


# Logging
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
)
logger.add(
    "logs/app.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
)


webhook_handler: LineWebhookHandler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    global webhook_handler

    logger.info("正在初始化 LINE 翻譯機器人...")
    settings = get_settings()

    if not settings.owner_user_id:
        logger.warning("OWNER_USER_ID 未設定，admin AI 路徑停用（所有人都走翻譯）")
    if not settings.openclaw_api_token:
        logger.warning("OPENCLAW_API_TOKEN 未設定，admin AI 將 fallback 到指令系統")

    webhook_handler = LineWebhookHandler(settings)

    logger.info(f"LINE 翻譯機器人已啟動，監聽端口: {settings.app_port}")
    yield
    logger.info("正在關閉 LINE 翻譯機器人...")


app = FastAPI(
    title="LINE Translator Bot",
    description="中文-印尼文自動翻譯機器人",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {"status": "ok", "message": "LINE Translator Bot is running"}


@app.get("/health")
async def health_check():
    """健康檢查端點。永遠回 200（liveness），openclaw 欄位是 informational。"""
    return {
        "status": "healthy",
        "service": "line-translator-bot",
        "version": "1.0.0",
        "openclaw": await _check_openclaw_status(),
    }


async def _check_openclaw_status() -> str:
    """快速 ping OpenClaw（1s timeout）。失敗回 'down'，token 未設定回 'disabled'。"""
    settings = get_settings()
    if not settings.openclaw_api_token:
        return "disabled"
    base_url = settings.openclaw_url.rsplit("/v1/", 1)[0] or settings.openclaw_url
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(base_url)
            return "up" if resp.status_code < 500 else "down"
    except Exception:
        return "down"


@app.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(None, alias="X-Line-Signature"),
):
    """LINE Webhook 端點"""
    if not x_line_signature:
        raise HTTPException(status_code=400, detail="Missing X-Line-Signature header")

    body = await request.body()
    body_text = body.decode("utf-8")

    logger.debug(f"收到 Webhook 請求: {body_text[:200]}...")

    try:
        webhook_handler.handle_webhook(body_text, x_line_signature)
    except Exception:
        logger.exception("Webhook 處理錯誤")
        raise HTTPException(status_code=400, detail="Webhook processing failed")

    return JSONResponse(content={"status": "ok"})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未處理的例外: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
