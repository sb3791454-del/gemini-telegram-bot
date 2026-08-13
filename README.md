# 🤖 Gemini Telegram Bot

A 24/7 intelligent Telegram bot powered by Google's latest **Gemini 2.5 Flash** model.

## ✨ Features (خصوصیات)
* 💬 **Smart Q&A (ذہین سوال و جواب):** Answers general knowledge, coding, math, essays, writing, and language learning questions.
* 🖼️ **Multimodal Image Vision (تصویر کا تجزیہ):** Send any image with a prompt or question to analyze, explain, or extract text from it.
* 🧠 **Conversational Memory (چیٹ ہسٹری یاد رکھنا):** Keeps context across continuous messages in a conversation.
* 🔄 **Custom Commands:**
  * `/start` - Start the bot & view introduction.
  * `/help` - View help & usage instructions.
  * `/clear` or `/reset` - Clear chat memory and start a fresh session.
* 🚀 **24/7 Ready:** Ready for 1-click free deployment on Render, Railway, Koyeb, or Docker.

---

## 🛠️ Environment Variables (ضروری متغیرات)
Create a `.env` file (or set them in your cloud hosting dashboard):

| Variable | Description |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Your Telegram Bot Token from [@BotFather](https://t.me/BotFather) |
| `GEMINI_API_KEY` | Your Gemini API Key from [Google AI Studio](https://aistudio.google.com/) |

---

## ☁️ How to Deploy 24/7 for Free (24/7 چلانے کا طریقہ)

### Option 1: Render (Recommended - Free)
1. Sign up / Log in to [Render](https://render.com/).
2. Click **New +** and choose **Background Worker** (or **Web Service**).
3. Connect your GitHub repository: `sb3791454-del/gemini-telegram-bot`.
4. Set **Runtime** to `Python 3` (or `Docker`).
5. Set **Start Command** to: `python bot.py`.
6. Under **Environment Variables**, add:
   * `TELEGRAM_BOT_TOKEN` = `your_telegram_bot_token`
   * `GEMINI_API_KEY` = `your_gemini_api_key`
7. Click **Deploy**. Your bot will be online 24/7!

### Option 2: Railway
1. Sign up / Log in to [Railway](https://railway.app/).
2. Click **New Project** -> **Deploy from GitHub repo**.
3. Select `gemini-telegram-bot`.
4. Go to **Variables** and add `TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY`.
5. Railway will automatically build and keep the bot running 24/7.

---

## 💻 Running Locally (اپنے کمپیوٹر پر چلانا)

1. Clone the repository:
   ```bash
   git clone https://github.com/sb3791454-del/gemini-telegram-bot.git
   cd gemini-telegram-bot
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # On Linux / Mac:
   source venv/bin/activate
   # On Windows:
   venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in your keys:
   ```bash
   cp .env.example .env
   ```
5. Run the bot:
   ```bash
   python bot.py
   ```
