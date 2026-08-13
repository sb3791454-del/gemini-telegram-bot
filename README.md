# 🤖 Gemini Telegram Bot (Cloudflare Python Worker)

A serverless, 24/7 Telegram bot powered by Google's **Gemini 2.0 Flash** model, built to run on the **Cloudflare Workers Free plan** (0 VPS, 0 long-running processes, 100% serverless Webhook architecture).

---

## ✨ Features (خصوصیات)
* 💬 **Smart Q&A (ذہین سوال و جواب):** Fast and accurate answers for general knowledge, writing, translation, math, and coding questions using **Gemini 2.0 Flash**.
* 🖼️ **Multimodal Image Vision (تصویر کا تجزیہ):** Send any photo with a prompt/caption to analyze, extract text, or explain its contents.
* ⚡ **100% Serverless Webhook Architecture:** Zero idle memory/CPU consumption, event-driven responses on Telegram updates.
* 🔒 **Secure Secrets Management:** All API keys and tokens are securely managed via Cloudflare Worker Secrets (never committed to Git).
* 🛡️ **Webhook Security:** Supports Telegram's `X-Telegram-Bot-Api-Secret-Token` verification.
* 🔄 **Customizable Model:** Defaults to `gemini-2.0-flash` (with automated fallback to `gemini-1.5-flash`), configurable via `GEMINI_MODEL` secret/variable.
* 🩺 **Health & Setup Endpoints:**
  * `GET /health` - Diagnostic endpoint to verify worker status, active model, and secret configurations.
  * `GET /set_webhook` - Automated 1-click webhook registration with Telegram.
  * `POST /webhook` - Handles incoming Telegram webhook updates.

---

## 📋 Prerequisites
1. **Cloudflare Account:** Sign up for free at [dash.cloudflare.com](https://dash.cloudflare.com/).
2. **Telegram Bot Token:** Create a bot with [@BotFather](https://t.me/BotFather) on Telegram and copy the token.
3. **Gemini API Key:** Get a free API key from [Google AI Studio](https://aistudio.google.com/).
4. **Node.js / npm:** (Optional, if deploying via Wrangler CLI) Installed on your machine.

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

# (Optional) Add a custom Webhook Secret for extra security
npx wrangler secret put WEBHOOK_SECRET

# (Optional) Add a Setup Secret to protect the /set_webhook endpoint
npx wrangler secret put SETUP_SECRET

# (Optional) Override the default model (defaults to gemini-2.0-flash)
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
You should see a JSON response confirming `status: "ok"`, the active model `gemini-2.0-flash`, and that your secrets are configured.

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
   * (Optional) Add Secret: `WEBHOOK_SECRET`
   * (Optional) Add Secret: `SETUP_SECRET`
   * (Optional) Add Variable: `GEMINI_MODEL` (value: `gemini-2.0-flash`)
5. Go to **Settings > Compatibility Flags** and ensure `python_workers` compatibility is enabled with date `2024-04-03` or later.
6. Click **Edit Code**, paste the code from `src/entry.py`, and click **Deploy**.
7. Open `https://gemini-telegram-bot.<your-subdomain>.workers.dev/set_webhook` to activate the Telegram webhook.

---

## 📌 Available Bot Commands
* `/start` - Welcome message and introduction.
* `/help` - Usage instructions.
* `/clear` or `/reset` - Start a fresh conversation.

---

## 📁 Repository Structure
```text
.
├── .env.example        # Reference environment variables
├── .gitignore          # Git ignore rules for secrets and build artifacts
├── README.md           # Documentation & deployment guide
├── requirements.txt    # Python runtime requirements
├── src/
│   ├── __init__.py     # Python package marker
│   └── entry.py        # Cloudflare Python Worker webhook entrypoint
└── wrangler.toml       # Cloudflare Worker configuration
```
