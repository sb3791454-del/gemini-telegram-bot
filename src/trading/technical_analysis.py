"""
Pure-Python Technical Indicator Mathematics, Market Structure, and Trade Setup Evaluator.
Runs natively inside Cloudflare Workers Pyodide runtime with zero C-extensions or external dependencies.
"""

import math
from typing import List, Tuple, Optional, Dict
from trading.models import (
    Candle,
    SwingPoint,
    TechnicalAnalysisSummary,
    MarketStructureSummary,
    TimeframeAnalysis,
    MultiTimeframeSummary,
    TradeSetupEvaluation,
)


def calculate_sma(values: List[float], period: int) -> float:
    """Calculates Simple Moving Average for the trailing period."""
    if not values:
        return 0.0
    period = min(period, len(values))
    subset = values[-period:]
    return sum(subset) / float(period)


def calculate_ema(values: List[float], period: int) -> float:
    """
    Calculates Exponential Moving Average using standard multiplier 2 / (period + 1).
    Initial seed value is the SMA of the first 'period' values.
    """
    if not values:
        return 0.0
    if len(values) <= period:
        return sum(values) / float(len(values))

    k = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / float(period)

    for price in values[period:]:
        ema = (price * k) + (ema * (1.0 - k))

    return ema


def calculate_rsi(closes: List[float], period: int = 14) -> float:
    """
    Calculates Wilder Smoothed Relative Strength Index (RSI-14).
    Uses standard Wilder smoothing with initial SMA seed.
    """
    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))

    if len(gains) < period:
        return 50.0

    avg_gain = sum(gains[:period]) / float(period)
    avg_loss = sum(losses[:period]) / float(period)

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / float(period)
        avg_loss = (avg_loss * (period - 1) + losses[i]) / float(period)

    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return max(0.0, min(100.0, rsi))


def calculate_bollinger_bands(closes: List[float], period: int = 20, num_std: float = 2.0) -> Tuple[float, float, float, float]:
    """
    Calculates Bollinger Bands (Upper, Middle SMA, Lower, Bandwidth %).
    """
    if not closes:
        return 0.0, 0.0, 0.0, 0.0

    effective_period = min(period, len(closes))
    sub = closes[-effective_period:]
    mean = sum(sub) / float(effective_period)

    variance = sum((x - mean) ** 2 for x in sub) / float(effective_period)
    std_dev = math.sqrt(variance)

    upper = mean + (num_std * std_dev)
    lower = max(0.0, mean - (num_std * std_dev))
    bandwidth_pct = ((upper - lower) / mean * 100.0) if mean > 0 else 0.0

    return upper, mean, lower, bandwidth_pct


def calculate_bollinger_percent_b(price: float, lower: float, upper: float) -> float:
    """
    Calculates %b oscillator: (Price - Lower) / (Upper - Lower).
    > 1.0 = Above upper band, < 0.0 = Below lower band, 0.5 = At middle band.
    """
    spread = upper - lower
    if spread <= 0:
        return 0.5
    return (price - lower) / spread


def calculate_atr(candles: List[Candle], period: int = 14) -> float:
    """
    Calculates Average True Range (ATR-14) using Wilder smoothing.
    """
    if len(candles) < 2:
        if candles:
            return max(0.0, candles[0].high - candles[0].low)
        return 0.0

    trs = []
    for i in range(1, len(candles)):
        curr = candles[i]
        prev = candles[i - 1]
        tr = max(
            curr.high - curr.low,
            abs(curr.high - prev.close),
            abs(curr.low - prev.close)
        )
        trs.append(tr)

    if not trs:
        return 0.0

    effective_period = min(period, len(trs))
    atr = sum(trs[:effective_period]) / float(effective_period)

    for i in range(effective_period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / float(period)

    return max(0.0, atr)


def calculate_swing_points(candles: List[Candle], lookback: int = 2) -> Tuple[List[SwingPoint], List[SwingPoint]]:
    """
    Detects deterministic local pivot peaks (Swing Highs) and troughs (Swing Lows).
    A candle at index i is a Swing High if it is strictly greater than neighboring highs.
    """
    if len(candles) < lookback * 2 + 1:
        return [], []

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    swing_highs: List[SwingPoint] = []
    swing_lows: List[SwingPoint] = []

    for i in range(lookback, len(candles) - lookback):
        # Check swing high
        if all(highs[i] >= highs[i - j] for j in range(1, lookback + 1)) and \
           all(highs[i] > highs[i + j] for j in range(1, lookback + 1)):
            swing_highs.append(SwingPoint(index=i, open_time=candles[i].open_time, price=highs[i], kind="HIGH"))

        # Check swing low
        if all(lows[i] <= lows[i - j] for j in range(1, lookback + 1)) and \
           all(lows[i] < lows[i + j] for j in range(1, lookback + 1)):
            swing_lows.append(SwingPoint(index=i, open_time=candles[i].open_time, price=lows[i], kind="LOW"))

    return swing_highs, swing_lows


def analyze_market_structure(
    symbol: str,
    timeframe: str,
    candles: List[Candle],
    lookback_window: int = 30
) -> MarketStructureSummary:
    """
    Extracts deterministic market structure from candle sequence:
    Higher Highs, Higher Lows, Lower Highs, Lower Lows, and Support/Resistance zones.
    """
    if not candles:
        return MarketStructureSummary(
            symbol=symbol,
            timeframe=timeframe,
            structure_type="Insufficient Data",
            trend="Neutral",
            trend_strength="None",
            recent_swing_high=0.0,
            recent_swing_low=0.0,
            support_level=0.0,
            resistance_level=0.0,
            support_zone=(0.0, 0.0),
            resistance_zone=(0.0, 0.0),
            higher_highs_count=0,
            higher_lows_count=0,
            lower_highs_count=0,
            lower_lows_count=0
        )

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    current_price = closes[-1]

    # Lookback extremes
    effective_lookback = min(lookback_window, len(candles))
    resistance_level = max(highs[-effective_lookback:])
    support_level = min(lows[-effective_lookback:])

    # Swing high / low detection
    sh_points, sl_points = calculate_swing_points(candles, lookback=2)
    sh_prices = [p.price for p in sh_points]
    sl_prices = [p.price for p in sl_points]

    recent_swing_high = sh_prices[-1] if sh_prices else resistance_level
    recent_swing_low = sl_prices[-1] if sl_prices else support_level

    # Count HH, HL, LH, LL
    hh_count, lh_count = 0, 0
    for k in range(1, len(sh_prices)):
        if sh_prices[k] > sh_prices[k - 1]:
            hh_count += 1
        elif sh_prices[k] < sh_prices[k - 1]:
            lh_count += 1

    hl_count, ll_count = 0, 0
    for k in range(1, len(sl_prices)):
        if sl_prices[k] > sl_prices[k - 1]:
            hl_count += 1
        elif sl_prices[k] < sl_prices[k - 1]:
            ll_count += 1

    # Zones
    support_zone = (round(support_level * 0.995, 2), round(support_level * 1.005, 2))
    resistance_zone = (round(resistance_level * 0.995, 2), round(resistance_level * 1.005, 2))

    # Proximity checks (within 0.4% of lookback extremes)
    near_resistance = (resistance_level - current_price) / current_price <= 0.004 if current_price > 0 else False
    near_support = (current_price - support_level) / current_price <= 0.004 if current_price > 0 else False

    # Structure classification
    if (hh_count > 0 and ll_count > 0) or (lh_count > 0 and hl_count > 0) or (hh_count == 0 and lh_count == 0 and hl_count == 0 and ll_count == 0):
        if near_resistance:
            structure_type = "Consolidation / Range (Testing Upper Boundary)"
            trend = "Neutral"
            trend_strength = "Weak"
        elif near_support:
            structure_type = "Consolidation / Range (Testing Lower Boundary)"
            trend = "Neutral"
            trend_strength = "Weak"
        else:
            structure_type = "Consolidation / Mixed Range (Equilibrium)"
            trend = "Neutral"
            trend_strength = "Weak"
    elif near_resistance and current_price >= recent_swing_high * 0.998:
        structure_type = "Potential Breakout Attempt (Testing Resistance)"
        trend = "Bullish"
        trend_strength = "Strong" if hh_count >= lh_count else "Moderate"
    elif near_support and current_price <= recent_swing_low * 1.002:
        structure_type = "Potential Breakdown Attempt (Testing Support)"
        trend = "Bearish"
        trend_strength = "Strong" if ll_count >= hl_count else "Moderate"
    elif hh_count > lh_count and hl_count >= ll_count:
        structure_type = "Bullish Structure (Higher Highs & Higher Lows)"
        trend = "Bullish"
        trend_strength = "Strong" if hh_count >= 2 and hl_count >= 2 else "Moderate"
    elif lh_count > hh_count and ll_count >= hl_count:
        structure_type = "Bearish Structure (Lower Highs & Lower Lows)"
        trend = "Bearish"
        trend_strength = "Strong" if lh_count >= 2 and ll_count >= 2 else "Moderate"
    else:
        # Fallback to candle price drift
        if current_price > closes[0]:
            structure_type = "Bullish Drift (Upward Momentum)"
            trend = "Bullish"
            trend_strength = "Moderate"
        elif current_price < closes[0]:
            structure_type = "Bearish Drift (Downward Momentum)"
            trend = "Bearish"
            trend_strength = "Moderate"
        else:
            structure_type = "Range-Bound (Flat Market)"
            trend = "Neutral"
            trend_strength = "Neutral"

    return MarketStructureSummary(
        symbol=symbol,
        timeframe=timeframe,
        structure_type=structure_type,
        trend=trend,
        trend_strength=trend_strength,
        recent_swing_high=recent_swing_high,
        recent_swing_low=recent_swing_low,
        support_level=support_level,
        resistance_level=resistance_level,
        support_zone=support_zone,
        resistance_zone=resistance_zone,
        higher_highs_count=hh_count,
        higher_lows_count=hl_count,
        lower_highs_count=lh_count,
        lower_lows_count=ll_count,
        breakout_level=resistance_level,
        breakdown_level=support_level
    )


def determine_mtf_alignment(
    primary_tf: str,
    tf_ta_map: Dict[str, TechnicalAnalysisSummary]
) -> MultiTimeframeSummary:
    """
    Synthesizes multiple timeframe analyses into a unified confluence & conflict summary.
    """
    tf_analyses: Dict[str, TimeframeAnalysis] = {}
    for tf, ta in tf_ta_map.items():
        tf_analyses[tf] = TimeframeAnalysis(
            timeframe=tf,
            trend=ta.trend,
            structure_type=ta.trend,
            rsi_14=ta.rsi_14,
            current_price=ta.current_price,
            ema_20=ta.ema_20,
            ema_50=ta.ema_50
        )

    trends = [ta.trend for ta in tf_ta_map.values()]
    parts = []
    for tf, ta in tf_ta_map.items():
        parts.append(f"{tf.upper()}: {ta.trend}")
    summary_str = " | ".join(parts)

    bull_count = sum(1 for t in trends if "Bullish" in t)
    bear_count = sum(1 for t in trends if "Bearish" in t)
    total = len(trends)

    if bull_count == total and total > 0:
        status = "Aligned Bullish"
        desc = f"{summary_str} => Full Multi-Timeframe Bullish Alignment (High Conviction)"
        has_conflict = False
        conflict_details = None
    elif bear_count == total and total > 0:
        status = "Aligned Bearish"
        desc = f"{summary_str} => Full Multi-Timeframe Bearish Alignment (High Conviction)"
        has_conflict = False
        conflict_details = None
    elif "1d" in tf_ta_map and "Bullish" in tf_ta_map["1d"].trend and "1h" in tf_ta_map and "Bearish" in tf_ta_map["1h"].trend:
        status = "Conflicting / Pullback in Uptrend"
        desc = f"{summary_str} => Lower-timeframe retracement within Higher-timeframe Bull trend"
        has_conflict = True
        conflict_details = "1D Bullish trend is intact while 1H is in a corrective pullback. Watch for support hold before longing."
    elif "1d" in tf_ta_map and "Bearish" in tf_ta_map["1d"].trend and "1h" in tf_ta_map and "Bullish" in tf_ta_map["1h"].trend:
        status = "Conflicting / Relief Bounce in Downtrend"
        desc = f"{summary_str} => Lower-timeframe relief rally against Higher-timeframe Bear trend (Counter-trend risk)"
        has_conflict = True
        conflict_details = "1D Bearish trend dominates while 1H is in a relief bounce. Counter-trend longs carry higher failure risk."
    else:
        status = "Mixed / Choppy Multi-Timeframe"
        desc = f"{summary_str} => Timeframes are mixed without dominant trend consensus"
        has_conflict = (bull_count > 0 and bear_count > 0)
        conflict_details = "Mixed signals across timeframes. High probability of chop or false moves." if has_conflict else None

    return MultiTimeframeSummary(
        primary_timeframe=primary_tf,
        timeframes=tf_analyses,
        alignment_status=status,
        alignment_description=desc,
        has_conflict=has_conflict,
        conflict_details=conflict_details
    )


def evaluate_deterministic_setup(
    symbol: str,
    timeframe: str,
    candles: List[Candle],
    ta: TechnicalAnalysisSummary,
    structure: MarketStructureSummary,
    mtf_summary: Optional[MultiTimeframeSummary] = None
) -> TradeSetupEvaluation:
    """
    Evaluates market conditions deterministically without ever guessing.
    Outputs: SETUP_READY, WAIT_FOR_PULLBACK, WAIT_FOR_BREAKOUT_CONFIRMATION,
    WAIT_FOR_BREAKDOWN_CONFIRMATION, CONFLICTING_SIGNALS, NO_TRADE, or INSUFFICIENT_DATA.
    """
    if len(candles) < 15:
        return TradeSetupEvaluation(
            setup_state="INSUFFICIENT_DATA",
            direction_bias="NEUTRAL",
            confidence="None",
            reasons=["Insufficient historical candlestick data to evaluate trade setups reliably."],
            invalidation_condition="N/A"
        )

    current_price = ta.current_price
    rsi_14 = ta.rsi_14
    ema_20 = ta.ema_20
    atr_14 = ta.atr_14
    sl_buffer = ta.suggested_sl_distance
    pct_b = ta.bb_position_pct
    resistance_level = structure.resistance_level
    support_level = structure.support_level
    recent_swing_high = structure.recent_swing_high
    recent_swing_low = structure.recent_swing_low

    is_bullish_structure = ("Bullish" in structure.trend) or ("Bullish" in ta.trend)
    is_bearish_structure = ("Bearish" in structure.trend) or ("Bearish" in ta.trend)

    # 1. Multi-timeframe conflict check
    if mtf_summary and mtf_summary.has_conflict:
        conflict_note = mtf_summary.conflict_details or mtf_summary.alignment_description
        return TradeSetupEvaluation(
            setup_state="CONFLICTING_SIGNALS",
            direction_bias="NEUTRAL / CAUTION",
            confidence="Low",
            reasons=[
                f"Multi-timeframe structure is in conflict: {mtf_summary.alignment_description}",
                conflict_note,
                "Capital Preservation First: Avoid aggressive entries when timeframes oppose each other."
            ],
            invalidation_level=recent_swing_high if is_bearish_structure else recent_swing_low,
            invalidation_condition=f"Break of key structural boundary (${recent_swing_low:,.2f} / ${recent_swing_high:,.2f}).",
            key_risks=["High chop risk", "False breakout / breakdown risk", "Counter-trend whipsaws"]
        )

    # 2. Testing key resistance or support
    near_resistance = (resistance_level - current_price) / current_price <= 0.004 if current_price > 0 else False
    near_support = (current_price - support_level) / current_price <= 0.004 if current_price > 0 else False

    if near_resistance and current_price >= recent_swing_high * 0.998:
        return TradeSetupEvaluation(
            setup_state="WAIT_FOR_BREAKOUT_CONFIRMATION",
            direction_bias="BULLISH_WATCH",
            confidence="Moderate",
            reasons=[
                f"Price (${current_price:,.2f}) is testing key overhead resistance at ${resistance_level:,.2f}.",
                "Buying directly into resistance without confirmed breakout offers poor Risk-to-Reward.",
                "Wait for a confirmed candle close above resistance with volume expansion, or wait for the retest."
            ],
            suggested_entry_zone=(resistance_level, round(resistance_level * 1.003, 2)),
            suggested_sl_level=round(recent_swing_low - sl_buffer, 2),
            suggested_tp_levels=[
                round(resistance_level + 1.5 * (resistance_level - (recent_swing_low - sl_buffer)), 2),
                round(resistance_level + 2.0 * (resistance_level - (recent_swing_low - sl_buffer)), 2)
            ],
            invalidation_level=recent_swing_low,
            invalidation_condition=f"Failure to break resistance followed by loss of swing low (${recent_swing_low:,.2f}).",
            key_risks=["Rejection at resistance", "Double top formation"]
        )

    if near_support and current_price <= recent_swing_low * 1.002:
        return TradeSetupEvaluation(
            setup_state="WAIT_FOR_BREAKDOWN_CONFIRMATION",
            direction_bias="BEARISH_WATCH",
            confidence="Moderate",
            reasons=[
                f"Price (${current_price:,.2f}) is pressing key major support at ${support_level:,.2f}.",
                "Shorting directly into major support without confirmed breakdown offers poor Risk-to-Reward.",
                "Wait for a confirmed candle close below support with volume expansion, or wait for the breakdown retest."
            ],
            suggested_entry_zone=(round(support_level * 0.997, 2), support_level),
            suggested_sl_level=round(recent_swing_high + sl_buffer, 2),
            suggested_tp_levels=[
                round(max(0.0, support_level - 1.5 * ((recent_swing_high + sl_buffer) - support_level)), 2),
                round(max(0.0, support_level - 2.0 * ((recent_swing_high + sl_buffer) - support_level)), 2)
            ],
            invalidation_level=recent_swing_high,
            invalidation_condition=f"Failure to break support followed by reclaim of swing high (${recent_swing_high:,.2f}).",
            key_risks=["Support bounce / absorption", "Double bottom formation"]
        )

    # 3. Bullish structure setups
    dist_ema_atr = abs(current_price - ema_20) / atr_14 if atr_14 > 0 else 0.0

    if is_bullish_structure:
        if dist_ema_atr > 1.8 or rsi_14 > 72.0 or pct_b > 1.02:
            return TradeSetupEvaluation(
                setup_state="WAIT_FOR_PULLBACK",
                direction_bias="LONG",
                confidence="Moderate",
                reasons=[
                    f"Trend is Bullish, but price is extended ({dist_ema_atr:.1f}x ATR above EMA20).",
                    f"RSI-14 is at {rsi_14:.1f} (Extreme Bullish Momentum / Overbought threshold). Entering long here risks buying the local high.",
                    f"Recommended strategy: Wait for a controlled pullback toward EMA20 (${ema_20:,.2f}) or Support (${support_level:,.2f}) before entering."
                ],
                suggested_entry_zone=(round(ema_20 * 0.998, 2), round((current_price + ema_20) / 2.0, 2)),
                suggested_sl_level=round(recent_swing_low - sl_buffer, 2),
                invalidation_level=recent_swing_low,
                invalidation_condition=f"Break below recent swing low (${recent_swing_low:,.2f}).",
                key_risks=["Local pullback drawdown", "Late chase exhaustion"]
            )
        elif dist_ema_atr <= 1.2 and 45.0 <= rsi_14 <= 68.0:
            mtf_align = mtf_summary.alignment_status if mtf_summary else ""
            conf = "High" if "Aligned Bullish" in mtf_align else "Moderate"
            tp1 = round(current_price + (1.5 * sl_buffer), 2)
            tp2 = round(current_price + (2.0 * sl_buffer), 2)
            tp3 = round(current_price + (3.0 * sl_buffer), 2)
            return TradeSetupEvaluation(
                setup_state="SETUP_READY",
                direction_bias="LONG",
                confidence=conf,
                reasons=[
                    "Bullish market structure confirmed (Higher Highs & Higher Lows).",
                    f"Price is well-positioned near dynamic support / EMA20 (${ema_20:,.2f}).",
                    f"RSI ({rsi_14:.1f}) is in a healthy expansion zone with headroom to resistance (${resistance_level:,.2f})."
                ],
                suggested_entry_zone=(round(current_price * 0.998, 2), round(current_price * 1.002, 2)),
                suggested_sl_level=round(recent_swing_low - sl_buffer, 2),
                suggested_tp_levels=[tp1, tp2, tp3],
                invalidation_level=recent_swing_low,
                invalidation_condition=f"Candle close below recent swing low (${recent_swing_low:,.2f}).",
                key_risks=["Sudden reversal if volume fails", "Break below swing low"]
            )

    # 4. Bearish structure setups
    if is_bearish_structure:
        if dist_ema_atr > 1.8 or rsi_14 < 28.0 or pct_b < -0.02:
            return TradeSetupEvaluation(
                setup_state="WAIT_FOR_PULLBACK",
                direction_bias="SHORT",
                confidence="Moderate",
                reasons=[
                    f"Trend is Bearish, but price is extended ({dist_ema_atr:.1f}x ATR below EMA20).",
                    f"RSI-14 is at {rsi_14:.1f} (Extreme Bearish Momentum / Oversold threshold). Entering short here risks selling into a relief bounce.",
                    f"Recommended strategy: Wait for a relief rally toward EMA20 (${ema_20:,.2f}) or Resistance (${resistance_level:,.2f}) before entering."
                ],
                suggested_entry_zone=(round((current_price + ema_20) / 2.0, 2), round(ema_20 * 1.002, 2)),
                suggested_sl_level=round(recent_swing_high + sl_buffer, 2),
                invalidation_level=recent_swing_high,
                invalidation_condition=f"Break above recent swing high (${recent_swing_high:,.2f}).",
                key_risks=["Short-squeeze / relief bounce", "Late short exhaustion"]
            )
        elif dist_ema_atr <= 1.2 and 32.0 <= rsi_14 <= 55.0:
            mtf_align = mtf_summary.alignment_status if mtf_summary else ""
            conf = "High" if "Aligned Bearish" in mtf_align else "Moderate"
            tp1 = round(max(0.0, current_price - (1.5 * sl_buffer)), 2)
            tp2 = round(max(0.0, current_price - (2.0 * sl_buffer)), 2)
            tp3 = round(max(0.0, current_price - (3.0 * sl_buffer)), 2)
            return TradeSetupEvaluation(
                setup_state="SETUP_READY",
                direction_bias="SHORT",
                confidence=conf,
                reasons=[
                    "Bearish market structure confirmed (Lower Highs & Lower Lows).",
                    f"Price is well-positioned near dynamic resistance / EMA20 (${ema_20:,.2f}).",
                    f"RSI ({rsi_14:.1f}) indicates active selling pressure with room toward key support (${support_level:,.2f})."
                ],
                suggested_entry_zone=(round(current_price * 0.998, 2), round(current_price * 1.002, 2)),
                suggested_sl_level=round(recent_swing_high + sl_buffer, 2),
                suggested_tp_levels=[tp1, tp2, tp3],
                invalidation_level=recent_swing_high,
                invalidation_condition=f"Candle close above recent swing high (${recent_swing_high:,.2f}).",
                key_risks=["Sudden short squeeze", "Break above swing high"]
            )

    # 5. Default Range / No Trade
    return TradeSetupEvaluation(
        setup_state="NO_TRADE",
        direction_bias="NEUTRAL",
        confidence="Low",
        reasons=[
            "Market is in a range-bound / consolidation phase without clear directional edge.",
            "Asymmetrical risk-to-reward entry is not currently established.",
            "Capital Preservation First: Stand aside until market establishes a clear structure or breakout."
        ],
        invalidation_level=support_level,
        invalidation_condition=f"Break of range boundaries (${support_level:,.2f} - ${resistance_level:,.2f}).",
        key_risks=["Range chop", "Low liquidity decay"]
    )


def evaluate_market_structure(
    symbol: str,
    timeframe: str,
    candles: List[Candle],
    timestamp: str,
    source: str = "Spot Klines"
) -> TechnicalAnalysisSummary:
    """
    Produces a unified technical analysis summary from raw OHLCV candles.
    """
    if not candles:
        raise ValueError(f"Cannot evaluate market structure: No candlestick data provided for {symbol}.")

    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    volumes = [c.volume for c in candles]
    current_price = closes[-1]

    # Calculate indicators
    rsi_val = calculate_rsi(closes, period=14)
    if rsi_val >= 70.0:
        rsi_cond = "Strong Bullish Momentum (Overbought Threshold reached — Monitor for exhaustion only if structure breaks)"
    elif rsi_val <= 30.0:
        rsi_cond = "Strong Bearish Momentum (Oversold Threshold reached — Monitor for absorption only if structure holds)"
    elif rsi_val >= 55.0:
        rsi_cond = "Bullish Momentum (Positive Flow)"
    elif rsi_val <= 45.0:
        rsi_cond = "Bearish Momentum (Negative Flow)"
    else:
        rsi_cond = "Neutral / Balanced Momentum"

    ema_20 = calculate_ema(closes, period=20)
    ema_50 = calculate_ema(closes, period=50)
    ema_200 = calculate_ema(closes, period=200) if len(closes) >= 100 else None

    # Trend calculation & EMA alignment
    if current_price > ema_20 and ema_20 >= ema_50:
        trend = "Bullish"
        if ema_200:
            ema_align = "Bullish (Price > EMA20 > EMA50 > EMA200)" if ema_50 >= ema_200 else "Bullish (Price > EMA20 > EMA50, below EMA200)"
        else:
            ema_align = "Bullish (Price > EMA20 > EMA50)"
    elif current_price < ema_20 and ema_20 <= ema_50:
        trend = "Bearish"
        if ema_200:
            ema_align = "Bearish (Price < EMA20 < EMA50 < EMA200)" if ema_50 <= ema_200 else "Bearish (Price < EMA20 < EMA50, above EMA200)"
        else:
            ema_align = "Bearish (Price < EMA20 < EMA50)"
    else:
        trend = "Consolidating / Neutral"
        ema_align = "Mixed / Compressing"

    bb_upper, bb_mid, bb_lower, bb_bw = calculate_bollinger_bands(closes, period=20, num_std=2.0)
    pct_b = calculate_bollinger_percent_b(current_price, bb_lower, bb_upper)

    if pct_b > 1.0:
        bb_state = "Testing Upper Band (High Momentum Expansion)"
    elif pct_b < 0.0:
        bb_state = "Testing Lower Band (High Downward Pressure)"
    elif pct_b >= 0.7:
        bb_state = "Inside Bands (Upper Zone)"
    elif pct_b <= 0.3:
        bb_state = "Inside Bands (Lower Zone)"
    else:
        bb_state = "Inside Bands (Mid-Range)"

    # Volatility state
    if bb_bw <= 3.0:
        vol_state = "Volatility Squeeze / Compression (Potential Breakout Energy)"
    elif bb_bw >= 10.0:
        vol_state = "High Volatility / Expansion"
    else:
        vol_state = "Normal Volatility Range"

    atr_val = calculate_atr(candles, period=14)
    suggested_sl = atr_val * 1.5

    # Volume state
    vol_recent = volumes[-1]
    vol_sma_20 = calculate_sma(volumes, 20)
    vol_ratio = (vol_recent / vol_sma_20) if vol_sma_20 > 0 else 1.0

    if vol_ratio >= 1.5:
        vol_state = f"High Volume Expansion (+{(vol_ratio - 1.0) * 100.0:.0f}% vs 20-SMA)"
    elif vol_ratio <= 0.7:
        vol_state = f"Low / Drying Volume (-{(1.0 - vol_ratio) * 100.0:.0f}% vs 20-SMA)"
    else:
        vol_state = "Normal / Steady Volume"

    # Key Support & Resistance lookback
    lookback = min(30, len(candles))
    resistance = max(highs[-lookback:])
    support = min(lows[-lookback:])

    return TechnicalAnalysisSummary(
        symbol=symbol,
        timeframe=timeframe,
        current_price=current_price,
        rsi_14=rsi_val,
        rsi_condition=rsi_cond,
        ema_20=ema_20,
        ema_50=ema_50,
        ema_200=ema_200,
        ema_alignment=ema_align,
        trend=trend,
        bb_upper=bb_upper,
        bb_middle=bb_mid,
        bb_lower=bb_lower,
        bb_bandwidth_pct=bb_bw,
        bb_position_pct=pct_b,
        bb_state=bb_state,
        atr_14=atr_val,
        suggested_sl_distance=suggested_sl,
        support_level=support,
        resistance_level=resistance,
        volatility_state=vol_state,
        volume_recent=vol_recent,
        volume_sma_20=vol_sma_20,
        volume_ratio=vol_ratio,
        volume_state=vol_state,
        timestamp=timestamp,
        source=source
    )
