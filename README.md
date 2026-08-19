# 🤖 Sultan Assistant (Cloudflare Python Worker)

A modular, serverless, 24/7 private personal trading-intelligence and education platform powered by Google's **Gemini 3.1 Flash-Lite** model, **Cloudflare D1** persistent storage, and a **High-Availability Multi-Exchange Market Engine**, engineered to run on the **Cloudflare Workers Free plan** (0 VPS, 0 long-running processes, 100% serverless Webhook architecture).

---

## 🔒 Security & Fail-Closed Architecture

Sultan Assistant is built as a **strictly private personal assistant**:

* **Fail-Closed Access Control:** The bot requires `ALLOWED_USER_IDS` to contain at least one valid Telegram user ID. If `ALLOWED_USER_IDS` is missing, empty, or invalid, the bot **denies access to all users** by default.
* **Database & Quota Protection:** Unauthorized requests are rejected immediately at the router level and **never** trigger Google Gemini API calls, database writes, profile creation, or memory/history access.
* **User Isolation:** All session history, user profiles, watchlists, and long-term memory operations (`SELECT`, `INSERT`, `DELETE`) are strictly scoped by `telegram_user_id` taken from `message.from.id`.
* **Zero Hallucination Policy:** Real-time market prices, candlestick data, and technical indicators are computed deterministically from verified live feeds (Binance, Bybit, OKX, KuCoin) with strict error sanitization. Gemini is never allowed to fabricate numerical market values.

---

## ✨ Features (خصوصیات)

* 📊 **Live Multi-Exchange Market Engine (لائیو مارکیٹ ریٹس):** Live spot prices (`/price`), 24h ticker metrics (`/ticker`), and top order-book depth (`/depth`) backed by a resilient waterfall (Binance cluster $\rightarrow$ Bybit $\rightarrow$ OKX $\rightarrow$ KuCoin).
* 📈 **Deterministic Technical Analysis (`/ta`):** Instant multi-timeframe (`15m`, `1h`, `4h`, `1d`) technical calculations:
  * **RSI-14:** Wilder-smoothed Relative Strength Index with overbought/oversold classification.
  * **EMAs:** Trailing 20, 50, and 200 Exponential Moving Averages for trend direction and cross detection.
  * **Bollinger Bands (20, 2σ):** Upper, middle, lower bands, and volatility bandwidth percentage.
  * **ATR-14:** Average True Range volatility with recommended dynamic Stop-Loss buffers (1.5x ATR).
  * **Support & Resistance:** Trailing price pivot extremes.
* 🛡️ **Position Sizing & Risk Management (`/risk`):** Exact mathematical position sizing based on Capital Preservation First:
  * Calculates maximum dollar risk budget, recommended quantity in coins and USD, and effective leverage.
  * Generates structured Take-Profit targets based on Risk-to-Reward ratios (1:1.5, 1:2.0, 1:3.0 R:R).
  * Enforces safety warnings against high-risk allocations (>3%) and dangerous leverage (>10x).
* ⭐ **Personal Crypto Watchlist (`/watchlist`):** Add (`/watch <symbol>`) and remove (`/unwatch <symbol>`) favorite assets stored persistently in Cloudflare D1 with instant multi-asset live summaries.
* 🧠 **Live Market-Grounded AI Intelligence:** Automatically detects crypto assets in natural language queries and injects verified live market context into Gemini prompts to eliminate LLM hallucinations.
* 💬 **Smart Q&A with Session Continuity (گفتگو کا تسلسل):** Automatic multi-turn conversation history tracking within active sessions (`/history`, `/clear`).
* 🧠 **Persistent Long-Term Memory (مستقل یادداشت):** Store, list, and delete custom facts, goals, and trading rules using `/remember`, `/memories`, `/forget`, and `/forgetall`.
* 🖼️ **Multimodal Image Vision (تصویر کا تجزیہ):** Send any trading chart or photo with a caption to analyze structures or patterns.
* 💾 **Persistent State & Memory (Cloudflare D1):** User profiles, session history, watchlists, and memories that survive Worker restarts.
* 🆔 **Identity Command (`/id`):** Instantly returns your Telegram numeric user ID directly from webhook metadata.

---

## 📌 Available Bot Commands

| Category | Command | Description | Example |
| :--- | :--- | :--- | :--- |
| **Market Data** | `/price <symbol>` | Live spot price with multi-exchange fallback | `/price BTCUSDT` or `/price SOL` |
| **Market Data** | `/ticker <symbol>` | 24h high, low, volume, and percentage change | `/ticker ETHUSDT` |
| **Market Data** | `/depth <symbol>` | Top 5 bids and asks order book depth | `/depth BTCUSDT` |
| **Trading Intelligence** | `/ta <symbol> [tf]` | Technical indicators (RSI, EMA, BB, ATR, S/R) | `/ta BTCUSDT 1h` or `/ta SOL 4h` |
| **Risk Management** | `/risk <cap> <r%> <e> <sl>` | Position sizing & 1:1.5, 1:2, 1:3 TP levels | `/risk 1000 2 65000 63500` |
| **Watchlist** | `/watch <symbol>` | Add asset to personal D1 watchlist | `/watch SOL` |
| **Watchlist** | `/unwatch <symbol>` | Remove asset from watchlist | `/unwatch SOL` |
| **Watchlist** | `/watchlist` or `/wl` | View live prices of all watched assets | `/watchlist` |
| **Memory** | `/remember <text>` | Save rule, goal, or preference to memory | `/remember Maximum risk per trade is 1.5%` |
| **Memory** | `/memories` | List all stored long-term memories | `/memories` |
| **Memory** | `/forget <num>` | Delete specific memory by number | `/forget 2` |
| **Memory** | `/forgetall` | Clear all long-term memories | `/forgetall` (confirms with `/forgetall_confirm`) |
| **Session** | `/history` | View recent turns in active session | `/history` |
| **Session** | `/clear` or `/reset` | Start fresh session (preserves memories & watchlist) | `/clear` |
| **System** | `/memory` | D1 database and storage connection status | `/memory` |
| **System** | `/id` | View Telegram Numeric User ID | `/id` |
| **System** | `/help` | Detailed command and usage guide | `/help` |
| **System** | `/start` | Bot welcome message and overview | `/start` |

---

## 🏗️ Architecture Overview

```text
src/
├── entry.py                     # Cloudflare Worker lifecycle & HTTP request routing
│
├── config/                      # Settings, constants, and prompts
│   ├── __init__.py
│   ├── settings.py              # Environment configuration & limits
│   └── prompts.py               # Predefined copy, welcome text, trading constitution
│
├── storage/                     # Cloudflare D1 persistence layer
│   ├── __init__.py
│   ├── database.py              # D1 database async query client (Pyodide compatible)
│   └── repositories.py          # Repositories for Users, Memories, Sessions, and Watchlists
│
├── telegram/                    # Telegram API client & utilities
│   ├── __init__.py
│   ├── client.py                # Async Telegram REST API (sendMessage, sendChatAction, getFile)
│   ├── formatting.py            # Message chunking & Markdown fallback logic
│   └── auth.py                  # Fail-closed user ID whitelist & access control
│
├── router/                      # Routing & dispatching
│   ├── __init__.py
│   ├── command_router.py        # Slash commands (/price, /ta, /risk, /watch, /watchlist, /memories...)
│   └── message_router.py        # Update dispatcher (commands, vision, AI market grounding, sessions)
│
├── ai/                          # Gemini AI integration
│   ├── __init__.py
│   ├── gemini_client.py         # Google Gemini 3.1 Flash-Lite REST client
│   └── prompts_builder.py       # Live market grounding, memory scoring & context separation
│
└── trading/                     # Market Data, Technical Analysis & Risk Management
    ├── __init__.py
    ├── models.py                # Data models (PriceTicker, Ticker24h, Depth, Candle, TA, Risk)
    ├── binance_client.py        # Resilient multi-exchange REST client (Binance/Bybit/OKX/KuCoin)
    ├── technical_analysis.py    # Pure-Python RSI-14, EMA 20/50/200, Bollinger Bands, ATR calculations
    └── risk_calculator.py       # Deterministic position sizing and risk-to-reward targets
```

---

## 🗄️ Database Setup & Migration (Cloudflare D1)

The database schema manages:
1. `user_profiles` — Profile metadata, `first_seen_at`, and `last_seen_at` timestamps.
2. `conversation_memories` — Explicit user long-term memories (goals, preferences, facts).
3. `assistant_settings` — Persistent settings and active session tracking pointer.
4. `conversation_sessions` — Active and historical conversation session records.
5. `conversation_messages` — Recent turns (`user` and `assistant`) scoped by session and user.
6. `user_watchlist` — Persistent tracked assets per user.

### To Apply Database Schema:

```bash
# Execute the Migration Schema:
npx wrangler d1 execute sultan-assistant-db --file=./schema.sql
```

---

## 🚀 Deployment Instructions

### Method 1: Deploy using Wrangler CLI
```bash
git clone https://github.com/sb3791454-del/gemini-telegram-bot.git
cd gemini-telegram-bot
npx wrangler deploy
```

#### Verification:
Visit `https://gemini-telegram-bot.<your-subdomain>.workers.dev/health` to confirm system status.
