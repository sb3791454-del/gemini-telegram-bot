"""Payload builders, relevance scoring, and context formatters for Gemini API with structured market reasoning."""

import re
import base64
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from config.prompts import TRADING_SYSTEM_INSTRUCTIONS, DEFAULT_VISION_PROMPT
from trading.models import MarketState

# Common stop words in English and Roman/Urdu to filter out for keyword matching
STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "and", "or", "but", "if", "so", "as", "it", "its", "i", "me",
    "my", "myself", "we", "our", "you", "your", "he", "him", "his", "she", "her",
    "they", "them", "their", "what", "which", "who", "whom", "this", "that", "these",
    "those", "am", "how", "why", "where", "when", "can", "could", "should", "would",
    "will", "shall", "may", "might", "must", "about", "into", "through", "after",
    "before", "above", "below", "up", "down", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "all", "any", "both", "each", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "than", "too", "very", "s", "t", "just", "don", "shouldn", "now", "tell",
    "give", "please", "help", "show", "know", "think",
    # Common Urdu roman/script tokens
    "کیا", "ہے", "ہیں", "تھا", "تھی", "تھے", "کا", "کی", "کے", "کو", "سے", "میں",
    "پر", "اور", "یا", "کہ", "یہ", "وہ", "تو", "نہ", "نہیں", "اب", "جب", "ہم",
    "آپ", "تم", "میرا", "میری", "میرے", "مجھے", "بتاؤ", "کرو", "کریں"
}

# Crypto symbol mappings for automated context extraction
CRYPTO_ALIASES = {
    "BITCOIN": "BTCUSDT", "BTC": "BTCUSDT",
    "ETHEREUM": "ETHUSDT", "ETH": "ETHUSDT",
    "SOLANA": "SOLUSDT", "SOL": "SOLUSDT",
    "BINANCE": "BNBUSDT", "BNB": "BNBUSDT",
    "RIPPLE": "XRPUSDT", "XRP": "XRPUSDT",
    "CARDANO": "ADAUSDT", "ADA": "ADAUSDT",
    "DOGECOIN": "DOGEUSDT", "DOGE": "DOGEUSDT",
    "AVALANCHE": "AVAXUSDT", "AVAX": "AVAXUSDT",
    "POLKADOT": "DOTUSDT", "DOT": "DOTUSDT",
    "CHAINLINK": "LINKUSDT", "LINK": "LINKUSDT",
    "NEAR": "NEARUSDT",
    "SUI": "SUIUSDT",
    "APTOS": "APTUSDT", "APT": "APTUSDT",
    "POLYGON": "MATICUSDT", "MATIC": "MATICUSDT",
    "LITECOIN": "LTCUSDT", "LTC": "LTCUSDT",
    "PEPE": "PEPEUSDT",
    "SHIBA": "SHIBUSDT", "SHIB": "SHIBUSDT",
    "TONCOIN": "TONUSDT", "TON": "TONUSDT",
    "TRON": "TRXUSDT", "TRX": "TRXUSDT",
    "UNISWAP": "UNIUSDT", "UNI": "UNIUSDT",
    "BITCOINCASH": "BCHUSDT", "BCH": "BCHUSDT",
    "TETHER": "USDT", "USDT": "USDT",
}

TIMEFRAME_PATTERNS = [
    # 15m patterns
    (r"\b(?:15\s*(?:m|min|mins|minute|minutes)|15-min|15-minute|15-minutes)\b|15\s*(?:منٹ|منٹوں)", "15m"),
    # 4h patterns (must precede 1h)
    (r"\b(?:4\s*(?:h|hr|hrs|hour|hours)|4-h|4-hr|4-hour|4-hours)\b|4\s*(?:گھنٹے|گھنٹہ|گھنٹوں)", "4h"),
    # 1h patterns
    (r"\b(?:1\s*(?:h|hr|hrs|hour|hours)|1-h|1-hr|1-hour|1-hours|hourly|hour\s+chart|hourly\s+chart)\b|1\s*(?:گھنٹہ|گھنٹے)", "1h"),
    # 1d patterns
    (r"\b(?:1\s*(?:d|day|days)|1-d|1-day|1-days|daily|day\s+chart|daily\s+chart|daily\s+timeframe)\b|1\s*دن|روزانہ", "1d"),
    # 1w patterns
    (r"\b(?:1\s*(?:w|wk|wks|week|weeks)|1-w|1-week|1-weeks|weekly|week\s+chart|weekly\s+chart|weekly\s+timeframe)\b|1\s*ہفتہ|ہفتہ\s*وار", "1w"),
]

TA_INTENT_PATTERNS = [
    r"\b(?:chart|charts|technical|ta|analyze|analysis|trend|structure|support|resistance|breakout|breakdown|overbought|oversold|setup|confirmation|candlestick|candle|candles|kline|klines|bullish|bearish|long|short|pullback|retest|entry|invalidation|moving\s+average|moving\s+averages|timeframe|timeframes|time\s+frame|time\s+frames|rsi|ema|sma|bollinger|bb|atr|indicator|indicators)\b",
    r"تجزیہ|چارٹ|رجحان|سپورٹ|مزاحمت|انڈیکیٹر|کینڈل|لونگ|شارٹ|بریک آؤٹ|پل بیک"
]


def get_current_utc_iso() -> str:
    """Returns current UTC timestamp in ISO-8601 format (YYYY-MM-DDTHH:MM:SSZ)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_keywords(text: str) -> set:
    """Extracts meaningful lowercase search tokens from text."""
    if not text:
        return set()
    words = re.findall(r"\b[\w\u0600-\u06FF]+\b", text.lower())
    return {w for w in words if len(w) > 2 and w not in STOP_WORDS}


def extract_crypto_symbols(text: str, max_symbols: int = 2) -> List[str]:
    """
    Extracts referenced cryptocurrency trading pairs from natural language query.
    e.g. 'Can you analyze Bitcoin and Solana?' -> ['BTCUSDT', 'SOLUSDT']
    """
    if not text:
        return []
    
    found = []
    tokens = re.findall(r"\b[a-zA-Z0-9_]+\b", text.upper())
    for t in tokens:
        if t in CRYPTO_ALIASES and CRYPTO_ALIASES[t] not in found:
            found.append(CRYPTO_ALIASES[t])
            if len(found) >= max_symbols:
                break
        elif t.endswith("USDT") and len(t) >= 6 and t not in found:
            found.append(t)
            if len(found) >= max_symbols:
                break

    return found


def extract_timeframe(text: str) -> Optional[str]:
    """
    Extracts and normalizes requested chart timeframe from natural language query.
    e.g. '1-hour chart' -> '1h', 'daily timeframe' -> '1d', '15 minute' -> '15m'
    """
    if not text:
        return None
    lower = text.lower()
    for pattern, canonical in TIMEFRAME_PATTERNS:
        if re.search(pattern, lower, re.IGNORECASE):
            return canonical
    return None


def has_technical_analysis_intent(text: str) -> bool:
    """
    Determines whether a message is seeking technical analysis, chart breakdown, or trade setup evaluation.
    """
    if not text:
        return False
    lower = text.lower()
    for pattern in TA_INTENT_PATTERNS:
        if re.search(pattern, lower, re.IGNORECASE):
            return True
    return False


def format_market_state_grounding(state: MarketState) -> str:
    """
    Constructs the standardized structured market grounding contract for Gemini context.
    Strictly separates factual data, market structure, indicators, MTF alignment, and deterministic setup.
    """
    ta = state.primary_ta
    ms = state.market_structure
    mtf = state.multi_timeframe
    setup = state.trade_setup
    ticker = state.ticker_24h

    sections = []

    # 1. LIVE MARKET FACTS
    price_str = f"${state.current_price:,.2f}" if state.current_price >= 1.0 else f"${state.current_price:.6f}"
    facts_lines = [
        "=== [LIVE MARKET FACTS] ===",
        f"• Symbol: {state.symbol}",
        f"• Verified Current Price: {price_str}",
        f"• Primary Timeframe: {state.primary_timeframe.upper()}",
        f"• Data Feed Source: {state.source}",
        f"• Feed Timestamp (UTC): {state.timestamp}"
    ]
    if ticker:
        sign = "+" if ticker.price_change >= 0 else ""
        facts_lines.extend([
            f"• 24h Rolling Change: {sign}{ticker.price_change_percent:.2f}% (${sign}{ticker.price_change:,.2f})",
            f"• 24h High: ${ticker.high_price:,.2f} | 24h Low: ${ticker.low_price:,.2f}",
            f"• 24h Volume (USD): ${ticker.quote_volume:,.2f}"
        ])
    sections.append("\n".join(facts_lines))

    # 2. MARKET STRUCTURE
    struct_lines = [
        f"=== [MARKET STRUCTURE — {state.primary_timeframe.upper()}] ===",
        f"• Market Structure Type: {ms.structure_type}",
        f"• Primary Trend: {ms.trend} (Strength: {ms.trend_strength})",
        f"• Recent Swing High: ${ms.recent_swing_high:,.2f} | Recent Swing Low: ${ms.recent_swing_low:,.2f}",
        f"• Trailing Lookback Extremes: Resistance: ${ms.resistance_level:,.2f} | Support: ${ms.support_level:,.2f}",
        f"• Key Support Zone: ${ms.support_zone[0]:,.2f} - ${ms.support_zone[1]:,.2f}",
        f"• Key Resistance Zone: ${ms.resistance_zone[0]:,.2f} - ${ms.resistance_zone[1]:,.2f}",
        f"• Swing Sequence: Higher Highs: {ms.higher_highs_count} | Higher Lows: {ms.higher_lows_count} | Lower Highs: {ms.lower_highs_count} | Lower Lows: {ms.lower_lows_count}"
    ]
    sections.append("\n".join(struct_lines))

    # 3. MOMENTUM & MOVING AVERAGES
    ema_200_str = f"${ta.ema_200:,.2f}" if ta.ema_200 else "N/A (insufficient candles)"
    mom_lines = [
        f"=== [MOMENTUM & MOVING AVERAGES — {state.primary_timeframe.upper()}] ===",
        f"• RSI-14 (Wilder Smoothed): {ta.rsi_14:.1f} [{ta.rsi_condition}]",
        f"• Moving Averages: EMA 20: ${ta.ema_20:,.2f} | EMA 50: ${ta.ema_50:,.2f} | EMA 200: {ema_200_str}",
        f"• EMA Structural Alignment: {ta.ema_alignment}"
    ]
    sections.append("\n".join(mom_lines))

    # 4. VOLATILITY, BANDS & VOLUME
    vol_lines = [
        f"=== [VOLATILITY, BOLLINGER BANDS & VOLUME — {state.primary_timeframe.upper()}] ===",
        f"• ATR-14 (Wilder Volatility): ${ta.atr_14:,.2f} (Recommended 1.5x ATR SL Buffer: ${ta.suggested_sl_distance:,.2f})",
        f"• Volatility State: {ta.volatility_state}",
        f"• Bollinger Bands (20, 2σ): Upper: ${ta.bb_upper:,.2f} | Middle (SMA 20): ${ta.bb_middle:,.2f} | Lower: ${ta.bb_lower:,.2f}",
        f"• Bollinger Bandwidth: {ta.bb_bandwidth_pct:.2f}% | Position (%b): {ta.bb_position_pct:.2f} [{ta.bb_state}]",
        f"• Volume Metrics: Recent {ta.volume_recent:,.1f} vs 20-SMA {ta.volume_sma_20:,.1f} ({ta.volume_state})"
    ]
    sections.append("\n".join(vol_lines))

    # 5. MULTI-TIMEFRAME CONFIRMATION
    if mtf:
        mtf_lines = [
            "=== [MULTI-TIMEFRAME CONFIRMATION & ALIGNMENT] ===",
            f"• Multi-Timeframe Alignment: {mtf.alignment_description}",
            f"• Confluence Status: {mtf.alignment_status}",
            f"• Signal Conflict Detected: {'YES (Conflicting signals present)' if mtf.has_conflict else 'NO (Timeframes aligned)'}"
        ]
        if mtf.conflict_details:
            mtf_lines.append(f"• Conflict Breakdown: {mtf.conflict_details}")
        sections.append("\n".join(mtf_lines))

    # 6. DETERMINISTIC TRADE SETUP EVALUATION
    setup_lines = [
        "=== [DETERMINISTIC TRADE SETUP EVALUATION] ===",
        f"• Setup State: {setup.setup_state}",
        f"• Directional Bias: {setup.direction_bias} (Confidence: {setup.confidence})",
        "• Deterministic Rationale:"
    ]
    for r in setup.reasons:
        setup_lines.append(f"  - {r}")

    if setup.suggested_entry_zone:
        setup_lines.append(f"• Suggested Technical Entry Zone: ${setup.suggested_entry_zone[0]:,.2f} - ${setup.suggested_entry_zone[1]:,.2f}")
    if setup.suggested_sl_level:
        setup_lines.append(f"• Technical Stop-Loss Level: ${setup.suggested_sl_level:,.2f}")
    if setup.suggested_tp_levels:
        tp_strs = [f"${tp:,.2f}" for tp in setup.suggested_tp_levels]
        setup_lines.append(f"• Calculated Take-Profit Targets: {', '.join(tp_strs)}")
    if setup.invalidation_level:
        setup_lines.append(f"• Setup Invalidation Level: ${setup.invalidation_level:,.2f} ({setup.invalidation_condition})")
    if setup.key_risks:
        setup_lines.append("• Key Identified Risks: " + ", ".join(setup.key_risks))

    setup_lines.append("• Risk Execution Policy: Exact dollar risk and position sizing require user-specified capital and risk percentage via /risk.")
    sections.append("\n".join(setup_lines))

    return "\n\n".join(sections)


def select_relevant_memories(
    query: str,
    memories: List[Dict[str, Any]],
    max_memories: int = 5
) -> List[Dict[str, Any]]:
    """
    Selects top relevant memories based on lightweight keyword token overlap.
    Runs entirely in pure Python with zero external API calls or vector databases.
    """
    if not query or not memories:
        return []

    query_tokens = extract_keywords(query)
    if not query_tokens:
        return []

    scored_memories = []
    for mem in memories:
        content = mem.get("content", "")
        mem_tokens = extract_keywords(content)
        overlap = query_tokens.intersection(mem_tokens)
        
        if not overlap:
            continue

        score = float(len(overlap))
        mtype = mem.get("memory_type", "fact").lower()
        if mtype in ("goal", "preference", "instruction"):
            score += 0.5

        scored_memories.append((score, mem))

    scored_memories.sort(key=lambda x: (x[0], x[1].get("id", 0)), reverse=True)
    return [item[1] for item in scored_memories[:max_memories]]


def format_prompt_with_context(
    user_query: str,
    relevant_memories: Optional[List[Dict[str, Any]]] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    current_utc_time: Optional[str] = None,
    market_grounding_text: Optional[str] = None,
) -> str:
    """
    Constructs the unified prompt with clearly separated sections:
    1. System constitution & operating instructions
    2. Temporal grounding (current UTC timestamp)
    3. Verified live market, technical indicator & setup grounding (if crypto query detected)
    4. Long-term memories (user-provided background context)
    5. Recent conversation history (active session turns)
    6. Current user message
    """
    now_str = current_utc_time or get_current_utc_iso()
    sections = [
        f"[SYSTEM CONSTITUTION & INSTRUCTIONS]\n{TRADING_SYSTEM_INSTRUCTIONS}",
        f"[TEMPORAL GROUNDING]\nCurrent UTC Time: {now_str}"
    ]

    # Section 3: Verified live market grounding
    if market_grounding_text:
        sections.append(
            "[LIVE VERIFIED MARKET GROUNDING — STRICT REAL-TIME DATA]\n"
            "The following verified live market data, deterministic technical indicators, market structure, and setup evaluations were computed directly from exchange feeds at this exact moment.\n"
            "You MUST treat these numbers, indicator calculations, structural classifications, and timeframe metrics as immutable ground truth.\n"
            "Never hallucinate, invent, or contradict these figures. Ground your analysis, explanations, and risk advice directly in these facts.\n\n"
            f"{market_grounding_text}"
        )

    # Section 4: Long-term memory context
    if relevant_memories:
        mem_lines = []
        for mem in relevant_memories:
            mtype = mem.get("memory_type", "Fact").capitalize()
            content = mem.get("content", "").strip()
            mem_lines.append(f"- {mtype}: {content}")
        if mem_lines:
            sections.append(
                "[LONG-TERM MEMORY — USER PROVIDED CONTEXT]\n" + "\n".join(mem_lines)
            )

    # Section 5: Recent conversation history
    if conversation_history:
        history_lines = []
        for msg in conversation_history:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "").strip()
            if role == "USER":
                history_lines.append(f"USER: {content}")
            else:
                history_lines.append(f"ASSISTANT: {content}")
        if history_lines:
            sections.append(
                "[RECENT CONVERSATION HISTORY]\n" + "\n".join(history_lines)
            )

    # Section 6: Current user message
    sections.append(f"[CURRENT USER MESSAGE]\n{user_query}")
    return "\n\n".join(sections)


def format_prompt_with_memories(user_query: str, relevant_memories: List[Dict[str, Any]]) -> str:
    """Backward-compatible alias for memory-only formatting."""
    return format_prompt_with_context(user_query, relevant_memories=relevant_memories, conversation_history=None)


def build_text_payload(prompt: str) -> Dict[str, Any]:
    """Constructs a standard generateContent JSON payload for text."""
    return {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }


def format_vision_caption(
    caption: Optional[str] = None,
    current_utc_time: Optional[str] = None
) -> str:
    """Formats multimodal vision caption with temporal grounding and instructions."""
    now_str = current_utc_time or get_current_utc_iso()
    user_caption = caption.strip() if caption else DEFAULT_VISION_PROMPT
    return (
        f"[SYSTEM CONSTITUTION & INSTRUCTIONS]\n{TRADING_SYSTEM_INSTRUCTIONS}\n\n"
        f"[TEMPORAL GROUNDING]\nCurrent UTC Time: {now_str}\n\n"
        f"[IMAGE ANALYSIS REQUEST]\n{user_caption}"
    )


def build_vision_payload(
    image_bytes: bytes,
    caption: Optional[str] = None,
    mime_type: str = "image/jpeg",
    current_utc_time: Optional[str] = None
) -> Dict[str, Any]:
    """Constructs a multimodal generateContent JSON payload with base64 image data."""
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    effective_caption = format_vision_caption(caption, current_utc_time)
    return {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64_image
                        }
                    },
                    {
                        "text": effective_caption
                    }
                ]
            }
        ]
    }
