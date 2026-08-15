# 🤖 Sultan Assistant (Cloudflare Python Worker)

A modular, serverless, 24/7 private personal assistant and trading analysis platform powered by Google's **Gemini 3.1 Flash-Lite** model and **Cloudflare D1** persistent storage, engineered to run on the **Cloudflare Workers Free plan** (0 VPS, 0 long-running processes, 100% serverless Webhook architecture).

---

## 🔒 Security & Fail-Closed Architecture

Sultan Assistant is built as a **strictly private personal assistant**:

* **Fail-Closed Access Control:** The bot requires `ALLOWED_USER_IDS` to contain at least one valid Telegram user ID. If `ALLOWED_USER_IDS` is missing, empty, or invalid, the bot **denies access to all users** by default.
* **Database & Quota Protection:** Unauthorized requests are rejected immediately at the router level and **never** trigger Google Gemini API calls, database writes, profile creation, or memory/history access.
* **User Isolation:** All session history, user profiles, and long-term memory operations (`SELECT`, `INSERT`, `DELETE`) are strictly scoped by `telegram_user_id` taken from `message.from.id`.
* **Secret Protection:** Webhook calls are validated via `X-Telegram-Bot-Api-Secret-Token`. Health endpoints (`/health`) expose only safe boolean readiness flags and never output secret values, database contents, session messages, or user IDs.

---

## ✨ Features (خصوصیات)
* 💬 **Smart Q&A with Session Continuity (گفتگو کا تسلسل):** Automatic multi-turn conversation history tracking within active sessions, allowing natural follow-ups and context-aware answers using **Gemini 3.1 Flash-Lite**.
* 🧠 **Real Long-Term Memory (مستقل یادداشت):** Store, list, and delete custom facts, goals, and preferences using `/remember`, `/memories`, `/forget`, and `/forgetall`.
* 🎯 **Dynamic Context Injection:** Injects relevant long-term memories and recent active conversation turns into Gemini prompts without requiring vector databases or embeddings.
* 🗨️ **Session History View (`/history`):** View a human-readable summary of recent conversation turns in your current active session.
* 🖼️ **Multimodal Image Vision (تصویر کا تجزیہ):** Send any photo with a prompt/caption to analyze, extract text, or explain its contents using multimodal native vision.
* 💾 **Persistent State & Memory (Cloudflare D1):** User profiles, session history, and extensible memory storage that survive Worker restarts.
* 🆔 **Identity Command (`/id`):** Instantly returns your Telegram numeric user ID directly from webhook metadata without querying Gemini.
* 🩺 **Health & Setup Endpoints:**
  * `GET /health` - Diagnostic endpoint to verify worker status, active model, private mode, database connectivity, and secret configurations without exposing secrets.
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
│   ├── settings.py              # Environment configuration & CONVERSATION_HISTORY_LIMIT = 20
│   └── prompts.py               # Predefined copy, welcome text, and error templates
│
├── storage/                     # Cloudflare D1 persistence layer
│   ├── __init__.py
│   ├── database.py              # D1 database async query client (Pyodide compatible)
│   └── repositories.py          # Repositories for Users, Memories, Settings, and Conversation Sessions
│
├── telegram/                    # Telegram API client & utilities
│   ├── __init__.py
│   ├── client.py                # Async Telegram REST API (sendMessage, sendChatAction, getFile)
│   ├── formatting.py            # Message chunking & Markdown fallback logic
│   └── auth.py                  # Fail-closed user ID whitelist & access control
│
├── router/                      # Routing & dispatching
│   ├── __init__.py
│   ├── command_router.py        # /start, /help, /id, /memory, /history, /remember, /memories, /forget
│   └── message_router.py        # Update dispatcher (commands, text, vision, auth, session history)
│
└── ai/                          # Gemini AI integration
    ├── __init__.py
    ├── gemini_client.py         # Google Gemini 3.1 Flash-Lite REST client
    └── prompts_builder.py       # JSON payload formatting, memory scoring & context separation
```

---

## 📌 Available Bot Commands
* `/remember <text>` - Explicitly save a goal, fact, preference, or instruction to long-term memory.
* `/memories` - List all your stored long-term memories with numbered indexes.
* `/forget <number>` - Delete a specific memory by its list number.
* `/forgetall` - Request deletion of all stored long-term memories (requires `/forgetall_confirm`).
* `/forgetall_confirm` - Permanently delete all stored long-term memories.
* `/history` - View recent conversation turns in your current active session.
* `/memory` - Check assistant memory, user profile, and D1 database state.
* `/id` - View your Telegram numeric user ID.
* `/start` - Welcome message and introduction.
* `/help` - Usage instructions.
* `/clear` or `/reset` - Start a fresh conversation session (does NOT delete long-term memories or profiles).

---

## 🗄️ Database Setup & Migration (Cloudflare D1)

The database schema manages:
1. `user_profiles` — Profile metadata, `first_seen_at`, and `last_seen_at` timestamps.
2. `conversation_memories` — Explicit user long-term memories (goals, preferences, facts).
3. `assistant_settings` — Persistent settings and active session tracking pointer.
4. `conversation_sessions` — Active and historical conversation session records.
5. `conversation_messages` — Recent turns (`user` and `assistant`) scoped by session and user.

### To Apply Database Schema:

```bash
# 1. Create the D1 Database (if not already created):
npx wrangler d1 create sultan-assistant-db

# 2. Execute the Migration Schema:
npx wrangler d1 execute sultan-assistant-db --file=./schema.sql
```

*(Note: If D1 is temporarily offline or unbound, Sultan Assistant gracefully degrades and processes single-turn Q&A without crashing).*

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

#### 4. Configure D1 Database Binding in `wrangler.toml`
Ensure `wrangler.toml` contains your D1 binding:
```toml
[[d1_databases]]
binding = "ASSISTANT_DB"
database_name = "sultan-assistant-db"
database_id = "<your-d1-database-id>"
```

#### 5. Deploy the Worker
```bash
npx wrangler deploy
```
Once deployed, Wrangler will output your worker URL (e.g., `https://gemini-telegram-bot.<your-subdomain>.workers.dev`).

#### 6. Verify Health
Visit your health endpoint in a web browser:
```
https://gemini-telegram-bot.<your-subdomain>.workers.dev/health
```
You should see a JSON response confirming `status: "ok"`, `private_mode: true`, `database_connected: true`, and that your secrets are configured.

#### 7. Register Telegram Webhook (1-Click)
Open the setup endpoint in your browser to automatically register your webhook with Telegram:
```
https://gemini-telegram-bot.<your-subdomain>.workers.dev/set_webhook
```
*(If you configured `SETUP_SECRET`, add `?secret=your_setup_secret` to the URL).*

Telegram will return `{"ok": true, "result": true, "description": "Webhook was set"}`.

Your bot is now live 24/7 on Cloudflare Workers! 🎉

---

## 📁 Repository Structure
```text
.
├── .env.example        # Reference environment variables & secret keys template
├── .gitignore          # Git ignore rules for secrets and build artifacts
├── README.md           # Documentation & deployment guide
├── requirements.txt    # Python runtime requirements
├── schema.sql          # Cloudflare D1 SQL schema migrations (Phase 2 & Phase 4)
├── src/
│   ├── __init__.py     # Core package marker
│   ├── entry.py        # Cloudflare Python Worker lifecycle & HTTP router
│   ├── config/         # Settings, prompts, and constants
│   ├── storage/        # Cloudflare D1 client and data repositories (Users, Memories, Sessions)
│   ├── telegram/       # Async Telegram API client, formatting, and authorization
│   ├── router/         # Command and message dispatcher
│   └── ai/             # Gemini 3.1 Flash-Lite REST integration & memory/history prompt builders
└── wrangler.toml       # Cloudflare Worker configuration
```
