"""Payload builders, relevance scoring, and context formatters for Gemini API with structured market reasoning."""

import re
import base64
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from config.prompts import TRADING_SYSTEM_INSTRUCTIONS, DEFAULT_VISION_PROMPT
from trading.models import MarketState
from trading.risk_calculator import DEFAULT_ATR_MULTIPLIER, calculate_hard_stop, calculate_position_risk

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
    "کیا", "ہے", "ہیں", "تھا", "تھی", "تھے", "کا", "کی", "کے", "کو", "سے", "میں",
    "پر", "اور", "یا", "کہ", "یہ", "وہ", "تو", "نہ", "نہیں", "اب", "جب", "ہم",
    "آپ", "تم", "میرا", "میری", "میرے", "مجھے", "بتاؤ", "کرو", "کریں"
}

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
    (r"\b(?:15\s*(?:m|min|mins|minute|minutes)|15-min|15-minute|15-minutes)\b|15\s*(?:منٹ|منٹوں)", "15m"),
    (r"\b(?:4\s*(?:h|hr|hrs|hour|hours)|4-h|4-hr|4-hour|4-hours)\b|4\s*(?:گھنٹے|گھنٹہ|گھنٹوں)", "4h"),
    (r"\b(?:1\s*(?:h|hr|hrs|hour|hours)|1-h|1-hr|1-hour|1-hours|hourly|hour\s+chart|hourly\s+chart)\b|1\s*(?:گھنٹہ|گھنٹے)", "1h"),
    (r"\b(?:1\s*(?:d|day|days)|1-d|1-day|1-days|daily|day\s+chart|daily\s+chart|daily\s+timeframe)\b|1\s*دن|روزانہ", "1d"),
    (r"\b(?:1\s*(?:w|wk|wks|week|weeks)|1-w|1-week|1-weeks|weekly|week\s+chart|weekly\s+chart|weekly\s+timeframe)\b|1\s*ہفتہ|ہفتہ\s*وار", "1w"),
]

TA_INTENT_PATTERNS = [
    r"\b(?:chart|charts|technical|ta|analyze|analysis|trend|structure|support|resistance|breakout|breakdown|overbought|oversold|setup|confirmation|candlestick|candle|candles|kline|klines|bullish|bearish|long|short|pullback|retest|entry|invalidation|moving\s+average|moving\s+averages|timeframe|timeframes|time\s+frame|time\s+frames|rsi|ema|sma|bollinger|bb|atr|indicator|indicators|best\s+trade|trade\s+setup|trade\s+plan|trade|position)\b",
    r"تجزیہ|چارٹ|رجحان|سپورٹ|مزاحمت|انڈیکیٹر|کینڈل|لونگ|شارٹ|بریک آؤٹ|پل بیک|ٹریڈ"
]


def get_current_utc_iso() -> str:
    """Returns the current UTC timestamp formatted as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_keywords(text: str) -> List[str]:
    """Extracts non-stopword tokens from query for simple keyword matching."""
    if not text:
        return []
    words = re.findall(r"\w+", text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 1]


def extract_crypto_symbols(text: str, max_symbols: int = 2) -> List[str]:
    """Deterministically extracts cryptocurrency symbols from text with alias support."""
    if not text:
        return []

    found = []
    text_clean = text.upper()

    # Exact slash/dash pairs e.g. BTC/USDT, ETH-USDT
    pair_matches = re.findall(r"\b([A-Z0-9]{2,10})[/-](USDT|BUSD|USDC|BTC|ETH)\b", text_clean)
    for base, quote in pair_matches:
        sym = f"{base}{quote}"
        if sym not in found:
            found.append(sym)

    # Standard symbols e.g. BTCUSDT, SOLUSDT
    direct_matches = re.findall(r"\b([A-Z0-9]{2,10}(?:USDT|FDUSD|USDC|BUSD))\b", text_clean)
    for sym in direct_matches:
        if sym not in found:
            found.append(sym)

    # Aliases
    words = re.findall(r"\b[A-Z0-9]+\b", text_clean)
    for w in words:
        if w in CRYPTO_ALIASES:
            sym = CRYPTO_ALIASES[w]
            if sym not in found:
                found.append(sym)

    return found[:max_symbols]


def extract_timeframe(text: str) -> Optional[str]:
    """Deterministically extracts timeframe from text, defaulting to None if unspecified."""
    if not text:
        return None
    for pattern, tf in TIMEFRAME_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return tf
    return None


def has_technical_analysis_intent(text: str) -> bool:
    """Detects whether user query requests technical analysis, charting, structure, or trading setups."""
    if not text:
        return False
    for pat in TA_INTENT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def extract_capital_and_risk(text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Deterministically extracts user-specified account capital and risk percentage
    from natural language queries.
    """
    cap: Optional[float] = None
    risk: Optional[float] = None

    if not text:
        return None, None

    # Capital extraction
    cap_patterns = [
        r"(?:capital|account|balance|funds?|portfolio)\s*(?:is|of|=|:)?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)(?!\s*%)\s*(?:usd|dollars)?\b",
        r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)(?!\s*%)\s*(?:usd|dollars)?\s*(?:capital|account|balance|funds?|portfolio)\b",
        r"(?:have|deposit(?:ed)?)\s+\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)(?!\s*%)\s*(?:usd|dollars)?\s*(?:in\s+capital|capital|account|balance)?\b",
    ]
    for cp in cap_patterns:
        m = re.search(cp, text, re.IGNORECASE)
        if m:
            val_str = m.group(1).replace(",", "")
            try:
                val = float(val_str)
                if val > 0:
                    cap = val
                    break
            except Exception:
                pass

    # Risk extraction
    risk_patterns = [
        r"(?:risk|risk\s*percentage|risk\s*budget)\s*(?:is|of|=|:)?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        r"\b([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:risk|per\s*trade|budget)\b",
        r"\brisk\s*(?:is|of|=|:)?\s*([0-9]+(?:\.[0-9]+)?)\b",
        r"\b([0-9]+(?:\.[0-9]+)?)\s*%\b",
    ]
    for rp in risk_patterns:
        m = re.search(rp, text, re.IGNORECASE)
        if m:
            try:
                r_val = float(m.group(1))
                if 0 < r_val <= 100:
                    risk = r_val
                    break
            except Exception:
                pass

    return cap, risk


def extract_hypothetical_trade_params(text: str) -> Optional[Dict[str, Any]]:
    """
    Extracts user-supplied hypothetical trade parameters (Entry, Structural Warning, Hard Stop, ATR, Capital, Risk%)
    for deterministic evaluation when the user provides custom numbers in chat.
    """
    if not text:
        return None

    res: Dict[str, Any] = {}

    # Entry
    m_entry = re.search(r"\b(?:entry|entry\s*price|buy\s*at|short\s*at|long\s*at)\s*(?:is|of|=|:)?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\b", text, re.IGNORECASE)
    if m_entry:
        try:
            res['entry'] = float(m_entry.group(1).replace(',', ''))
        except Exception:
            pass

    # Structural Warning / Swing Level / Invalidation
    m_sw = re.search(r"\b(?:structural\s*(?:warning|invalidation|level|boundary|pivot|stop|sl)|swing\s*(?:low|high|point|level)|warning\s*level|warning)\s*(?:is|of|=|:)?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\b", text, re.IGNORECASE)
    if m_sw:
        try:
            res['structural_warning'] = float(m_sw.group(1).replace(',', ''))
        except Exception:
            pass

    # Hard Stop / Stop Loss (Negative lookbehind to prevent collision with structural stop)
    m_sl = re.search(r"(?<!\bstructural\s)(?<!\bswing\s)\b(?:hard\s*stop|hard\s*sl|execution\s*stop|physical\s*stop|stop\s*loss|stoploss|\bsl\b|\bstop\b)\s*(?:is|of|=|:)?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\b", text, re.IGNORECASE)
    if m_sl:
        try:
            res['hard_stop'] = float(m_sl.group(1).replace(',', ''))
        except Exception:
            pass

    # ATR
    m_atr = re.search(r"\b(?:atr|atr-14|average\s*true\s*range)\s*(?:is|of|=|:)?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\b", text, re.IGNORECASE)
    if m_atr:
        try:
            res['atr'] = float(m_atr.group(1).replace(',', ''))
        except Exception:
            pass

    # Capital & Risk
    cap, risk = extract_capital_and_risk(text)
    if cap is not None:
        res['capital'] = cap
    if risk is not None:
        res['risk_pct'] = risk

    # Direction
    if re.search(r"\b(?:long|buy|bullish)\b", text, re.IGNORECASE):
        res['direction'] = 'LONG'
    elif re.search(r"\b(?:short|sell|bearish)\b", text, re.IGNORECASE):
        res['direction'] = 'SHORT'
    elif 'entry' in res and 'structural_warning' in res:
        res['direction'] = 'LONG' if res['entry'] > res['structural_warning'] else 'SHORT'
    elif 'entry' in res and 'hard_stop' in res:
        res['direction'] = 'LONG' if res['entry'] > res['hard_stop'] else 'SHORT'

    has_trade_data = ('entry' in res) or ('structural_warning' in res) or ('hard_stop' in res) or ('atr' in res)
    return res if has_trade_data else None


def format_hypothetical_trade_grounding(params: Dict[str, Any]) -> str:
    """
    Constructs the immutable deterministic grounding contract for hypothetical trade calculations.
    Enforces Structural Warning != Hard SL and strictly uses deterministic k=1.5.
    """
    lines = ["=== [DETERMINISTIC TRADE & RISK CALCULATION — USER HYPOTHETICAL] ==="]

    entry = params.get("entry")
    sw = params.get("structural_warning")
    hard_sl = params.get("hard_stop")
    atr = params.get("atr")
    cap = params.get("capital")
    risk_pct = params.get("risk_pct")
    direction = params.get("direction", "LONG")

    if entry is not None:
        lines.append(f"• Proposed Entry Price: ${entry:,.2f}")
    if sw is not None:
        lines.append(f"• Structural Warning Level: ${sw:,.2f} (Informational Structural Boundary)")
    if atr is not None:
        lines.append(f"• ATR Volatility Buffer: ${atr:,.2f} (System Deterministic Buffer Multiplier k = {DEFAULT_ATR_MULTIPLIER})")

    # Invariant: Structural Warning and Hard SL must never be identical
    if sw is not None and hard_sl is not None and sw == hard_sl:
        if atr is not None:
            hard_sl = calculate_hard_stop(sw, atr, direction=direction, k=DEFAULT_ATR_MULTIPLIER)
            lines.append(f"• Invariant Enforcement: Structural Warning (${sw:,.2f}) and Hard Stop cannot be identical. Hard Stop recalculation applied: ${hard_sl:,.2f} ({DEFAULT_ATR_MULTIPLIER}x ATR buffer).")
        else:
            hard_sl = None

    # Evaluate Hard Stop-Loss deterministically
    if hard_sl is not None:
        lines.append(f"• Proposed Hard Stop-Loss: ${hard_sl:,.2f} (Explicitly Provided)")
    elif sw is not None and atr is not None:
        hard_sl = calculate_hard_stop(sw, atr, direction=direction, k=DEFAULT_ATR_MULTIPLIER)
        buffer_val = DEFAULT_ATR_MULTIPLIER * atr
        sign = "-" if direction == "LONG" else "+"
        lines.append(f"• Proposed Hard Stop-Loss: ${hard_sl:,.2f} (Calculated as Structural Warning ${sw:,.2f} {sign} {DEFAULT_ATR_MULTIPLIER}x ATR (${buffer_val:,.2f}))")
        lines.append(f"• Structural Distinction: Structural Warning (${sw:,.2f}) != Hard Stop Loss (${hard_sl:,.2f})")
    elif sw is not None and atr is None:
        lines.append(f"• ⚠️ INSUFFICIENT DATA FOR HARD STOP: Structural Warning (${sw:,.2f}) is NOT the Hard Stop Loss.")
        lines.append(f"  Hard Stop requires an ATR volatility buffer (Hard SL = Structural Warning - {DEFAULT_ATR_MULTIPLIER}x ATR for Long; Structural Warning + {DEFAULT_ATR_MULTIPLIER}x ATR for Short).")
        lines.append("  Without ATR or an explicit Hard Stop, exact Hard SL, position size, and Take-Profit levels cannot be computed.")
        lines.append("  Gemini MUST explicitly explain this missing dependency rather than inventing a stop-loss.")
        return "\n".join(lines)

    if entry is not None and hard_sl is not None:
        # Validate geometry
        if direction == "LONG" and hard_sl >= entry:
            lines.append(f"• ⚠️ INVALID GEOMETRY: For a LONG position, Hard Stop-Loss (${hard_sl:,.2f}) must be strictly below Entry price (${entry:,.2f}).")
            return "\n".join(lines)
        if direction == "SHORT" and hard_sl <= entry:
            lines.append(f"• ⚠️ INVALID GEOMETRY: For a SHORT position, Hard Stop-Loss (${hard_sl:,.2f}) must be strictly above Entry price (${entry:,.2f}).")
            return "\n".join(lines)

        risk_per_unit = abs(entry - hard_sl)
        risk_pct_price = (risk_per_unit / entry * 100.0) if entry > 0 else 0.0
        lines.append(f"• Exact Risk Per Unit: ${risk_per_unit:,.2f} ({risk_pct_price:.2f}% price distance)")

        # Target calculations based on Hard Stop risk
        if direction == "LONG":
            tp1 = round(entry + 1.5 * risk_per_unit, 2)
            tp2 = round(entry + 2.0 * risk_per_unit, 2)
            tp3 = round(entry + 3.0 * risk_per_unit, 2)
        else:
            tp1 = round(max(0.0, entry - 1.5 * risk_per_unit), 2)
            tp2 = round(max(0.0, entry - 2.0 * risk_per_unit), 2)
            tp3 = round(max(0.0, entry - 3.0 * risk_per_unit), 2)

        lines.append(f"• Take-Profit Targets (Calculated from Hard-Stop Risk of ${risk_per_unit:,.2f}):")
        lines.append(f"  - 🎯 TP1 (1:1.5 R:R): ${tp1:,.2f}")
        lines.append(f"  - 🎯 TP2 (1:2.0 R:R): ${tp2:,.2f}")
        lines.append(f"  - 🎯 TP3 (1:3.0 R:R): ${tp3:,.2f}")

        if cap is not None and risk_pct is not None:
            try:
                r_res = calculate_position_risk(capital=cap, risk_pct=risk_pct, entry_price=entry, stop_loss_price=hard_sl, direction=direction)
                lines.append(f"• Account Position Sizing (Capital: ${cap:,.2f} | Risk Budget: {risk_pct:.1f}% / ${r_res.risk_usd:,.2f}):")
                lines.append(f"  - Position Size: {r_res.position_size_coins:,.4f} units (${r_res.position_value_usd:,.2f} total value)")
                lines.append(f"  - Effective Leverage: {r_res.effective_leverage:.2f}x")
            except Exception as e:
                lines.append(f"• Position Sizing Error: {e}")
        elif cap is not None and risk_pct is None:
            lines.append(f"• Position Sizing Note: Capital is ${cap:,.2f}, but Risk Percentage (%) was not specified. Standard risk is 1.0% - 2.0% of capital.")
        elif cap is None and risk_pct is not None:
            lines.append(f"• Position Sizing Note: Risk percentage is {risk_pct:.1f}%, but Account Capital ($) was not provided. Ask user for capital to compute exact coin position size.")

    return "\n".join(lines)


def format_market_state_grounding(
    state: MarketState,
    user_capital: Optional[float] = None,
    user_risk_pct: Optional[float] = None
) -> str:
    """
    Constructs the standardized structured market grounding contract for Gemini context.
    Strictly separates factual data, market structure, indicators, MTF alignment, deterministic setup,
    and deterministic position sizing.
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
        f"• ATR-14 (Wilder Volatility): ${ta.atr_14:,.2f} (Recommended {DEFAULT_ATR_MULTIPLIER}x ATR SL Buffer: ${ta.suggested_sl_distance:,.2f})",
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
        f"• Execution Scenario: {setup.execution_scenario}",
        f"• Current Verified Market Price: {price_str}",
    ]
    if setup.suggested_entry_zone and setup.entry_reference_price is not None:
        setup_lines.append(f"• Proposed Entry Zone: ${setup.suggested_entry_zone[0]:,.2f} - ${setup.suggested_entry_zone[1]:,.2f} (Reference Entry: ${setup.entry_reference_price:,.2f})")
    elif setup.entry_reference_price is not None:
        setup_lines.append(f"• Reference Execution Price: ${setup.entry_reference_price:,.2f}")

    if setup.structural_warning_level is not None:
        setup_lines.append(f"• Structural Warning Level: ${setup.structural_warning_level:,.2f} ({setup.structural_warning_condition})")

    if setup.suggested_sl_level is not None:
        dist_str = f" | Risk Distance: ${setup.hard_sl_distance:,.2f} ({setup.hard_sl_risk_pct:.2f}%)" if setup.hard_sl_distance is not None else ""
        setup_lines.append(f"• Proposed Hard Stop-Loss: ${setup.suggested_sl_level:,.2f}{dist_str}")
        if setup.structural_warning_level is not None:
            setup_lines.append(f"• Structural Invariant: Structural Warning (${setup.structural_warning_level:,.2f}) != Hard Stop Loss (${setup.suggested_sl_level:,.2f})")

    if setup.tp_target_details:
        setup_lines.append("• Calculated Take-Profit Targets:")
        for tp_d in setup.tp_target_details:
            setup_lines.append(f"  - {tp_d}")
    elif setup.suggested_tp_levels:
        tp_strs = [f"${tp:,.2f}" for tp in setup.suggested_tp_levels]
        setup_lines.append(f"• Calculated Take-Profit Targets: {', '.join(tp_strs)}")

    if setup.sr_clearance_status and setup.sr_clearance_status != "N/A":
        setup_lines.append(f"• Support / Resistance Clearance: {setup.sr_clearance_status}")

    if setup.invalidation_level is not None:
        setup_lines.append(f"• Setup Invalidation Level: ${setup.invalidation_level:,.2f} ({setup.invalidation_condition})")

    if setup.reasons:
        setup_lines.append("• Deterministic Rationale:")
        for r in setup.reasons:
            setup_lines.append(f"  - {r}")

    if setup.key_risks:
        setup_lines.append("• Key Identified Risks: " + ", ".join(setup.key_risks))

    # 7. DETERMINISTIC POSITION SIZING (If Capital & Risk% provided)
    if user_capital is not None and user_risk_pct is not None:
        if setup.setup_state not in ("NO_TRADE", "CONFLICTING_SIGNALS", "INSUFFICIENT_DATA") and setup.entry_reference_price and setup.suggested_sl_level:
            try:
                trade_dir = "LONG" if ("LONG" in setup.direction_bias or "BULLISH" in setup.direction_bias) else "SHORT"
                sizing_res = calculate_position_risk(
                    capital=user_capital,
                    risk_pct=user_risk_pct,
                    entry_price=setup.entry_reference_price,
                    stop_loss_price=setup.suggested_sl_level,
                    direction=trade_dir
                )
                setup_lines.append(f"• Deterministic Position Sizing (Capital: ${user_capital:,.2f} | Risk: {user_risk_pct:.1f}% / ${sizing_res.risk_usd:,.2f}):")
                setup_lines.append(f"  - Position Size: {sizing_res.position_size_coins:,.4f} {state.symbol.replace('USDT', '')} (${sizing_res.position_value_usd:,.2f} total value)")
                setup_lines.append(f"  - Effective Leverage: {sizing_res.effective_leverage:.2f}x")
                setup_lines.append(f"  - Risk Per Unit: ${abs(setup.entry_reference_price - setup.suggested_sl_level):,.2f}")
            except Exception as e:
                setup_lines.append(f"• Position Sizing Error: {e}")
    elif user_capital is not None and user_risk_pct is None:
        setup_lines.append(f"• Position Sizing Note: Capital is ${user_capital:,.2f}, but Risk Percentage (%) was not specified. Standard risk is 1.0% - 2.0% of capital.")
    elif user_capital is None and user_risk_pct is not None:
        setup_lines.append(f"• Position Sizing Note: Risk percentage is {user_risk_pct:.1f}%, but Account Capital ($) was not provided. Ask user for capital to compute exact coin position size and dollar exposure.")

    sections.append("\n".join(setup_lines))
    return "\n\n".join(sections)


def select_relevant_memories(query: str, memories: List[Dict[str, Any]], max_memories: int = 5) -> List[Dict[str, Any]]:
    """Scores memories by word-overlap relevance and returns top matches."""
    if not memories:
        return []
    keywords = extract_keywords(query)
    if not keywords:
        return memories[:max_memories]

    scored = []
    for mem in memories:
        text = mem.get("content", "").lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [m for _, m in scored[:max_memories]]
    if not results:
        results = memories[:max_memories]
    return results


def format_prompt_with_context(
    user_query: str,
    relevant_memories: Optional[List[Dict[str, Any]]] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    current_utc_time: Optional[str] = None,
    market_grounding_text: Optional[str] = None,
) -> str:
    """Combines user query, memories, conversation history, and live market grounding into a clean prompt."""
    parts = []

    if current_utc_time is None:
        current_utc_time = get_current_utc_iso()

    header = f"=== CONTEXT & TIME ===\nCurrent UTC Time: {current_utc_time}\n"
    parts.append(header)

    if market_grounding_text:
        parts.append(f"=== LIVE MARKET DATA & DETERMINISTIC CALCULATIONS ===\n{market_grounding_text}\n")

    if relevant_memories:
        mem_lines = ["=== RELEVANT USER MEMORIES ==="]
        for m in relevant_memories:
            c = m.get("content", "")
            t = m.get("created_at", "")
            mem_lines.append(f"- [{t}] {c}")
        parts.append("\n".join(mem_lines) + "\n")

    if conversation_history:
        hist_lines = ["=== RECENT CONVERSATION HISTORY ==="]
        for h in conversation_history:
            role = h.get("role", "user").capitalize()
            content = h.get("content", "")
            hist_lines.append(f"{role}: {content}")
        parts.append("\n".join(hist_lines) + "\n")

    parts.append(f"=== USER QUERY ===\n{user_query}")
    return "\n".join(parts)


def format_prompt_with_memories(user_query: str, relevant_memories: List[Dict[str, Any]]) -> str:
    """Backwards-compatible wrapper."""
    return format_prompt_with_context(user_query, relevant_memories=relevant_memories)


def build_text_payload(prompt: str) -> Dict[str, Any]:
    """Builds standard text payload for Gemini REST API with system instructions."""
    return {
        "system_instruction": {
            "parts": [{"text": TRADING_SYSTEM_INSTRUCTIONS}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
            "topP": 0.8
        }
    }


def format_vision_caption(caption: Optional[str], current_utc_time: str) -> str:
    """Formats image analysis prompt caption."""
    base = caption.strip() if caption else DEFAULT_VISION_PROMPT
    return f"=== CONTEXT ===\nCurrent UTC Time: {current_utc_time}\n\nUser Request: {base}"


def build_vision_payload(
    image_bytes: bytes,
    caption: Optional[str] = None,
    mime_type: str = "image/jpeg",
    current_utc_time: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds multimodal payload for Gemini Vision REST API."""
    if current_utc_time is None:
        current_utc_time = get_current_utc_iso()

    prompt_text = format_vision_caption(caption, current_utc_time)
    b64_data = base64.b64encode(image_bytes).decode("utf-8")

    return {
        "system_instruction": {
            "parts": [{"text": TRADING_SYSTEM_INSTRUCTIONS}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt_text},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64_data
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
            "topP": 0.8
        }
    }
