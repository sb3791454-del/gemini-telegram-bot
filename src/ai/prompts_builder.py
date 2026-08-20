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
    r"\b(?:chart|charts|technical|ta|analyze|analysis|trend|structure|support|resistance|breakout|breakdown|overbought|oversold|setup|confirmation|candlestick|candle|candles|kline|klines|bullish|bearish|long|short|pullback|retest|entry|invalidation|moving\s+average|moving\s+averages|timeframe|timeframes|time\s+frame|time\s+frames|rsi|ema|sma|bollinger|bb|atr|indicator|indicators|best\s+trade|trade\s+setup|trade\s+plan|trade)\b",
    r"تجزیہ|چارٹ|رجحان|سپورٹ|مزاحمت|انڈیکیٹر|کینڈل|لونگ|شارٹ|بریک آؤٹ|پل بیک|ٹریڈ"
]


def get_current_utc_iso() -> str:
    """Returns the current UTC timestamp formatted as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_keywords(text: str) -> set:
    """Extracts alphanumeric words from text excluding stop words."""
    if not text:
        return set()
    words = re.findall(r"\b[\w\u0600-\u06FF]+\b", text.lower())
    return {w for w in words if len(w) > 2 and w not in STOP_WORDS}


def extract_crypto_symbols(text: str, max_symbols: int = 2) -> List[str]:
    """Detects cryptocurrency symbols or coin names in user messages."""
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
    """Detects requested timeframe (15m, 1h, 4h, 1d, 1w) from natural language query."""
    if not text:
        return None
    lower = text.lower()
    for pattern, canonical in TIMEFRAME_PATTERNS:
        if re.search(pattern, lower, re.IGNORECASE):
            return canonical
    return None


def has_technical_analysis_intent(text: str) -> bool:
    """Detects whether user prompt seeks chart, indicator, trend, or market structure reasoning."""
    if not text:
        return False
    lower = text.lower()
    for pattern in TA_INTENT_PATTERNS:
        if re.search(pattern, lower, re.IGNORECASE):
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

    # Structural Warning / Swing Level
    m_sw = re.search(r"\b(?:structural\s*warning|swing\s*low|swing\s*high|structural\s*level|structural\s*invalidation|warning\s*level|warning)\s*(?:is|of|=|:)?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\b", text, re.IGNORECASE)
    if m_sw:
        try:
            res['structural_warning'] = float(m_sw.group(1).replace(',', ''))
        except Exception:
            pass

    # Hard Stop / Stop Loss
    m_sl = re.search(r"\b(?:hard\s*stop|hard\s*sl|stop\s*loss|stoploss|sl)\s*(?:is|of|=|:)?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\b", text, re.IGNORECASE)
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
        lines.append(f"  Hard Stop requires an ATR volatility buffer (Hard SL = Structural Warning - {DEFAULT_ATR_MULTIPLIER}x ATR for Long).")
        lines.append("  Without ATR or an explicit Hard Stop, exact Hard SL, position size, and Take-Profit levels cannot be computed.")
        lines.append("  Gemini MUST explicitly explain this missing dependency rather than inventing a stop-loss.")
        return "\n".join(lines)

    if entry is not None and hard_sl is not None:
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
        elif cap is not None or risk_pct is not None:
            lines.append("• Sizing Note: Both Capital and Risk% are required for exact position sizing.")

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
        else:
            setup_lines.append(f"• Position Sizing Status: Sizing is NOT applicable because setup state is {setup.setup_state} (no executable trade setup).")
    else:
        setup_lines.append("• Risk Execution Policy: Exact dollar risk and position sizing require user-specified capital and risk percentage via /risk or by specifying 'I have $X capital and risk Y%'.")

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
    Combines system prompt constitution, verified market grounding, user memories,
    and recent session history into a single structured prompt payload for Gemini.
    """
    now_str = current_utc_time or get_current_utc_iso()
    sections = [
        f"[SYSTEM CONSTITUTION & INSTRUCTIONS]\n{TRADING_SYSTEM_INSTRUCTIONS}",
        f"[TEMPORAL GROUNDING]\nCurrent UTC Time: {now_str}"
    ]

    if market_grounding_text:
        sections.append(
            "[LIVE VERIFIED MARKET GROUNDING — STRICT REAL-TIME DATA]\n"
            "The following verified live market data, deterministic technical indicators, market structure, setup evaluations, and risk calculations were computed directly by the deterministic engine at this exact moment.\n"
            "You MUST treat these numbers, indicator calculations, structural classifications, position sizes, and Take-Profit targets as immutable ground truth.\n"
            "Never recalculate, invent, or contradict these figures. Ground your analysis, explanations, and risk advice directly in these facts.\n\n"
            f"{market_grounding_text}"
        )

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

    sections.append(f"[CURRENT USER MESSAGE]\n{user_query}")
    return "\n\n".join(sections)


def format_prompt_with_memories(user_query: str, relevant_memories: List[Dict[str, Any]]) -> str:
    """Helper method for backwards compatibility."""
    return format_prompt_with_context(user_query, relevant_memories=relevant_memories, conversation_history=None)


def build_text_payload(prompt: str) -> Dict[str, Any]:
    """Formats payload for Gemini text generation endpoint."""
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
    """Builds instructions and temporal context for image/chart vision analysis."""
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
    """Encodes image bytes as base64 and bundles with prompt instructions."""
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
