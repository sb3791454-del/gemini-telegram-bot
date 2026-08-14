# 🤖 Sultan Assistant (Cloudflare Python Worker)

A modular, serverless, 24/7 private personal assistant and trading analysis platform powered by Google's **Gemini 3.1 Flash-Lite** model, engineered to run on the **Cloudflare Workers Free plan** (0 VPS, 0 long-running processes, 100% serverless Webhook architecture).

---

## 🔒 Security & Fail-Closed Architecture

Sultan Assistant is built as a **strictly private personal assistant**:

* **Fail-Closed Access Control:** The bot requires `ALLOWED_USER_IDS` to contain at least one valid Telegram user ID. If `ALLOWED_USER_IDS` is missing, empty, or invalid, the bot **denies access to all users** by default.
* **Quota Protection:** Unauthorized requests are rejected immediately at the router level and **never** trigger Google Gemini API calls or consume token quotas.
* **Secret Protection:** Webhook calls are validated via `X-Telegram-Bot-Api-Secret-Token`. Health endpoints (`/health`) expose only safe boolean readiness flags and never output secret values or user IDs.

---

## ✨ Features (خصوصیات)
* 💬 **Smart Q&A (ذہین سوال و جواب):** Fast and accurate answers for general knowledge, writing, translation, math, and coding questions using **Gemini 3.1 Flash-Lite**.
* 🖼️ **Multimodal Image Vision (تصویر کا تجزیہ):** Send any photo with a prompt/caption to analyze, extract text, or explain its contents using multimodal native vision.
* 🆔 **Identity Command (`/id`):** Instantly returns your Telegram numeric user ID directly from webhook metadata without querying Gemini.
* 🔒 **Private User Whitelist:** Enforced user authorization whitelist (`ALLOWED_USER_IDS`) with fail-closed security.
* ⚡ **100% Serverless Webhook Architecture:** Zero idle memory/CPU consumption, event-driven responses on Telegram updates.
* 🛡️ **Webhook Security:** Supports Telegram's `X-Telegram-Bot-Api-Secret-Token` verification and protected `/set_webhook` setup.
* 🔄 **Modular Architecture:** Clean decoupled modules (`config/`, `telegram/`, `router/`, `ai/`) prepared for future trading analysis modules.
* 🩺 **Health & Setup Endpoints:**
  * `GET /health` - Diagnostic endpoint to verify worker status, active model, private mode status, and secret configurations without exposing secrets.
  * `GET /set_webhook` - Automated 1-click webhook registration with Telegram.
  * `POST /webhook` - Handles incoming Telegram webhook updates.

---

## 🏗️ Architecture Overview

```text
src/
├── entry.py                     # Cloudflare Worker lifecycle & HTTP request routing
│
├── config/                      # Settings, constants, and prompts
│   ├── __init__.py
│   ├── settings.py              # Environment configuration & ALLOWED_USER_IDS parser
│   └── prompts.py               # Predefined copy, welcome text, and error templates
│
├── telegram/                    # Telegram API client & utilities
│   ├── __init__.py
│   ├── client.py                # Async Telegram REST API (sendMessage, sendChatAction, getFile)
│   ├── formatting.py            # Message chunking & Markdown fallback logic
│   └── auth.py                  # Fail-closed user ID whitelist & access control
│
├── router/                      # Routing & dispatching
│   ├── __init__.py
│   ├── command_router.py        # /start, /help, /id, /clear, /reset command execution
│   └── message_router.py        # Update dispatcher (commands, text, vision, auth gatekeeper)
│
└── ai/                          # Gemini AI integration
    ├── __init__.py
    ├── gemini_client.py         # Google Gemini 3.1 Flash-Lite REST client
    └── prompts_builder.py       # JSON payload formatting for text & multimodal requests
```

---

## 📋 Prerequisites
1. **Cloudflare Account:** Sign up for free at [dash.cloudflare.com](https://dash.cloudflare.com/).
2. **Telegram Bot Token:** Create a bot with [@BotFather](https://t.me/BotFather) on Telegram and copy the token.
3. **Gemini API Key:** Get a free API key from [Google AI Studio](https://aistudio.google.com/).
4. **Your Telegram User ID:** Get your numeric Telegram ID (e.g. from [@userinfobot](https://t.me/userinfobot) or by sending `/id` once authorized).
5. **Node.js / npm:** (Optional, if deploying via Wrangler CLI) Installed on your machine.

---

## 🚀 Deployment Instructions (مرحلہ وار ڈپلائمنٹ)

### Method 1: Deploy using Wrangler CLI (Recommended)

#### 1. Clone the repository
```bash
git clone https://github.com/sb3791454-del/gemini-telegram-bot.git
cd gemini-telegram-bot
```

#### 2. Login to Cloudflare
```bash
npx wrangler login
```

#### 3. Configure Worker Secrets
Run the following commands to add your tokens securely to Cloudflare:
```bash
# Add Telegram Bot Token (from @BotFather)
npx wrangler secret put TELEGRAM_BOT_TOKEN

# Add Gemini API Key (from Google AI Studio)
npx wrangler secret put GEMINI_API_KEY

# Add your Telegram User ID (Required to grant access; comma-separated for multiple IDs)
npx wrangler secret put ALLOWED_USER_IDS

# (Optional) Add a custom Webhook Secret for extra security
npx wrangler secret put WEBHOOK_SECRET

# (Optional) Add a Setup Secret to protect the /set_webhook endpoint
npx wrangler secret put SETUP_SECRET

# (Optional) Override the default model (defaults to gemini-3.1-flash-lite)
# npx wrangler secret put GEMINI_MODEL
```

#### 4. Deploy the Worker
```bash
npx wrangler deploy
```
Once deployed, Wrangler will output your worker URL (e.g., `https://gemini-telegram-bot.<your-subdomain>.workers.dev`).

#### 5. Verify Health
Visit your health endpoint in a web browser:
```
https://gemini-telegram-bot.<your-subdomain>.workers.dev/health
```
You should see a JSON response confirming `status: "ok"`, `private_mode: true`, and that your secrets are configured.

#### 6. Register Telegram Webhook (1-Click)
Open the setup endpoint in your browser to automatically register your webhook with Telegram:
```
https://gemini-telegram-bot.<your-subdomain>.workers.dev/set_webhook
```
*(If you configured `SETUP_SECRET`, add `?secret=your_setup_secret` to the URL).*

Telegram will return `{"ok": true, "result": true, "description": "Webhook was set"}`.

Your bot is now live 24/7 on Cloudflare Workers! 🎉

---

### Method 2: Deploy via Cloudflare Dashboard (No CLI required)

1. Open the [Cloudflare Dashboard](https://dash.cloudflare.com/) and go to **Compute (Workers) > Workers & Pages**.
2. Click **Create Application** > **Create Worker**.
3. Name your worker `gemini-telegram-bot` and click **Deploy**.
4. In the worker settings, go to **Settings > Variables and Secrets**:
   * Add Secret: `TELEGRAM_BOT_TOKEN`
   * Add Secret: `GEMINI_API_KEY`
   * Add Secret: `ALLOWED_USER_IDS` (e.g., `123456789`)
   * (Optional) Add Secret: `WEBHOOK_SECRET`
   * (Optional) Add Secret: `SETUP_SECRET`
   * (Optional) Add Variable: `GEMINI_MODEL` (value: `gemini-3.1-flash-lite`)
5. Go to **Settings > Compatibility Flags** and ensure `python_workers` compatibility is enabled with date `2024-04-03` or later.
6. Upload or paste the modular source files under `src/` and click **Deploy**.
7. Open `https://gemini-telegram-bot.<your-subdomain>.workers.dev/set_webhook` to activate the Telegram webhook.

---

## 📌 Available Bot Commands
* `/id` - View your Telegram numeric user ID.
* `/start` - Welcome message and introduction.
* `/help` - Usage instructions.
* `/clear` or `/reset` - Start a fresh conversation.

---

## 📁 Repository Structure
```text
.
├── .env.example        # Reference environment variables & secret keys template
├── .gitignore          # Git ignore rules for secrets and build artifacts
├── README.md           # Documentation & deployment guide
├── requirements.txt    # Python runtime requirements
├── src/
│   ├── __init__.py     # Core package marker
│   ├── entry.py        # Cloudflare Python Worker lifecycle & HTTP router
│   ├── config/         # Settings, prompts, and constants
│   ├── telegram/       # Async Telegram API client, formatting, and authorization
│   ├── router/         # Command and message dispatcher
│   └── ai/             # Gemini 3.1 Flash-Lite REST integration and payload builders
└── wrangler.toml       # Cloudflare Worker configuration
```
