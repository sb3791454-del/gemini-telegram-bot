"""Payload builders, relevance scoring, and context formatters for Gemini API with live market grounding."""

import re
import base64
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from config.prompts import TRADING_SYSTEM_INSTRUCTIONS, DEFAULT_VISION_PROMPT

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
    3. Verified live market grounding (if crypto query detected)
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
            "The following verified live market data was retrieved directly from exchange feeds at this exact moment.\n"
            "You MUST treat these numbers as indisputable ground truth. Never hallucinate, invent, or contradict these figures.\n\n"
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
