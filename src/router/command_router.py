"""Command router for Telegram bot slash commands."""

from typing import Optional
from telegram.client import TelegramClient
from config.prompts import WELCOME_TEXT, HELP_TEXT, RESET_TEXT
from storage.repositories import UserRepository, MemoryRepository, infer_memory_type

async def handle_command(
    command: str,
    chat_id: int,
    telegram_client: TelegramClient,
    user_id: Optional[int] = None,
    user_repo: Optional[UserRepository] = None,
    memory_repo: Optional[MemoryRepository] = None
) -> bool:
    """
    Evaluates slash commands. Returns True if command was handled, False otherwise.
    """
    clean_cmd = command.strip().split()[0].lower()
    
    if clean_cmd.startswith("/start"):
        await telegram_client.send_message(chat_id, WELCOME_TEXT, parse_mode="Markdown")
        return True
        
    if clean_cmd.startswith("/help"):
        await telegram_client.send_message(chat_id, HELP_TEXT, parse_mode="Markdown")
        return True
        
    if clean_cmd.startswith("/clear") or clean_cmd.startswith("/reset"):
        await telegram_client.send_message(chat_id, RESET_TEXT, parse_mode="Markdown")
        return True

    if clean_cmd.startswith("/id"):
        id_text = f"🆔 Your Telegram User ID: {user_id}" if user_id is not None else "⚠️ Could not determine Telegram User ID."
        await telegram_client.send_message(chat_id, id_text, parse_mode="")
        return True

    # --- MEMORY COMMANDS ---

    # 1. /remember <text>
    if clean_cmd.startswith("/remember"):
        content = command.strip()[len(clean_cmd):].strip()
        if not content:
            msg = (
                "ℹ️ *درست طریقہ استعمال (Usage):*\n"
                "`/remember <معلومات یا ہدف>`\n\n"
                "*مثالیں (Examples):*\n"
                "• `/remember I want to become an embedded systems engineer.`\n"
                "• `/remember I prefer explanations in simple Urdu and English.`"
            )
            await telegram_client.send_message(chat_id, msg, parse_mode="Markdown")
            return True

        if not memory_repo or not memory_repo.db.is_available or not user_id:
            await telegram_client.send_message(chat_id, "⚠️ ڈیٹا بیس فی الوقت دستیاب نہیں ہے۔ یادداشت محفوظ نہیں ہو سکی۔ (Database offline)", parse_mode="")
            return True

        mtype = infer_memory_type(content)
        res = await memory_repo.add_memory(user_id, mtype, content)
        
        if res.get("success"):
            saved_msg = (
                f"✅ *یادداشت محفوظ کر لی گئی ہے (Memory Saved):*\n"
                f"• *Type:* `{mtype.capitalize()}`\n"
                f"• *Content:* {content}"
            )
            await telegram_client.send_message(chat_id, saved_msg, parse_mode="Markdown")
        elif res.get("reason") == "duplicate":
            dup_msg = (
                "ℹ️ *پہلے سے موجود ہے (Already Remembered):*\n"
                "یہ ہو بہو معلومات آپ کی یادداشت میں پہلے سے محفوظ ہیں۔"
            )
            await telegram_client.send_message(chat_id, dup_msg, parse_mode="Markdown")
        elif res.get("reason") == "limit_reached":
            limit_msg = (
                f"⚠️ *میموری کی حد مکمل ہو چکی ہے (Memory Limit Reached):*\n"
                f"آپ کی محفوظ کردہ یادداشتوں کی حد ({res.get('limit', 100)}) پوری ہو چکی ہے۔ "
                f"نئی یادداشت کے لیے `/forget <نمبر>` کے ذریعے پرانی یادداشتیں ڈیلیٹ کریں۔"
            )
            await telegram_client.send_message(chat_id, limit_msg, parse_mode="Markdown")
        else:
            await telegram_client.send_message(chat_id, "⚠️ معذرت، ڈیٹا بیس ایرر کے باعث یادداشت محفوظ نہیں ہو سکی۔", parse_mode="")
        return True

    # 2. /memories
    if clean_cmd.startswith("/memories"):
        if not memory_repo or not memory_repo.db.is_available or not user_id:
            await telegram_client.send_message(chat_id, "⚠️ ڈیٹا بیس فی الوقت دستیاب نہیں ہے۔", parse_mode="")
            return True

        memories = await memory_repo.get_all_memories(user_id)
        if not memories:
            empty_msg = (
                "🧠 *کوئی مستقل یادداشت محفوظ نہیں ہے (No Memories Stored):*\n"
                "نئی معلومات محفوظ کرنے کے لیے `/remember <معلومات>` لکھیں۔"
            )
            await telegram_client.send_message(chat_id, empty_msg, parse_mode="Markdown")
            return True

        lines = [f"🧠 *آپ کی مستقل یادداشتیں (Your Memories - {len(memories)}/100):*\n"]
        for idx, mem in enumerate(memories, start=1):
            mtype = mem.get("memory_type", "Fact").capitalize()
            content = mem.get("content", "").strip()
            lines.append(f"{idx}. `[{mtype}]` {content}")

        lines.append("\n_کسی یادداشت کو ڈیلیٹ کرنے کے لیے `/forget <نمبر>` لکھیں۔_")
        await telegram_client.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")
        return True

    # 3. /forgetall_confirm (must check before /forgetall)
    if clean_cmd.startswith("/forgetall_confirm"):
        if not memory_repo or not memory_repo.db.is_available or not user_id:
            await telegram_client.send_message(chat_id, "⚠️ ڈیٹا بیس فی الوقت دستیاب نہیں ہے۔", parse_mode="")
            return True

        await memory_repo.delete_all_memories(user_id)
        await telegram_client.send_message(chat_id, "🗑️ *تمام مستقل یادداشتیں کامیابی کے ساتھ ڈیلیٹ کر دی گئی ہیں (All Memories Deleted).*", parse_mode="Markdown")
        return True

    # 4. /forgetall
    if clean_cmd.startswith("/forgetall"):
        warn_msg = (
            "⚠️ *انتباہ (Warning):*\n"
            "اس عمل سے آپ کی تمام مستقل یادداشتیں ہمیشہ کے لیے ڈیلیٹ ہو جائیں گی۔\n\n"
            "تصدیق کے لیے `/forgetall_confirm` لکھ کر بھیجیں۔"
        )
        await telegram_client.send_message(chat_id, warn_msg, parse_mode="Markdown")
        return True

    # 5. /forget <number>
    if clean_cmd.startswith("/forget"):
        args = command.strip()[len(clean_cmd):].strip()
        if not args or not args.isdigit():
            msg = (
                "ℹ️ *درست طریقہ استعمال (Usage):*\n"
                "`/forget <یادداشت کا نمبر>`\n\n"
                "پہلے `/memories` لکھ کر اپنی فہرست اور نمبر چیک کریں۔"
            )
            await telegram_client.send_message(chat_id, msg, parse_mode="Markdown")
            return True

        if not memory_repo or not memory_repo.db.is_available or not user_id:
            await telegram_client.send_message(chat_id, "⚠️ ڈیٹا بیس فی الوقت دستیاب نہیں ہے۔", parse_mode="")
            return True

        target_idx = int(args)
        memories = await memory_repo.get_all_memories(user_id)
        if target_idx < 1 or target_idx > len(memories):
            err_msg = f"⚠️ *غلط نمبر:* آپ کی کل {len(memories)} یادداشتیں ہیں۔ فہرست دیکھنے کے لیے `/memories` لکھیں۔"
            await telegram_client.send_message(chat_id, err_msg, parse_mode="Markdown")
            return True

        target_mem = memories[target_idx - 1]
        mem_id = target_mem.get("id")
        await memory_repo.delete_memory(user_id, mem_id)
        
        del_msg = f"🗑️ *یادداشت نمبر {target_idx} ڈیلیٹ کر دی گئی ہے (Memory #{target_idx} Deleted):*\n\"{target_mem.get('content')}\""
        await telegram_client.send_message(chat_id, del_msg, parse_mode="Markdown")
        return True

    # 6. /memory (status summary)
    if clean_cmd.startswith("/memory"):
        if user_repo and user_repo.db.is_available:
            try:
                profile = await user_repo.get_user_profile(user_id) if user_id else None
                mem_count = await memory_repo.count_memories(user_id) if (memory_repo and user_id) else 0
                has_profile = profile is not None
                
                resp_text = (
                    "🧠 *Memory & State Status:*\n"
                    "• Database: Connected (D1 Active)\n"
                    f"• User Profile: {'Available' if has_profile else 'Not Created Yet'}\n"
                    f"• Long-term Memories: {mem_count} / 100\n"
                )
                if profile and profile.get("last_seen_at"):
                    resp_text += f"• Last Active: {profile['last_seen_at'][:19].replace('T', ' ')} UTC\n"
            except Exception as e:
                resp_text = "🧠 *Memory Status:* Active (D1 Error occurred)"
        else:
            resp_text = (
                "🧠 *Memory & State Status:*\n"
                "• Database: Offline (D1 binding not attached)\n"
                "• User Profile: Ephemeral (In-Memory)\n"
                "• Long-term Memories: 0"
            )
        await telegram_client.send_message(chat_id, resp_text, parse_mode="Markdown")
        return True
        
    return False
