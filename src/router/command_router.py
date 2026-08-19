"""Command router for Telegram bot slash commands with deterministic execution."""

import re
import logging
from typing import Optional, Tuple
from telegram.client import TelegramClient
from config.prompts import WELCOME_TEXT, HELP_TEXT, RESET_TEXT
from storage.repositories import UserRepository, MemoryRepository, ConversationRepository, infer_memory_type
from trading.binance_client import BinanceClient, BinanceAPIError
from trading.models import PriceTicker, Ticker24h, OrderBookDepth

logger = logging.getLogger("worker.router.commands")

def parse_command_and_args(raw_text: str) -> Tuple[Optional[str], str]:
    """
    Robustly parses command and arguments from raw message text.
    Handles:
    - /price BTCUSDT
    - /price btcusdt
    - /price@BOT_USERNAME BTCUSDT
    - Leading/trailing whitespace and multiple spaces
    
    Returns (command_name_lower, argument_string_stripped).
    e.g. '/price@sultan_bot  BTCUSDT ' -> ('/price', 'BTCUSDT')
    """
    if not raw_text:
        return None, ""
    
    trimmed = raw_text.strip()
    if not trimmed.startswith("/"):
        return None, ""
    
    # Match /cmd or /cmd@botname followed optionally by whitespace and arguments
    match = re.match(r"^/([a-zA-Z0-9_]+)(?:@[\w_]+)?(?:\s+(.*))?$", trimmed, re.DOTALL)
    if not match:
        return None, ""
    
    cmd_name = "/" + match.group(1).lower()
    args = match.group(2).strip() if match.group(2) else ""
    return cmd_name, args

def format_price_message(ticker: PriceTicker) -> str:
    price_val = ticker.price
    if price_val >= 1.0:
        price_str = f"{price_val:,.2f}" if price_val >= 100 else f"{price_val:,.4f}"
    else:
        price_str = f"{price_val:.8f}".rstrip("0").rstrip(".")
        
    source_name = getattr(ticker, 'source', 'Binance Spot')
    return (
        f"📊 *{ticker.symbol} Live Price*\n"
        f"• *Price:* `${price_str}`\n"
        f"• *Source:* {source_name} (Verified)\n"
        f"• *UTC Time:* `{ticker.timestamp}`"
    )

def format_ticker_message(t: Ticker24h) -> str:
    change_sign = "+" if t.price_change >= 0 else ""
    change_emoji = "🟢" if t.price_change >= 0 else "🔴"
    
    if t.last_price >= 1.0:
        price_str = f"{t.last_price:,.2f}" if t.last_price >= 100 else f"{t.last_price:,.4f}"
        high_str = f"{t.high_price:,.2f}" if t.high_price >= 100 else f"{t.high_price:,.4f}"
        low_str = f"{t.low_price:,.2f}" if t.low_price >= 100 else f"{t.low_price:,.4f}"
    else:
        price_str = f"{t.last_price:.8f}".rstrip("0").rstrip(".")
        high_str = f"{t.high_price:.8f}".rstrip("0").rstrip(".")
        low_str = f"{t.low_price:.8f}".rstrip("0").rstrip(".")
        
    source_name = getattr(t, 'source', 'Binance Spot')
    return (
        f"📈 *{t.symbol} 24h Ticker Summary*\n"
        f"• *Last Price:* `${price_str}`\n"
        f"• *24h Change:* {change_emoji} `{change_sign}{t.price_change_percent:.2f}%` ({change_sign}${t.price_change:,.4f})\n"
        f"• *24h High:* `${high_str}`\n"
        f"• *24h Low:* `${low_str}`\n"
        f"• *24h Base Volume:* `{t.volume:,.2f}`\n"
        f"• *24h Quote Volume:* `${t.quote_volume:,.2f} USDT`\n"
        f"• *Source:* {source_name} (Verified)\n"
        f"• *UTC Time:* `{t.timestamp}`"
    )

def format_depth_message(d: OrderBookDepth) -> str:
    source_name = getattr(d, 'source', 'Binance Order Book')
    lines = [
        f"📖 *{d.symbol} Order Book Depth (Top 5)*\n"
        f"• *Best Bid:* `${d.best_bid:,.4f}`\n"
        f"• *Best Ask:* `${d.best_ask:,.4f}`\n"
        f"• *Spread:* `${d.spread:,.4f}` (`{d.spread_percentage:.3f}%`)\n",
        "*Asks (Sellers):*"
    ]
    for p, q in reversed(d.asks):
        lines.append(f"  🔴 `${p:,.4f}` — `{q:,.4f}`")
    lines.append("\n*Bids (Buyers):*")
    for p, q in d.bids:
        lines.append(f"  🟢 `${p:,.4f}` — `{q:,.4f}`")
    lines.append(f"\n• *Source:* {source_name}\n• *UTC Time:* `{d.timestamp}`")
    return "\n".join(lines)

async def handle_command(
    command_text: str,
    chat_id: int,
    telegram_client: TelegramClient,
    user_id: Optional[int] = None,
    user_repo: Optional[UserRepository] = None,
    memory_repo: Optional[MemoryRepository] = None,
    conversation_repo: Optional[ConversationRepository] = None,
    binance_client: Optional[BinanceClient] = None,
) -> bool:
    """
    Evaluates slash commands.
    Returns True if the message was recognized and handled as a command, False otherwise.
    
    CRITICAL SAFETY RULE:
    Once recognized as a deterministic command (such as /price, /ticker, /depth),
    the handler will NEVER return False or allow silent fallback into Gemini,
    even if an error or exception occurs.
    """
    cmd, args = parse_command_and_args(command_text)
    if not cmd:
        return False

    # --- 1. CORE SYSTEM COMMANDS ---
    if cmd == "/start":
        await telegram_client.send_message(chat_id, WELCOME_TEXT, parse_mode="Markdown")
        return True
        
    if cmd == "/help":
        await telegram_client.send_message(chat_id, HELP_TEXT, parse_mode="Markdown")
        return True
        
    if cmd in ("/clear", "/reset"):
        if conversation_repo and user_id:
            try:
                await conversation_repo.create_new_session(user_id)
            except Exception as e:
                logger.error(f"Error resetting session: {e}")
        await telegram_client.send_message(chat_id, RESET_TEXT, parse_mode="Markdown")
        return True

    if cmd == "/id":
        id_text = f"🆔 Your Telegram User ID: {user_id}" if user_id is not None else "⚠️ Could not determine Telegram User ID."
        await telegram_client.send_message(chat_id, id_text, parse_mode="")
        return True

    # --- 2. SESSION CONVERSATION HISTORY COMMAND ---
    if cmd == "/history":
        if not conversation_repo or not conversation_repo.db.is_available or not user_id:
            await telegram_client.send_message(chat_id, "⚠️ ڈیٹا بیس فی الوقت دستیاب نہیں ہے۔ (Database offline)", parse_mode="")
            return True

        try:
            active_session = await conversation_repo.get_or_create_active_session(user_id)
            if not active_session:
                await telegram_client.send_message(chat_id, "ℹ️ کوئی فعال سیشن موجود نہیں ہے۔ نیا پیغام بھیج کر گفتگو شروع کریں۔", parse_mode="")
                return True

            messages = await conversation_repo.get_recent_messages(user_id, active_session["id"], limit=10)
            if not messages:
                await telegram_client.send_message(chat_id, "ℹ️ اس سیشن میں ابھی تک کوئی گفتگو نہیں ہوئی۔", parse_mode="")
                return True

            lines = ["📜 *موجودہ سیشن کی گفتگو (Session History):*\n"]
            for idx, msg in enumerate(messages, start=1):
                sender = "You" if msg.get("role") == "user" else "Sultan Assistant"
                content = msg.get("content", "").strip()
                if len(content) > 150:
                    content = content[:147] + "..."
                lines.append(f"{idx}. *{sender}:* {content}")

            await telegram_client.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error fetching history: {e}")
            await telegram_client.send_message(chat_id, "⚠️ گفتگو لانے میں مسئلہ پیش آیا۔", parse_mode="")
        return True

    # --- 3. DETERMINISTIC MARKET DATA COMMANDS (PHASE 7) ---
    
    # 3a. /price <symbol>
    if cmd == "/price":
        if not args:
            msg = (
                "ℹ️ *درست طریقہ استعمال (Usage):*\n"
                "`/price <symbol>`\n\n"
                "*مثالیں (Examples):*\n"
                "• `/price BTCUSDT`\n"
                "• `/price ETHUSDT`\n"
                "• `/price SOL` (خودکار طور پر USDT پیئر لے گا)"
            )
            await telegram_client.send_message(chat_id, msg, parse_mode="Markdown")
            return True

        if not binance_client:
            await telegram_client.send_message(
                chat_id,
                "⚠️ *Market Data Error:*\nمارکیٹ ڈیٹا کلائنٹ دستیاب نہیں ہے۔ (Binance client uninitialized)",
                parse_mode="Markdown"
            )
            return True

        try:
            symbol_raw = args.split()[0]
            ticker = await binance_client.get_price(symbol_raw)
            resp = format_price_message(ticker)
            await telegram_client.send_message(chat_id, resp, parse_mode="Markdown")
        except ValueError as ve:
            await telegram_client.send_message(
                chat_id,
                f"⚠️ *غلط سمبل (Invalid Symbol):*\n{str(ve)}\n\n_مثال:_ `/price BTCUSDT`",
                parse_mode="Markdown"
            )
        except BinanceAPIError as be:
            logger.error(f"Binance price error: {be}")
            await telegram_client.send_message(
                chat_id,
                f"⚠️ *Market Data Error:*\n{str(be)}\n\n_No market value or analysis will be guessed._",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Unexpected error in /price: {e}")
            await telegram_client.send_message(
                chat_id,
                "⚠️ *Market Data Error:*\nمارکیٹ ریٹ لانے میں غیر متوقع مسئلہ پیش آیا۔ No market value will be guessed.",
                parse_mode="Markdown"
            )
        return True

    # 3b. /ticker <symbol>
    if cmd == "/ticker":
        if not args:
            msg = (
                "ℹ️ *درست طریقہ استعمال (Usage):*\n"
                "`/ticker <symbol>`\n\n"
                "*مثالیں (Examples):*\n"
                "• `/ticker BTCUSDT`\n"
                "• `/ticker SOLUSDT`"
            )
            await telegram_client.send_message(chat_id, msg, parse_mode="Markdown")
            return True

        if not binance_client:
            await telegram_client.send_message(
                chat_id,
                "⚠️ *Market Data Error:*\nمارکیٹ ڈیٹا کلائنٹ دستیاب نہیں ہے۔",
                parse_mode="Markdown"
            )
            return True

        try:
            symbol_raw = args.split()[0]
            t = await binance_client.get_24h_ticker(symbol_raw)
            resp = format_ticker_message(t)
            await telegram_client.send_message(chat_id, resp, parse_mode="Markdown")
        except ValueError as ve:
            await telegram_client.send_message(
                chat_id,
                f"⚠️ *غلط سمبل (Invalid Symbol):*\n{str(ve)}",
                parse_mode="Markdown"
            )
        except BinanceAPIError as be:
            logger.error(f"Binance ticker error: {be}")
            await telegram_client.send_message(
                chat_id,
                f"⚠️ *Market Data Error:*\n{str(be)}\n\n_No market value or analysis will be guessed._",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Unexpected error in /ticker: {e}")
            await telegram_client.send_message(
                chat_id,
                "⚠️ *Market Data Error:*\nمارکیٹ ٹکر سمری لانے میں مسئلہ پیش آیا۔",
                parse_mode="Markdown"
            )
        return True

    # 3c. /depth <symbol>
    if cmd == "/depth":
        if not args:
            msg = (
                "ℹ️ *درست طریقہ استعمال (Usage):*\n"
                "`/depth <symbol>`\n\n"
                "*مثالیں (Examples):*\n"
                "• `/depth BTCUSDT`\n"
                "• `/depth ETHUSDT`"
            )
            await telegram_client.send_message(chat_id, msg, parse_mode="Markdown")
            return True

        if not binance_client:
            await telegram_client.send_message(
                chat_id,
                "⚠️ *Market Data Error:*\nمارکیٹ ڈیٹا کلائنٹ دستیاب نہیں ہے۔",
                parse_mode="Markdown"
            )
            return True

        try:
            symbol_raw = args.split()[0]
            d = await binance_client.get_order_book_depth(symbol_raw, limit=5)
            resp = format_depth_message(d)
            await telegram_client.send_message(chat_id, resp, parse_mode="Markdown")
        except ValueError as ve:
            await telegram_client.send_message(
                chat_id,
                f"⚠️ *غلط سمبل (Invalid Symbol):*\n{str(ve)}",
                parse_mode="Markdown"
            )
        except BinanceAPIError as be:
            logger.error(f"Binance depth error: {be}")
            await telegram_client.send_message(
                chat_id,
                f"⚠️ *Market Data Error:*\n{str(be)}\n\n_No market value or analysis will be guessed._",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Unexpected error in /depth: {e}")
            await telegram_client.send_message(
                chat_id,
                "⚠️ *Market Data Error:*\nآرڈر بک لانے میں مسئلہ پیش آیا۔",
                parse_mode="Markdown"
            )
        return True

    # --- 4. LONG-TERM MEMORY COMMANDS ---
    if cmd == "/remember":
        content = args.strip()
        if not content:
            msg = (
                "ℹ️ *درست طریقہ استعمال (Usage):*\n"
                "`/remember <معلومات یا ترجیحات>`\n\n"
                "*مثال:*\n"
                "`/remember مجھے مختصر اور ٹو دی پوائنٹ جوابات پسند ہیں۔`"
            )
            await telegram_client.send_message(chat_id, msg, parse_mode="Markdown")
            return True

        if not memory_repo or not memory_repo.db.is_available or not user_id:
            await telegram_client.send_message(chat_id, "⚠️ ڈیٹا بیس فی الوقت دستیاب نہیں ہے۔ (Database offline)", parse_mode="")
            return True

        try:
            mtype = infer_memory_type(content)
            mem_id = await memory_repo.add_memory(user_id, content, memory_type=mtype)
            saved_msg = (
                f"💾 *یادداشت کامیابی کے ساتھ محفوظ کر لی گئی ہے! (Memory Saved)*\n\n"
                f"• *ID:* `{mem_id}`\n"
                f"• *نوعیت (Type):* `{mtype}`\n"
                f"• *متن (Content):* {content}\n\n"
                f"_یہ معلومات مستقبل کی گفتگو میں بطور حوالہ استعمال ہوگی۔_"
            )
            await telegram_client.send_message(chat_id, saved_msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error adding memory: {e}")
            await telegram_client.send_message(chat_id, "⚠️ معذرت، ڈیٹا بیس ایرر کے باعث یادداشت محفوظ نہیں ہو سکی۔", parse_mode="")
        return True

    if cmd == "/memories":
        if not memory_repo or not memory_repo.db.is_available or not user_id:
            await telegram_client.send_message(chat_id, "⚠️ ڈیٹا بیس فی الوقت دستیاب نہیں ہے۔", parse_mode="")
            return True

        try:
            memories = await memory_repo.get_all_memories(user_id)
            if not memories:
                await telegram_client.send_message(
                    chat_id,
                    "ℹ️ آپ کے پاس ابھی کوئی محفوظ شدہ یادداشت نہیں ہے۔ نئی یادداشت کے لیے `/remember <متن>` استعمال کریں۔",
                    parse_mode="Markdown"
                )
                return True

            lines = ["🧠 *آپ کی محفوظ شدہ مستقل یادداشتیں (Long-term Memories):*\n"]
            for idx, mem in enumerate(memories, start=1):
                mtype = mem.get("memory_type", "fact")
                content = mem.get("content", "")
                lines.append(f"{idx}. *[{mtype.capitalize()}]* `{content}`")

            lines.append("\n_کسی یادداشت کو ڈیلیٹ کرنے کے لیے `/forget <نمبر>` لکھیں۔_")
            await telegram_client.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error fetching memories: {e}")
            await telegram_client.send_message(chat_id, "⚠️ یادداشتیں لانے میں مسئلہ پیش آیا۔", parse_mode="")
        return True

    if cmd == "/forgetall_confirm":
        if not memory_repo or not memory_repo.db.is_available or not user_id:
            await telegram_client.send_message(chat_id, "⚠️ ڈیٹا بیس فی الوقت دستیاب نہیں ہے۔", parse_mode="")
            return True
        await memory_repo.clear_all_memories(user_id)
        await telegram_client.send_message(chat_id, "🗑️ *تمام مستقل یادداشتیں کامیابی کے ساتھ ڈیلیٹ کر دی گئی ہیں (All Memories Deleted).* ", parse_mode="Markdown")
        return True

    if cmd == "/forgetall":
        warn_msg = (
            "⚠️ *انتباہ (Warning):*\n"
            "اس عمل سے آپ کی تمام مستقل یادداشتیں ہمیشہ کے لیے ڈیلیٹ ہو جائیں گی۔\n\n"
            "تصدیق کے لیے درج ذیل کمانڈ لکھیں:\n"
            "`/forgetall_confirm`"
        )
        await telegram_client.send_message(chat_id, warn_msg, parse_mode="Markdown")
        return True

    if cmd == "/forget":
        if not args or not args.isdigit():
            msg = (
                "ℹ️ *درست طریقہ استعمال (Usage):*\n"
                "`/forget <یادداشت نمبر>`\n\n"
                "یادداشتوں کے نمبر دیکھنے کے لیے پہلے `/memories` چیک کریں۔"
            )
            await telegram_client.send_message(chat_id, msg, parse_mode="Markdown")
            return True

        if not memory_repo or not memory_repo.db.is_available or not user_id:
            await telegram_client.send_message(chat_id, "⚠️ ڈیٹا بیس فی الوقت دستیاب نہیں ہے۔", parse_mode="")
            return True

        target_idx = int(args)
        memories = await memory_repo.get_all_memories(user_id)
        if target_idx < 1 or target_idx > len(memories):
            await telegram_client.send_message(chat_id, f"⚠️ نمبر {target_idx} پر کوئی یادداشت موجود نہیں ہے۔", parse_mode="")
            return True

        target_mem = memories[target_idx - 1]
        mem_id = target_mem.get("id")
        await memory_repo.delete_memory(user_id, mem_id)
        
        del_msg = f"🗑️ *یادداشت نمبر {target_idx} ڈیلیٹ کر دی گئی ہے (Memory #{target_idx} Deleted):*\n`{target_mem.get('content')}`"
        await telegram_client.send_message(chat_id, del_msg, parse_mode="Markdown")
        return True

    if cmd == "/memory":
        if user_repo and user_repo.db.is_available:
            try:
                profile = await user_repo.get_user_profile(user_id) if user_id else None
                mem_count = await memory_repo.get_memory_count(user_id) if (memory_repo and user_id) else 0
                msg_count = await conversation_repo.get_total_message_count(user_id) if (conversation_repo and user_id) else 0
                
                resp_text = (
                    f"🧠 *اسٹیٹس اور یادداشت (State & Memory Status)*\n\n"
                    f"• *D1 Database:* `Connected (Active)`\n"
                    f"• *صارف کا نام:* {profile.get('display_name') if profile else 'N/A'}\n"
                    f"• *Telegram ID:* `{user_id}`\n"
                    f"• *محفوظ شدہ یادداشتیں (Memories):* `{mem_count}`\n"
                    f"• *کل پیغامات (Total Messages):* `{msg_count}`\n\n"
                    f"_یادداشتیں دیکھنے کے لیے `/memories` استعمال کریں۔_"
                )
            except Exception as e:
                logger.error(f"Error fetching memory status: {e}")
                resp_text = "⚠️ میموری اسٹیٹس لانے میں مسئلہ پیش آیا۔"
        else:
            resp_text = (
                "🧠 *اسٹیٹس (State Status)*\n\n"
                "• *D1 Database:* `Offline / Unbound`\n"
                "• *موڈ:* `عارضی سیشن (Ephemeral)`\n\n"
                "_ڈیٹا بیس فعال کرنے کے لیے `ASSISTANT_DB` بائنڈنگ ترتیب دیں۔_"
            )
        await telegram_client.send_message(chat_id, resp_text, parse_mode="Markdown")
        return True

    return False
