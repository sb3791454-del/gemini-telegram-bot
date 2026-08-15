# 🤖 Sultan Assistant (Cloudflare Python Worker)

A modular, serverless, 24/7 private personal assistant and trading analysis platform powered by Google's **Gemini 3.1 Flash-Lite** model and **Cloudflare D1** persistent storage, engineered to run on the **Cloudflare Workers Free plan** (0 VPS, 0 long-running processes, 100% serverless Webhook architecture).

---

## 🔒 Security & Fail-Closed Architecture

Sultan Assistant is built as a **strictly private personal assistant**:

* **Fail-Closed Access Control:** The bot requires `ALLOWED_USER_IDS` to contain at least one valid Telegram user ID. If `ALLOWED_USER_IDS` is missing, empty, or invalid, the bot **denies access to all users** by default.
* **Database & Quota Protection:** Unauthorized requests are rejected immediately at the router level and **never** trigger Google Gemini API calls, database writes, or profile/memory access.
* **Secret Protection:** Webhook calls are validated via `X-Telegram-Bot-Api-Secret-Token`. Health endpoints (`/health`) expose only safe boolean readiness flags and never output secret values, database contents, or user IDs.

---

## ✨ Features (خصوصیات)
* 💬 **Smart Q&A (ذہین سوال و جواب):** Fast and accurate answers for general knowledge, writing, translation, math, and coding questions using **Gemini 3.1 Flash-Lite**.
* 🧠 **Real Long-Term Memory (مستقل یادداشت):** Store, list, and delete custom facts, goals, and preferences using `/remember`, `/memories`, `/forget`, and `/forgetall`.
* 🎯 **Dynamic Context Injection:** Automatically injects relevant memories into Gemini prompts using pure Python keyword overlap scoring (zero vector DB costs).
* 🖼️ **Multimodal Image Vision (تصویر کا تجزیہ):** Send any photo with a prompt/caption to analyze, extract text, or explain its contents using multimodal native vision.
* 💾 **Persistent State & Memory (Cloudflare D1):** User profiles, activity timestamps, preferences, and extensible memory storage.
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
│   ├── settings.py              # Environment configuration & ALLOWED_USER_IDS parser
│   └── prompts.py               # Predefined copy, welcome text, and error templates
│
├── storage/                     # Cloudflare D1 persistence layer
│   ├── __init__.py
│   ├── database.py              # D1 database async query client (Pyodide compatible)
│   └── repositories.py          # Repositories for User Profiles, Memories, and Settings
│
├── telegram/                    # Telegram API client & utilities
│   ├── __init__.py
│   ├── client.py                # Async Telegram REST API (sendMessage, sendChatAction, getFile)
│   ├── formatting.py            # Message chunking & Markdown fallback logic
│   └── auth.py                  # Fail-closed user ID whitelist & access control
│
├── router/                      # Routing & dispatching
│   ├── __init__.py
│   ├── command_router.py        # /start, /help, /id, /memory, /remember, /memories, /forget, /forgetall
│   └── message_router.py        # Update dispatcher (commands, text, vision, auth, memory injection)
│
└── ai/                          # Gemini AI integration
    ├── __init__.py
    ├── gemini_client.py         # Google Gemini 3.1 Flash-Lite REST client
    └── prompts_builder.py       # JSON payload formatting & keyword relevance scoring
```

---

## 📌 Available Bot Commands
* `/remember <text>` - Explicitly save a goal, fact, preference, or instruction to long-term memory.
* `/memories` - List all your stored long-term memories with numbered indexes.
* `/forget <number>` - Delete a specific memory by its list number.
* `/forgetall` - Request deletion of all stored long-term memories (requires `/forgetall_confirm`).
* `/forgetall_confirm` - Permanently delete all stored long-term memories.
* `/memory` - Check assistant memory, user profile, and D1 database state.
* `/id` - View your Telegram numeric user ID.
* `/start` - Welcome message and introduction.
* `/help` - Usage instructions.
* `/clear` or `/reset` - Start a fresh conversation session (does not delete long-term memories).

---

## 🗄️ Database Setup (Cloudflare D1)

To bind Cloudflare D1 to Sultan Assistant:

1. **Create the D1 Database:**
   ```bash
   npx wrangler d1 create sultan-assistant-db
   ```
2. **Execute Database Migration Schema:**
   ```bash
   npx wrangler d1 execute sultan-assistant-db --file=./schema.sql
   ```
3. **Add D1 Binding to `wrangler.toml` (or Cloudflare Dashboard):**
   ```toml
   [[d1_databases]]
   binding = "ASSISTANT_DB"
   database_name = "sultan-assistant-db"
   database_id = "<your-d1-database-id>"
   ```
*(Note: If D1 is not bound, Sultan Assistant operates in graceful ephemeral mode without crashing).*

---

## 📁 Repository Structure
```text
.
├── .env.example        # Reference environment variables & secret keys template
├── .gitignore          # Git ignore rules for secrets and build artifacts
├── README.md           # Documentation & deployment guide
├── requirements.txt    # Python runtime requirements
├── schema.sql          # Cloudflare D1 SQL schema migrations
├── src/
│   ├── __init__.py     # Core package marker
│   ├── entry.py        # Cloudflare Python Worker lifecycle & HTTP router
│   ├── config/         # Settings, prompts, and constants
│   ├── storage/        # Cloudflare D1 client and data repositories
│   ├── telegram/       # Async Telegram API client, formatting, and authorization
│   ├── router/         # Command and message dispatcher
│   └── ai/             # Gemini 3.1 Flash-Lite REST integration & memory matcher
└── wrangler.toml       # Cloudflare Worker configuration
```
