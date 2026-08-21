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
    extract_capital_and_risk,
    extract_hypothetical_trade_params,
    has_technical_analysis_intent,
    format_market_state_grounding,
    format_hypothetical_trade_grounding,
    format_prompt_with_context,
)
from router.command_router import handle_command
from storage.repositories import (
    UserRepository,
    MemoryRepository,
    SettingsRepository,
    ConversationRepository,
    WatchlistRepository,
    AlertRepository,
)
from trading.binance_client import BinanceClient
from config.prompts import (
    UNAUTHORIZED_DENIAL_TEXT,
    FALLBACK_ERROR_TEXT,
    IMAGE_ERROR_TEXT,
    UNSUPPORTED_MESSAGE_TEXT,
)

logger = logging.getLogger("worker.router")


async def dispatch_telegram_update(
    update: dict,
    settings: Settings,
    telegram_client: TelegramClient,
    gemini_client: GeminiClient,
    user_repo: Optional[UserRepository] = None,
    memory_repo: Optional[MemoryRepository] = None,
    settings_repo: Optional[SettingsRepository] = None,
    conversation_repo: Optional[ConversationRepository] = None,
    watchlist_repo: Optional[WatchlistRepository] = None,
    binance_client: Optional[BinanceClient] = None,
    alert_repo: Optional[AlertRepository] = None,
) -> None:
    """
    Main dispatching pipeline for Telegram webhook updates.
    Enforces FAIL-CLOSED authentication, intercepts deterministic slash commands,
    grounds trading inquiries with verified Binance market data, and executes AI generation.
    """
    try:
        # Step 1: Extract message payload
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = message.get("chat", {}).get("id")
        user_info = message.get("from", {})
        user_id = user_info.get("id")

        if not chat_id:
            return

        # Step 2: Strict Authorization (FAIL-CLOSED)
        if not is_user_authorized(user_id, settings):
            logger.warning(f"Unauthorized access attempt by user_id: {user_id}")
            await telegram_client.send_message(chat_id, UNAUTHORIZED_DENIAL_TEXT, parse_mode="")
            return

        # Step 3: Register / update user record in D1 if available
        if user_repo and user_id and user_repo.db.is_available:
            try:
                await user_repo.upsert_user(
                    user_id=user_id,
                    username=user_info.get("username"),
                    first_name=user_info.get("first_name"),
                    last_name=user_info.get("last_name"),
                    language_code=user_info.get("language_code"),
                )
            except Exception as e:
                logger.error(f"Error persisting user profile: {e}")

        # Step 4: Handle slash commands deterministically (NO Gemini fallthrough)
        text = message.get("text", "").strip()
        caption = message.get("caption", "").strip()
        effective_text = text or caption

        if effective_text.startswith("/"):
            handled = await handle_command(
                command_text=effective_text,
                chat_id=chat_id,
                telegram_client=telegram_client,
                user_id=user_id,
                user_repo=user_repo,
                memory_repo=memory_repo,
                conversation_repo=conversation_repo,
                watchlist_repo=watchlist_repo,
                binance_client=binance_client,
                alert_repo=alert_repo,
            )
            if handled:
                return

        # Step 5: Process standard conversational messages
        photo_list = message.get("photo")
        if photo_list:
            # Multimodal photo message
            await telegram_client.send_chat_action(chat_id, "typing")
            best_photo = photo_list[-1]
            file_id = best_photo.get("file_id")

            image_bytes = await telegram_client.download_file_bytes(file_id)
            if not image_bytes:
                await telegram_client.send_message(chat_id, IMAGE_ERROR_TEXT, parse_mode="")
                return

            reply = await gemini_client.generate_vision(
                image_bytes=image_bytes,
                caption=caption if caption else None,
                model_name=settings.gemini_model,
            )
            await telegram_client.send_message(chat_id, reply, parse_mode="")
            return

        elif text:
            # Standard Text Message
            await telegram_client.send_chat_action(chat_id, "typing")

            relevant_memories = []
            recent_history = []
            market_grounding_lines = []
            active_session_id = None

            # Step 5a: Retrieve conversation history from D1 (non-blocking / resilient)
            if conversation_repo and user_id and conversation_repo.db.is_available:
                try:
                    active_session_id = await conversation_repo.get_or_create_active_session(user_id)
                    if active_session_id:
                        recent_history = await conversation_repo.get_recent_messages(
                            user_id, active_session_id, limit=settings.history_limit
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
            user_capital, user_risk_pct = extract_capital_and_risk(text)
            hypo_params = extract_hypothetical_trade_params(text)

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
                            market_grounding_lines.append(
                                format_market_state_grounding(
                                    market_state,
                                    user_capital=user_capital,
                                    user_risk_pct=user_risk_pct
                                )
                            )
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

            if hypo_params:
                # Handle user-supplied hypothetical numbers deterministically
                market_grounding_lines.append(format_hypothetical_trade_grounding(hypo_params))

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

        else:
            # Non-text / unsupported message types (stickers, documents, audio)
            await telegram_client.send_message(chat_id, UNSUPPORTED_MESSAGE_TEXT, parse_mode="")

    except Exception as e:
        logger.error(f"Unhandled error in dispatch_telegram_update: {e}")
        try:
            chat_id = update.get("message", {}).get("chat", {}).get("id")
            if chat_id:
                await telegram_client.send_message(chat_id, FALLBACK_ERROR_TEXT, parse_mode="")
        except Exception:
            pass
