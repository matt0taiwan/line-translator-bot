# LINE Translator Bot

中文 ↔ 印尼文自動翻譯機器人

## 功能特色

- 自動偵測訊息語言（中文/印尼文）
- 雙向即時翻譯
- 群組內自動回覆翻譯結果
- 使用原發言者的頭像和名稱（透過 LINE Sender API）
- 基於 Docker 的簡易部署
- 整合 Cloudflare Tunnel，提供 HTTPS 支援

## 技術架構

- **語言**: Python 3.12
- **Web 框架**: FastAPI + Uvicorn
- **LINE SDK**: line-bot-sdk 3.x
- **翻譯服務**: deep-translator (Google Translate)
- **語言偵測**: langdetect + 中文正則表達式
- **部署**: Docker + Docker Compose
- **HTTPS**: Cloudflare Tunnel

## 翻譯邏輯

```
收到訊息 → 偵測語言 → 翻譯 → 回覆
   │
   ├─ 中文字元 > 30% → 翻譯成印尼文
   ├─ 偵測為印尼文/馬來文 → 翻譯成中文
   └─ 無法判定 → 不處理
```

## 專案結構

```
/opt/line-translator-bot/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 環境變數配置
│   ├── handlers/
│   │   └── webhook_handler.py  # LINE Webhook 處理
│   └── services/
│       ├── translator.py       # 翻譯服務
│       └── language_detector.py # 語言偵測
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                        # 環境變數（請勿提交）
└── .env.example                # 環境變數範例
```

## 安裝與設定

### 1. 前置需求

- Docker 和 Docker Compose
- LINE Developer 帳號
- Cloudflare Tunnel（或其他提供 HTTPS 的解決方案）

### 2. 複製專案

```bash
git clone https://github.com/matt0taiwan/line-translator-bot.git
cd line-translator-bot
```

### 3. 設定環境變數

複製 `.env.example` 並填入你的 LINE Bot 憑證：

```bash
cp .env.example .env
```

編輯 `.env` 檔案：

```env
LINE_CHANNEL_SECRET=你的_channel_secret
LINE_CHANNEL_ACCESS_TOKEN=你的_channel_access_token
APP_HOST=0.0.0.0
APP_PORT=5000
DEBUG=false
```

### 4. 啟動服務

```bash
docker compose up -d --build
```

### 5. 設定 LINE Developer Console

1. 前往 [LINE Developer Console](https://developers.line.biz/)
2. 選擇你的 Channel
3. 在 **Messaging API** 設定：
   - Webhook URL: `https://你的網址/webhook`
   - 開啟 "Use webhook"
   - 關閉 "Auto-reply messages"
4. 確認 Bot 可以加入群組

### 6. 設定 Cloudflare Tunnel（選用）

如果使用 Cloudflare Tunnel：

```bash
# 安裝 cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# 登入並建立 tunnel
cloudflared tunnel login
cloudflared tunnel create line-bot
cloudflared tunnel route dns line-bot 你的子網域.你的網域.com

# 設定 config.yml
mkdir -p ~/.cloudflared
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

1. 將 Bot 加入 LINE 群組
2. 在群組中發送中文或印尼文訊息
3. Bot 會自動偵測語言並回覆翻譯

### 範例

```
小明：你好嗎？
Bot（顯示小明的頭像）：Apa kabar?

Siti：Selamat pagi
Bot（顯示 Siti 的頭像）：早安
```

## 管理指令

### 查看日誌

```bash
docker compose logs -f
```

### 重啟服務

```bash
docker compose restart
```

### 停止服務

```bash
docker compose down
```

### 更新程式碼

```bash
git pull
docker compose up -d --build
```

## 健康檢查

Bot 提供健康檢查端點：

```bash
curl https://你的網址/health
```

回應：
```json
{
  "status": "healthy",
  "service": "LINE Translator Bot",
  "version": "1.0.0"
}
```

## 疑難排解

### Bot 沒有回應

1. 檢查 Docker 容器狀態：
   ```bash
   docker compose ps
   ```

2. 查看日誌：
   ```bash
   docker compose logs -f
   ```

3. 確認 Webhook URL 設定正確並可從外部存取

### 翻譯品質不佳

deep-translator 使用 Google Translate API，翻譯品質取決於：
- 原文的清晰度
- 語境是否完整
- Google Translate 的演算法

### 無法取得使用者頭像

LINE API 限制：
- 使用者必須同意 Bot 取得個人資料
- 在群組中，某些設定可能阻止 Bot 取得成員資料
- 如果無法取得，Bot 會使用預設頭像

## 授權

MIT License

## 貢獻

歡迎提交 Issue 和 Pull Request！

## 作者

matt0taiwan

## 致謝

- [LINE Messaging API](https://developers.line.biz/en/docs/messaging-api/)
- [deep-translator](https://github.com/nidhaloff/deep-translator)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/)
