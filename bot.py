import os
import io
import logging
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from google import genai
from PIL import Image
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in environment variables.")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in environment variables.")

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Initialize Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

# In-memory chat sessions storage: {user_id: chat_session}
user_chats = {}

def get_or_create_chat(user_id: int):
    if user_id not in user_chats:
        user_chats[user_id] = client.chats.create(model="gemini-2.5-flash")
    return user_chats[user_id]

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_chats[user_id] = client.chats.create(model="gemini-2.5-flash")
    welcome_text = (
        "👋 **السلام علیکم! Welcome to Gemini AI Bot!**\n\n"
        "میں Google Gemini سے چلنے والا ایک ذہین اسسٹنٹ ہوں۔\n\n"
        "✨ **میں کیا کر سکتا ہوں؟ (Features):**\n"
        "• **سوال و جواب (Q&A):** کسی بھی موضوع پر سوالات کے تفصیلی جوابات۔\n"
        "• **تصویر کا تجزیہ (Image Analysis):** مجھے کوئی تصویر بھیجیں اور اس کے بارے میں پوچھیں۔\n"
        "• **ترجمہ اور تحریر (Writing & Translation):** اردو، انگریزی اور دیگر زبانوں میں مضامین، ای میلز اور کوڈنگ۔\n"
        "• **بات چیت یاد رکھنا (Memory):** پچھلی گفتگو کو یاد رکھتے ہوئے جواب دینا۔\n\n"
        "📌 **کمانڈز (Commands):**\n"
        "/help - تفصیلی رہنمائی\n"
        "/clear - نئی چیٹ شروع کریں (Clear Chat Memory)\n\n"
        "بس اپنا سوال یا تصویر یہاں بھیجیں!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **بوٹ استعمال کرنے کا طریقہ (Help Guide):**\n\n"
        "1. **ٹیکسٹ میسج:** براہ راست کوئی بھی سوال لکھ کر بھیجیں۔\n"
        "2. **تصویر:** تصویر بھیجیں اور کیپشن میں اپنا سوال لکھیں (مثلاً: 'اس تصویر کی وضاحت کریں')۔\n"
        "3. **نئی گفتگو:** اگر آپ پرانی چیٹ کو صاف کر کے نئی گفتگو شروع کرنا چاہتے ہیں تو /clear لکھیں۔\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_chats[user_id] = client.chats.create(model="gemini-2.5-flash")
    await update.message.reply_text("🔄 چیٹ ہسٹری صاف کر دی گئی ہے۔ اب آپ نئی گفتگو شروع کر سکتے ہیں۔")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Send typing action
    await update.message.chat.send_action(action=ChatAction.TYPING)
    
    chat_session = get_or_create_chat(user_id)
    try:
        response = chat_session.send_message(user_message)
        reply_text = response.text or "معذرت، کوئی جواب حاصل نہیں ہو سکا۔"
        await update.message.reply_text(reply_text)
    except Exception as e:
        logger.error(f"Error generating text response: {e}")
        # Reset session if state became inconsistent
        user_chats[user_id] = client.chats.create(model="gemini-2.5-flash")
        await update.message.reply_text("⚠️ معذرت، جواب تیار کرنے میں کوئی مسئلہ پیش آیا۔ براہ کرم دوبارہ کوشش کریں۔")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Send typing action
    await update.message.chat.send_action(action=ChatAction.TYPING)
    
    caption = update.message.caption or "اس تصویر کے بارے میں تفصیل سے بتائیں۔"
    photo_file = await update.message.photo[-1].get_file()
    
    # Download photo into memory
    photo_bytes = await photo_file.download_as_bytearray()
    image = Image.open(io.BytesIO(photo_bytes))
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[image, caption],
        )
        reply_text = response.text or "تصویر کا تجزیہ مکمل نہیں ہو سکا۔"
        await update.message.reply_text(reply_text)
    except Exception as e:
        logger.error(f"Error analyzing image: {e}")
        await update.message.reply_text("⚠️ تصویر کا تجزیہ کرنے میں مسئلہ پیش آیا۔ براہ کرم دوبارہ بھیجیں۔")

def main():
    logger.info("Starting Gemini Telegram Bot...")
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("reset", clear_command))
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.run_polling()

if __name__ == "__main__":
    main()
