"""FastAPI 主應用程式"""
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from loguru import logger
import sys

from app.config import get_settings
from app.handlers.webhook_handler import LineWebhookHandler


# 設定日誌
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    "logs/app.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG"
)


# 全域變數
webhook_handler: LineWebhookHandler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    global webhook_handler

    # 啟動時初始化
    logger.info("正在初始化 LINE 翻譯機器人...")
    settings = get_settings()
    webhook_handler = LineWebhookHandler()
    logger.info(f"LINE 翻譯機器人已啟動，監聽端口: {settings.app_port}")

    yield

    # 關閉時清理
    logger.info("正在關閉 LINE 翻譯機器人...")


# 建立 FastAPI 應用程式
app = FastAPI(
    title="LINE Translator Bot",
    description="中文-印尼文自動翻譯機器人",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """根端點"""
    return {"status": "ok", "message": "LINE Translator Bot is running"}


@app.get("/health")
async def health_check():
    """健康檢查端點"""
    return {
        "status": "healthy",
        "service": "line-translator-bot",
        "version": "1.0.0"
    }


@app.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(None, alias="X-Line-Signature")
):
    """
    LINE Webhook 端點
    接收來自 LINE Platform 的事件
    """
    if not x_line_signature:
        raise HTTPException(status_code=400, detail="Missing X-Line-Signature header")

    body = await request.body()
    body_text = body.decode("utf-8")

    logger.debug(f"收到 Webhook 請求: {body_text[:200]}...")

    try:
        webhook_handler.handle_webhook(body_text, x_line_signature)
    except Exception as e:
        logger.error(f"Webhook 處理錯誤: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(content={"status": "ok"})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全域例外處理"""
    logger.error(f"未處理的例外: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug
    )
