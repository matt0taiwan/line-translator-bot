# LINE Translator Bot

中文 ↔ 印尼文自動翻譯機器人，並整合 **OpenClaw AI** 作為管理員私訊智慧助理。

## 功能特色

### 翻譯（一般使用者 / 群組）
- 自動偵測訊息語言（中文 / 印尼文 / 馬來文）
- 雙向即時翻譯（zh-TW ↔ id）
- 群組內自動回覆翻譯結果
- 透過 LINE Sender API 使用原發言者的頭像和名稱
- 自動移除 `@mentions` 後再判斷語言，避免誤判
- Sender 顯示名稱清理（去除括號、`*`、`[]`、`LINE` 等 NG 字元）

### 管理員私訊（OpenClaw AI）
- 管理員私訊優先送至 [OpenClaw](https://github.com/matt0taiwan/openclaw) LLM 處理
- **記憶機制**：完全交給 OpenClaw 自己的 disk-backed session（用 `user="line-<USER_ID>"` 衍生 sessionKey），bot 端不再注入任何記憶層
  - 完整對話狀態（含 tool call / reasoning）存在 `<openclaw>/.openclaw/agents/main/sessions/<id>.jsonl`
  - 長期事實/skill prompts 由 OpenClaw workspace（MEMORY.md / SOUL.md / TOOLS.md 等）注入
- **背景推送**：若 OpenClaw 思考時間超過 reply_token 安全窗口（20 秒），先回覆「思考中」，完成後透過 Push API 主動推送
- **備援指令系統**：OpenClaw 無回應時自動 fallback 到固定指令（佇列模式）

### 部署
- 基於 Docker Compose
- 整合 Cloudflare Tunnel，提供 HTTPS 支援
- 內建健康檢查端點（`/health`）

## 技術架構

- **語言**: Python 3.12
- **Web 框架**: FastAPI + Uvicorn
- **LINE SDK**: line-bot-sdk 3.x（async API）
- **翻譯服務**: deep-translator（Google Translate，含 auto-detect）
- **語言偵測**: 中文比例正則 + Google auto-detect
- **HTTP Client**: httpx（呼叫 OpenClaw）
- **日誌**: loguru
- **測試**: pytest + pytest-asyncio
- **部署**: Docker + Docker Compose
- **HTTPS**: Cloudflare Tunnel

## 訊息處理流程

```
收到 LINE 訊息
  │
  ├─ 管理員私訊 (user_id == OWNER_USER_ID && 非群組)
  │    │
  │    ├─ 送 OpenClaw（最多等 20 秒）
  │    │    ├─ 收到回覆 → reply_token 直接回覆
  │    │    └─ 超時      → 先回「思考中」，背景等完成後 Push
  │    │
  │    └─ OpenClaw 失敗 → fallback 到指令系統（/help, /status …）
  │
  └─ 一般訊息（含群組）
       │
       ├─ 中文字元 > 30%       → 翻譯成印尼文
       ├─ 其他語言             → Google auto-detect 翻譯成中文
       └─ 空白訊息             → 不處理
```

## 專案結構

```
/opt/line-translator-bot/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 入口、webhook 路由
│   ├── config.py                  # pydantic-settings 環境變數
│   ├── handlers/
│   │   └── webhook_handler.py     # LINE 事件分派、翻譯流程、Sender
│   └── services/
│       ├── translator.py          # zh-TW ↔ id 翻譯（async）
│       ├── language_detector.py   # 中文比例 + langdetect
│       ├── admin_commands.py      # 管理員指令解析 + 寫入佇列
│       └── openclaw_client.py     # OpenClaw API + system message 記憶注入
├── admin-queue/                   # 管理指令佇列（host bind-mount）
│   ├── requests/                  # 待處理請求
│   └── processed/                 # 已處理紀錄
├── tests/                         # pytest 單元測試
│   ├── conftest.py
│   ├── test_language_detector.py
│   ├── test_admin_commands.py
│   ├── test_sanitize_sender_name.py
│   └── test_openclaw_client.py
├── logs/                          # loguru 應用日誌
├── Dockerfile
├── docker-compose.yml
├── requirements.txt               # 鎖死版本
├── requirements-dev.txt           # 額外：pytest
├── .env                           # 環境變數（請勿提交）
└── .env.example                   # 環境變數範例
```

## 安裝與設定

### 1. 前置需求

- Docker 和 Docker Compose
- LINE Developer 帳號
- Cloudflare Tunnel（或其他提供 HTTPS 的解決方案）
- （選用）OpenClaw 服務：管理員 AI 助理功能需要

### 2. 複製專案

```bash
git clone https://github.com/matt0taiwan/line-translator-bot.git
cd line-translator-bot
```

### 3. 設定環境變數

```bash
cp .env.example .env
```

編輯 `.env` 檔案。**必填**：

```env
LINE_CHANNEL_SECRET=你的_channel_secret
LINE_CHANNEL_ACCESS_TOKEN=你的_channel_access_token
```

**選用**（要啟用管理員 AI 助理才需要）：

```env
OWNER_USER_ID=你的_LINE_user_id        # 私訊此 ID 走 OpenClaw AI；留空 = 停用
OPENCLAW_API_TOKEN=你的_openclaw_token  # 留空 = AI 路徑停用、fallback 到 /help 系列指令
```

完整變數清單見 [.env.example](.env.example)（含預設值說明）。**OWNER_USER_ID 不再 hardcode 在程式碼裡**，調整登錄者只要改 `.env` + 重啟容器。

### 4. 啟動服務

```bash
docker compose up -d --build
```

`docker-compose.yml` 預設會掛載：

| 容器路徑 | host 路徑 | 用途 |
|---|---|---|
| `/app/logs` | `./logs` | 應用日誌 |
| `/app/admin-queue` | `./admin-queue` | 管理指令佇列 |

### 5. 設定 LINE Developer Console

1. 前往 [LINE Developer Console](https://developers.line.biz/)
2. 在 **Messaging API** 設定：
   - Webhook URL: `https://你的網址/webhook`
   - 開啟 **Use webhook**
   - 關閉 **Auto-reply messages**
3. 確認 Bot 可以加入群組

### 6. 設定 Cloudflare Tunnel（選用）

```bash
# 安裝 cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# 登入並建立 tunnel
cloudflared tunnel login
cloudflared tunnel create line-bot
cloudflared tunnel route dns line-bot 你的子網域.你的網域.com

# 設定 ~/.cloudflared/config.yml
cat > ~/.cloudflared/config.yml << EOF
tunnel: <tunnel-id>
credentials-file: /home/$USER/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: 你的子網域.你的網域.com
    service: http://localhost:5000
  - service: http_status:404
EOF

# 安裝為系統服務
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

## 使用方式

### 一般使用者 / 群組

1. 將 Bot 加入 LINE 群組
2. 發送中文或印尼文訊息
3. Bot 會自動偵測語言並回覆翻譯（顯示原發言者的頭像和名稱）

範例：

```
小明：你好嗎？
Bot（顯示「小明」的頭像）：Apa kabar?

Siti：Selamat pagi
Bot（顯示「Siti」的頭像）：早安
```

### 管理員（私訊 Bot）

直接以自然語言對話即會走 OpenClaw AI；若 OpenClaw 無回應，可使用以下備援指令：

| 指令 | 說明 |
|---|---|
| `/help` | 顯示指令說明 |
| `/status` | docker ps + uptime + df + free |
| `/uptime` | 系統 uptime |
| `/df` | 磁碟使用量 |
| `/logs <service> [lines]` | 容器日誌尾端（預設 50 行） |
| `/restart <service>` | 重啟服務（僅 nginx / line-translator-bot） |
| `/update` | 手動觸發 apt 更新 |

> 備援指令會寫入 `admin-queue/requests/`，由 host 端 systemd worker 執行並透過 LINE Push API 回報結果。

## 維運操作

### 查看日誌

```bash
docker compose logs -f
```

### 重啟 / 停止服務

```bash
docker compose restart
docker compose down
```

### 更新程式碼

```bash
git pull
docker compose up -d --build
```

### 健康檢查

```bash
curl https://你的網址/health
```

回應：
```json
{
  "status": "healthy",
  "service": "line-translator-bot",
  "version": "1.0.0",
  "openclaw": "up"
}
```

`openclaw` 欄位為 informational：`up` / `down` / `disabled`（未設 token）。HTTP status 永遠 200——OpenClaw 失聯不會觸發容器重啟，因為重啟也修不好。

### 跑單元測試

```bash
docker run --rm -v "$PWD:/app" -w /app python:3.12-slim \
  sh -c "pip install -q -r requirements-dev.txt && pytest -v"
```

測試純粹本地邏輯（語言偵測、指令解析、記憶讀寫、Sender 名稱清洗），不打 LINE / OpenClaw / Google Translate。

## 疑難排解

### Bot 沒有回應

1. 檢查容器狀態：`docker compose ps`
2. 查看日誌：`docker compose logs -f`
3. 確認 Webhook URL 可從外部存取（使用 LINE Console 的 **Verify** 按鈕）

### 翻譯品質不佳

deep-translator 依賴 Google Translate，品質取決於原文清晰度與語境完整性。

### 無法取得使用者頭像

LINE API 限制：
- 使用者必須同意 Bot 取得個人資料
- 群組中某些設定可能阻止 Bot 取得成員資料
- 取不到時 Bot 會使用預設圖示

### OpenClaw 沒有回應

1. 確認 `OPENCLAW_API_TOKEN` 已設定
2. 確認 `OPENCLAW_URL` 可從容器內存取（預設使用 `host.docker.internal`，需 `extra_hosts` 設定）
3. 檢查 OpenClaw 服務本身是否運作正常
4. 即使 OpenClaw 失敗，管理員仍可透過 `/help` 等備援指令操作

### 對話記憶想重置

對話歷史由 OpenClaw 自己的 session 維護，bot 端沒有持久化記憶。重置選項：

1. **強制開新 session**（最簡單）：在 [openclaw_client.py](app/services/openclaw_client.py) 的 `body["user"]` 加上時間 suffix，例如 `f"line-{user_id}-{int(time.time())}"`，OpenClaw 會視為新使用者開新 session
2. **直接刪 session 檔**（保留歷史 dump 用）：
   ```bash
   # 先確認是哪個 session（OpenClaw 會 hash user= 衍生）
   ls /opt/openclaw/.openclaw/agents/main/sessions/
   # 刪除後 OpenClaw 下次互動會建新的
   rm /opt/openclaw/.openclaw/agents/main/sessions/<session-id>.jsonl
   ```

## 授權

MIT License

## 作者

matt0taiwan

## 致謝

- [LINE Messaging API](https://developers.line.biz/en/docs/messaging-api/)
- [deep-translator](https://github.com/nidhaloff/deep-translator)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/)
- [OpenClaw](https://github.com/matt0taiwan/openclaw)
