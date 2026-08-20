"""Main update and message dispatcher with strict deterministic command interception & AI market grounding."""

import logging
import asyncio
from typing import Optional
from config.settings import Settings
from telegram.client import TelegramClient
from telegram.auth import is_user_authorized
from ai.gemini_client import GeminiClient
from ai.prompts_builder import (
    select_relevant_memories,
    extract_crypto_symbols,
    extract_timeframe,
    has_technical_analysis_intent,
    format_market_state_grounding,
    format_prompt_with_context,
)
from router.command_router import handle_command
from config.prompts import UNAUTHORIZED_DENIAL_TEXT, IMAGE_ERROR_TEXT, FALLBACK_ERROR_TEXT
from storage.repositories import (
    UserRepository,
    MemoryRepository,
    ConversationRepository,
    WatchlistRepository,
)
from trading.binance_client import BinanceClient

logger = logging.getLogger("worker.router")


async def dispatch_telegram_update(
    update: dict,
    settings: Settings,
    telegram_client: TelegramClient,
    gemini_client: GeminiClient,
    user_repo: Optional[UserRepository] = None,
    memory_repo: Optional[MemoryRepository] = None,
    conversation_repo: Optional[ConversationRepository] = None,
    watchlist_repo: Optional[WatchlistRepository] = None,
    binance_client: Optional[BinanceClient] = None,
):
    """Processes an incoming Telegram update dictionary."""
    message = update.get("message")
    if not message:
        return

    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        return

    from_user = message.get("from", {})
    user_id = from_user.get("id")

    # 1. Authorization Gatekeeper (Fail-Closed: evaluated before DB writes and AI calls)
    if not is_user_authorized(user_id, settings):
        await telegram_client.send_message(chat_id, UNAUTHORIZED_DENIAL_TEXT, parse_mode="Markdown")
        return

    # 2. Update Authorized User Profile in D1 (Graceful/Non-blocking)
    if user_repo and user_id:
        try:
            display_name = from_user.get("first_name", "")
            username = from_user.get("username", "")
            await user_repo.upsert_user_profile(user_id, display_name=display_name, username=username)
        except Exception as e:
            logger.error(f"Error persisting user profile: {e}")

    text = message.get("text", "").strip()
    photo = message.get("photo")
    caption = message.get("caption", "").strip()

    # 3. Check for Commands (Evaluated before any Gemini calls)
    is_command = text.startswith("/")
    if not is_command and "entities" in message:
        for ent in message["entities"]:
            if ent.get("type") == "bot_command" and ent.get("offset") == 0:
                is_command = True
                break

    if is_command:
        handled = await handle_command(
            text,
            chat_id,
            telegram_client,
            user_id=user_id,
            user_repo=user_repo,
            memory_repo=memory_repo,
            conversation_repo=conversation_repo,
            watchlist_repo=watchlist_repo,
            binance_client=binance_client
        )
        if handled:
            return

    # 4. Handle Photos / Multimodal Vision
    if photo:
        await telegram_client.send_chat_action(chat_id, "typing")
        try:
            highest_res_photo = photo[-1]
            file_id = highest_res_photo.get("file_id")
            image_bytes = await telegram_client.get_file_bytes(file_id)
            reply = await gemini_client.generate_vision(image_bytes, caption=caption, model_name=settings.gemini_model)
            await telegram_client.send_message(chat_id, reply, parse_mode="")

            if conversation_repo and user_id and conversation_repo.db.is_available and reply != IMAGE_ERROR_TEXT:
                try:
                    active_session = await conversation_repo.get_or_create_active_session(user_id)
                    if active_session:
                        user_entry = f"[User sent an image] Caption: {caption}" if caption else "[User sent an image]"
                        await conversation_repo.add_message(user_id, active_session["id"], "user", user_entry)
                        await conversation_repo.add_message(user_id, active_session["id"], "assistant", reply)
                except Exception as e:
                    logger.error(f"Error storing photo conversation turn: {e}")
        except Exception as e:
            logger.error(f"Error processing photo message: {e}")
            await telegram_client.send_message(chat_id, IMAGE_ERROR_TEXT, parse_mode="")
        return

    # 5. Handle Ordinary Text Messages with Session History, Long-Term Memory, and Live Market Grounding
    if text:
        await telegram_client.send_chat_action(chat_id, "typing")
        try:
            active_session_id = None
            recent_history = []
            relevant_memories = []
            market_grounding_lines = []

            # Step 5a: Retrieve active session history from D1 (non-blocking / resilient)
            if conversation_repo and user_id and conversation_repo.db.is_available:
                try:
                    active_session = await conversation_repo.get_or_create_active_session(user_id)
                    if active_session:
                        active_session_id = active_session["id"]
                        recent_history = await conversation_repo.get_recent_messages(
                            user_id,
                            active_session_id,
                            limit=settings.conversation_history_limit
                        )
                except Exception as e:
                    logger.error(f"Error retrieving session history: {e}")

            # Step 5b: Retrieve stored long-term memories from D1 (non-blocking / resilient)
            if memory_repo and user_id and memory_repo.db.is_available:
                try:
                    all_user_memories = await memory_repo.get_all_memories(user_id)
                    relevant_memories = select_relevant_memories(text, all_user_memories, max_memories=5)
                except Exception as e:
                    logger.error(f"Error selecting relevant memories: {e}")

            # Step 5c: Automated Live Market Grounding & Deterministic Market Reasoning Engine
            detected_symbols = extract_crypto_symbols(text, max_symbols=2)
            if detected_symbols and binance_client:
                timeframe = extract_timeframe(text)
                wants_ta = has_technical_analysis_intent(text) or (timeframe is not None)
                target_tf = timeframe or "1h"

                for sym in detected_symbols:
                    if wants_ta:
                        try:
                            market_state = await binance_client.get_market_state(
                                sym,
                                primary_timeframe=target_tf,
                                include_mtf=True
                            )
                            market_grounding_lines.append(format_market_state_grounding(market_state))
                        except Exception as e:
                            logger.warning(f"Could not compute full market state for {sym} ({target_tf}): {e}")
                            # Fallback to 24h ticker if klines fail
                            try:
                                ticker_data = await binance_client.get_24h_ticker(sym)
                                change_sign = "+" if ticker_data.price_change >= 0 else ""
                                ticker_line = (
                                    f"Asset: {ticker_data.symbol} | Verified Spot Price: ${ticker_data.last_price:,.2f} | "
                                    f"24h Change: {change_sign}{ticker_data.price_change_percent:.2f}% | "
                                    f"24h High: ${ticker_data.high_price:,.2f} | 24h Low: ${ticker_data.low_price:,.2f} | "
                                    f"24h Volume (USD): ${ticker_data.quote_volume:,.2f} | "
                                    f"Source: {ticker_data.source} (UTC: {ticker_data.timestamp})"
                                )
                                market_grounding_lines.append(ticker_line)
                            except Exception as ex:
                                logger.warning(f"Could not ground symbol {sym} on fallback: {ex}")
                    else:
                        try:
                            ticker_data = await binance_client.get_24h_ticker(sym)
                            change_sign = "+" if ticker_data.price_change >= 0 else ""
                            ticker_line = (
                                f"Asset: {ticker_data.symbol} | Verified Spot Price: ${ticker_data.last_price:,.2f} | "
                                f"24h Change: {change_sign}{ticker_data.price_change_percent:.2f}% | "
                                f"24h High: ${ticker_data.high_price:,.2f} | 24h Low: ${ticker_data.low_price:,.2f} | "
                                f"24h Volume (USD): ${ticker_data.quote_volume:,.2f} | "
                                f"Source: {ticker_data.source} (UTC: {ticker_data.timestamp})"
                            )
                            market_grounding_lines.append(ticker_line)
                        except Exception as e:
                            logger.warning(f"Could not ground symbol {sym}: {e}")

            market_grounding_text = "\n\n".join(market_grounding_lines) if market_grounding_lines else None

            # Step 5d: Format final prompt combining grounding, memories, history, and user query
            final_prompt = format_prompt_with_context(
                user_query=text,
                relevant_memories=relevant_memories,
                conversation_history=recent_history,
                market_grounding_text=market_grounding_text
            )

            # Step 5e: Execute single Gemini generation call
            reply = await gemini_client.generate_text(final_prompt, model_name=settings.gemini_model)
            await telegram_client.send_message(chat_id, reply, parse_mode="")

            # Step 5f: Persist user and assistant turns in D1 upon success
            if (
                conversation_repo
                and user_id
                and active_session_id
                and conversation_repo.db.is_available
                and reply != FALLBACK_ERROR_TEXT
                and not reply.startswith("⚠️ Gemini API Error:")
            ):
                try:
                    await conversation_repo.add_message(user_id, active_session_id, "user", text)
                    await conversation_repo.add_message(user_id, active_session_id, "assistant", reply)
                except Exception as e:
                    logger.error(f"Error persisting conversation messages: {e}")

        except Exception as e:
            logger.error(f"Error processing text message: {e}")
            await telegram_client.send_message(chat_id, FALLBACK_ERROR_TEXT, parse_mode="")
        return
