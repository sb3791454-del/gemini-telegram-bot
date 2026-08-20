"""
Pure-Python Technical Indicator Mathematics, Market Structure, and Trade Setup Evaluator.
Runs natively inside Cloudflare Workers Pyodide runtime with zero C-extensions or external dependencies.
"""

import math
from typing import List, Tuple, Optional, Dict
from trading.risk_calculator import DEFAULT_ATR_MULTIPLIER, calculate_hard_stop
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
    """Calculates Simple Moving Average (SMA) over a given period."""
    if not values:
        return 0.0
    period = min(period, len(values))
    subset = values[-period:]
    return sum(subset) / float(period)


def calculate_ema(values: List[float], period: int) -> float:
    """Calculates Exponential Moving Average (EMA) with standard multiplier 2 / (period + 1)."""
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
    """Calculates Relative Strength Index (RSI-14) using Wilder's Smoothed Moving Average."""
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
    """Calculates Bollinger Bands (Upper, Middle, Lower, Bandwidth %)."""
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
    """Calculates Bollinger Bands %b oscillator: (Price - Lower) / (Upper - Lower)."""
    spread = upper - lower
    if spread <= 0:
        return 0.5
    return (price - lower) / spread


def calculate_atr(candles: List[Candle], period: int = 14) -> float:
    """Calculates Average True Range (ATR-14) using Wilder's smoothing technique."""
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
    Identifies pure price-action pivot swing highs and swing lows using local extrema lookback.
    Returns: (swing_highs, swing_lows).
    """
    if len(candles) < lookback * 2 + 1:
        return [], []

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    swing_highs: List[SwingPoint] = []
    swing_lows: List[SwingPoint] = []

    for i in range(lookback, len(candles) - lookback):
        if all(highs[i] >= highs[i - j] for j in range(1, lookback + 1)) and all(highs[i] > highs[i + j] for j in range(1, lookback + 1)):
            swing_highs.append(SwingPoint(index=i, open_time=candles[i].open_time, price=highs[i], kind="HIGH"))

        if all(lows[i] <= lows[i - j] for j in range(1, lookback + 1)) and all(lows[i] < lows[i + j] for j in range(1, lookback + 1)):
            swing_lows.append(SwingPoint(index=i, open_time=candles[i].open_time, price=lows[i], kind="LOW"))

    return swing_highs, swing_lows


def analyze_market_structure(
    symbol: str,
    timeframe: str,
    candles: List[Candle],
    lookback_window: int = 30
) -> MarketStructureSummary:
    """
    Analyzes swing sequences to classify market structure:
    - Bullish Structure: Higher Highs (HH) + Higher Lows (HL)
    - Bearish Structure: Lower Highs (LH) + Lower Lows (LL)
    - Breakout / Breakdown attempt
    - Range-Bound / Consolidation
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
    first_close = closes[0]

    effective_lookback = min(lookback_window, len(candles))
    resistance_level = max(highs[-effective_lookback:])
    support_level = min(lows[-effective_lookback:])

    sh_points, sl_points = calculate_swing_points(candles, lookback=2)
    sh_prices = [p.price for p in sh_points]
    sl_prices = [p.price for p in sl_points]

    recent_swing_high = sh_prices[-1] if sh_prices else resistance_level
    recent_swing_low = sl_prices[-1] if sl_prices else support_level

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

    support_zone = (round(support_level * 0.995, 2), round(support_level * 1.005, 2))
    resistance_zone = (round(resistance_level * 0.995, 2), round(resistance_level * 1.005, 2))

    near_resistance = (resistance_level - current_price) / current_price <= 0.006 if current_price > 0 else False
    near_support = (current_price - support_level) / current_price <= 0.006 if current_price > 0 else False
    near_swing_high = (recent_swing_high - current_price) / current_price <= 0.006 if current_price > 0 else False
    near_swing_low = (current_price - recent_swing_low) / current_price <= 0.006 if current_price > 0 else False

    if (hh_count > 0 and ll_count > 0) or (lh_count > 0 and hl_count > 0) or (hh_count == 0 and lh_count == 0 and hl_count == 0 and ll_count == 0):
        if hh_count == 0 and lh_count == 0 and current_price > first_close * 1.01:
            structure_type = "Bullish Expansion (Testing New Highs)"
            trend = "Bullish"
            trend_strength = "Strong"
        elif hh_count == 0 and lh_count == 0 and current_price < first_close * 0.99:
            structure_type = "Bearish Expansion (Testing New Lows)"
            trend = "Bearish"
            trend_strength = "Strong"
        elif near_resistance:
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
    elif (near_resistance or near_swing_high) and current_price >= min(resistance_level, recent_swing_high) * 0.994:
        structure_type = "Potential Breakout Attempt (Testing Resistance)"
        trend = "Bullish"
        trend_strength = "Strong" if hh_count >= lh_count else "Moderate"
    elif (near_support or near_swing_low) and current_price <= max(support_level, recent_swing_low) * 1.006:
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
    Computes multi-timeframe trend alignment, detects confluence versus conflicts,
    and identifies retracements vs relief bounces.
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
    Enforces Core Objectives:
    1. Exact R:R mathematical consistency (Risk = |Entry - Hard SL|; TP = Entry +/- R:R * Risk).
    2. Current price consistency: Evaluates proposed entry and targets against live market price.
    3. Structural warning (e.g. Swing Low/High) clearly distinguished from Hard Stop (1.5x ATR buffer).
    4. Support / Resistance aware targeting: Verifies whether room to major S/R permits a favorable trade.
    5. Execution scenario specificity: Pullback Retest vs Market Execution vs Breakout/Breakdown.
    6. Strict Long / Short symmetry across all logic branches.
    7. 7 Deterministic setup states: SETUP_READY, WAIT_FOR_PULLBACK, WAIT_FOR_BREAKOUT_CONFIRMATION,
       WAIT_FOR_BREAKDOWN_CONFIRMATION, CONFLICTING_SIGNALS, NO_TRADE, INSUFFICIENT_DATA.
    """
    if len(candles) < 15:
        return TradeSetupEvaluation(
            setup_state="INSUFFICIENT_DATA",
            direction_bias="NEUTRAL",
            confidence="None",
            reasons=["Insufficient historical candlestick data (minimum 15 candles required) to evaluate trade setups reliably."],
            execution_scenario="No Action (Data Deficit)",
            invalidation_condition="N/A"
        )

    current_price = ta.current_price
    rsi_14 = ta.rsi_14
    ema_20 = ta.ema_20
    ema_50 = ta.ema_50
    atr_14 = ta.atr_14
    sl_buffer = ta.suggested_sl_distance  # 1.5 * ATR
    pct_b = ta.bb_position_pct
    resistance_level = structure.resistance_level
    support_level = structure.support_level
    recent_swing_high = structure.recent_swing_high
    recent_swing_low = structure.recent_swing_low

    is_bullish_structure = (structure.trend == "Bullish") or (structure.trend != "Neutral" and "Bullish" in ta.trend)
    is_bearish_structure = (structure.trend == "Bearish") or (structure.trend != "Neutral" and "Bearish" in ta.trend)

    # 1. Multi-timeframe conflict check
    if mtf_summary and mtf_summary.has_conflict:
        conflict_note = mtf_summary.conflict_details or mtf_summary.alignment_description
        struct_warning = recent_swing_low if is_bullish_structure else recent_swing_high
        struct_inval = recent_swing_low if is_bullish_structure else recent_swing_high
        hard_sl = round(recent_swing_low - sl_buffer, 2) if is_bullish_structure else round(recent_swing_high + sl_buffer, 2)
        return TradeSetupEvaluation(
            setup_state="CONFLICTING_SIGNALS",
            direction_bias="NEUTRAL / CAUTION",
            confidence="Low",
            reasons=[
                f"Multi-timeframe structure is in conflict: {mtf_summary.alignment_description}.",
                conflict_note,
                "Capital Preservation First: Avoid aggressive entries when higher and lower timeframes oppose each other."
            ],
            execution_scenario="No Action (Stand Aside during Multi-Timeframe Conflict)",
            entry_reference_price=current_price,
            suggested_entry_zone=None,
            structural_warning_level=struct_warning,
            structural_warning_condition=f"Cross of swing level (${struct_warning:,.2f}) indicates structural breakdown in conflicted market.",
            suggested_sl_level=hard_sl,
            hard_sl_distance=round(abs(current_price - hard_sl), 2),
            hard_sl_risk_pct=round(abs(current_price - hard_sl) / current_price * 100.0, 2) if current_price > 0 else 0.0,
            suggested_tp_levels=[],
            tp_target_details=[],
            sr_clearance_status="Target calculation suspended due to opposing timeframe trends.",
            invalidation_level=struct_inval,
            invalidation_condition=f"Break of primary structural boundary (${struct_inval:,.2f}).",
            key_risks=["High chop risk", "False breakout / breakdown risk", "Counter-trend whipsaws"]
        )

    # 2. Check for Neutral / Range-Bound market with no clear directional bias
    if not is_bullish_structure and not is_bearish_structure:
        return TradeSetupEvaluation(
            setup_state="NO_TRADE",
            direction_bias="NEUTRAL",
            confidence="Low",
            reasons=[
                "Market is in a range-bound / consolidation phase without clear directional edge.",
                "Asymmetrical risk-to-reward entry is not currently established.",
                "Capital Preservation First: Stand aside until market establishes a clear structure or breakout."
            ],
            execution_scenario="No Action (Stand Aside in Consolidation)",
            entry_reference_price=current_price,
            suggested_entry_zone=None,
            structural_warning_level=recent_swing_low,
            structural_warning_condition=f"Break of range boundaries (${support_level:,.2f} - ${resistance_level:,.2f}).",
            suggested_sl_level=None,
            hard_sl_distance=None,
            hard_sl_risk_pct=None,
            suggested_tp_levels=[],
            tp_target_details=[],
            sr_clearance_status=f"Range-bound between support (${support_level:,.2f}) and resistance (${resistance_level:,.2f}).",
            invalidation_level=support_level,
            invalidation_condition=f"Break of range boundaries (${support_level:,.2f} - ${resistance_level:,.2f}).",
            key_risks=["Range chop", "Low liquidity decay", "Whipsaw breakouts / breakdowns"]
        )

    dist_ema_atr = abs(current_price - ema_20) / atr_14 if atr_14 > 0 else 0.0

    # Distance to resistance and support metrics
    dist_to_res_pct = (resistance_level - current_price) / current_price if current_price > 0 else 1.0
    dist_to_swing_high_pct = (recent_swing_high - current_price) / current_price if current_price > 0 else 1.0
    near_resistance = (dist_to_res_pct <= 0.006) or (dist_to_swing_high_pct <= 0.006 and dist_to_swing_high_pct >= -0.004)

    dist_to_sup_pct = (current_price - support_level) / current_price if current_price > 0 else 1.0
    dist_to_swing_low_pct = (current_price - recent_swing_low) / current_price if current_price > 0 else 1.0
    near_support = (dist_to_sup_pct <= 0.006) or (dist_to_swing_low_pct <= 0.006 and dist_to_swing_low_pct >= -0.004)

    # 3. Bullish Structure Setups
    if is_bullish_structure:
        # Check if price has broken down below recent swing low
        if current_price < recent_swing_low:
            return TradeSetupEvaluation(
                setup_state="NO_TRADE",
                direction_bias="NEUTRAL / CAUTION",
                confidence="Low",
                reasons=[
                    f"Market price (${current_price:,.2f}) has broken below recent swing low (${recent_swing_low:,.2f}), invalidating the higher-low structure.",
                    "Capital Preservation First: Stand aside until market establishes a new bullish base."
                ],
                execution_scenario="No Action (Bullish Structure Invalidated)",
                entry_reference_price=current_price,
                suggested_entry_zone=None,
                structural_warning_level=recent_swing_low,
                structural_warning_condition=f"Loss of swing low (${recent_swing_low:,.2f}) confirms structural breakdown.",
                suggested_sl_level=None,
                hard_sl_distance=None,
                hard_sl_risk_pct=None,
                suggested_tp_levels=[],
                tp_target_details=[],
                sr_clearance_status=f"Structure broken below swing low (${recent_swing_low:,.2f}).",
                invalidation_level=recent_swing_low,
                invalidation_condition=f"Loss of recent swing low (${recent_swing_low:,.2f}).",
                key_risks=["Structural breakdown", "Deeper correction", "Trend reversal"]
            )

        # A. Testing Resistance -> Breakout Confirmation
        if near_resistance and rsi_14 < 82.0 and dist_ema_atr <= 3.2:
            entry_ref = resistance_level
            entry_zone = (resistance_level, round(resistance_level * 1.003, 2))
            struct_warning = recent_swing_low
            hard_sl = round(recent_swing_low - sl_buffer, 2)
            risk_dist = max(1.0, entry_ref - hard_sl)
            risk_pct = (risk_dist / entry_ref * 100.0) if entry_ref > 0 else 0.0
            tp1 = round(entry_ref + (1.5 * risk_dist), 2)
            tp2 = round(entry_ref + (2.0 * risk_dist), 2)
            tp3 = round(entry_ref + (3.0 * risk_dist), 2)

            tp_details = [
                f"🎯 TP1 (1:1.5 R:R): ${tp1:,.2f} (+${1.5 * risk_dist:,.2f} / +{1.5 * risk_pct:.2f}% from breakout entry)",
                f"🎯 TP2 (1:2.0 R:R): ${tp2:,.2f} (+${2.0 * risk_dist:,.2f} / +{2.0 * risk_pct:.2f}% from breakout entry)",
                f"🎯 TP3 (1:3.0 R:R): ${tp3:,.2f} (+${3.0 * risk_dist:,.2f} / +{3.0 * risk_pct:.2f}% from breakout entry)",
            ]

            return TradeSetupEvaluation(
                setup_state="WAIT_FOR_BREAKOUT_CONFIRMATION",
                direction_bias="BULLISH_WATCH",
                confidence="Moderate",
                reasons=[
                    f"Price (${current_price:,.2f}) is testing key overhead resistance at ${resistance_level:,.2f}.",
                    "Buying directly into resistance without confirmed breakout offers poor Risk-to-Reward.",
                    "Wait for a confirmed candle close above resistance with volume expansion, or wait for the retest."
                ],
                execution_scenario="Conditional Stop/Retest Order on Confirmed Breakout",
                entry_reference_price=entry_ref,
                suggested_entry_zone=entry_zone,
                structural_warning_level=struct_warning,
                structural_warning_condition=f"Candle close below recent swing low (${struct_warning:,.2f}) invalidates bullish momentum.",
                suggested_sl_level=hard_sl,
                hard_sl_distance=round(risk_dist, 2),
                hard_sl_risk_pct=round(risk_pct, 2),
                suggested_tp_levels=[tp1, tp2, tp3],
                tp_target_details=tp_details,
                sr_clearance_status=f"Breakout above ${resistance_level:,.2f} clears immediate overhead resistance.",
                invalidation_level=struct_warning,
                invalidation_condition=f"Failure to break resistance followed by loss of swing low (${struct_warning:,.2f}).",
                key_risks=["Rejection at resistance", "Double top formation", "False breakout / liquidity sweep"]
            )

        # B. Extended / Overbought -> WAIT_FOR_PULLBACK
        if dist_ema_atr > 1.8 or rsi_14 > 72.0 or pct_b > 1.02:
            entry_ref = ema_20
            entry_zone = (round(ema_20 * 0.998, 2), round((current_price + ema_20) / 2.0, 2))
            struct_warning = recent_swing_low
            hard_sl = round(recent_swing_low - sl_buffer, 2)
            risk_dist = max(1.0, entry_ref - hard_sl)
            risk_pct = (risk_dist / entry_ref * 100.0) if entry_ref > 0 else 0.0
            tp1 = round(entry_ref + (1.5 * risk_dist), 2)
            tp2 = round(entry_ref + (2.0 * risk_dist), 2)
            tp3 = round(entry_ref + (3.0 * risk_dist), 2)

            tp1_status = f" (⚠️ Currently below market ${current_price:,.2f} — active only upon pullback)" if tp1 <= current_price else ""
            tp2_status = f" (⚠️ Currently below market ${current_price:,.2f} — active only upon pullback)" if tp2 <= current_price else ""

            tp_details = [
                f"🎯 TP1 (1:1.5 R:R from pullback): ${tp1:,.2f}{tp1_status}",
                f"🎯 TP2 (1:2.0 R:R from pullback): ${tp2:,.2f}{tp2_status}",
                f"🎯 TP3 (1:3.0 R:R from pullback): ${tp3:,.2f}",
            ]

            sr_clearance = f"Overhead resistance at ${resistance_level:,.2f}."
            if tp1 > resistance_level:
                sr_clearance += f" Note: TP1 (${tp1:,.2f}) is above resistance (${resistance_level:,.2f}); monitor price action at resistance."
            else:
                sr_clearance += " Clear runway to TP1 below resistance."

            chase_risk = max(1.0, current_price - hard_sl)
            chase_risk_pct = (chase_risk / current_price * 100.0) if current_price > 0 else 0.0

            return TradeSetupEvaluation(
                setup_state="WAIT_FOR_PULLBACK",
                direction_bias="LONG",
                confidence="Moderate",
                reasons=[
                    f"Trend is Bullish, but price is extended ({dist_ema_atr:.1f}x ATR above EMA20).",
                    f"RSI-14 is at {rsi_14:.1f} (Extreme Bullish Momentum / Overbought threshold). Entering long at market risks buying into local exhaustion.",
                    f"Entering now at ${current_price:,.2f} risks ${chase_risk:,.2f} ({chase_risk_pct:.2f}%) with poor R:R.",
                    f"Recommended strategy: Wait for a controlled pullback toward EMA20 (${ema_20:,.2f}) or Support (${support_level:,.2f}) for a favorable entry."
                ],
                execution_scenario="Conditional Limit Order on Pullback Retest",
                entry_reference_price=entry_ref,
                suggested_entry_zone=entry_zone,
                structural_warning_level=struct_warning,
                structural_warning_condition=f"Break below recent swing low (${struct_warning:,.2f}) degrades bullish momentum.",
                suggested_sl_level=hard_sl,
                hard_sl_distance=round(risk_dist, 2),
                hard_sl_risk_pct=round(risk_pct, 2),
                suggested_tp_levels=[tp1, tp2, tp3],
                tp_target_details=tp_details,
                sr_clearance_status=sr_clearance,
                invalidation_level=struct_warning,
                invalidation_condition=f"Candle close below recent swing low (${struct_warning:,.2f}).",
                key_risks=["Local pullback drawdown", "Late chase exhaustion", "Overhead resistance rejection"]
            )

        # C. Healthy setup near EMA20
        elif dist_ema_atr <= 1.2 and 45.0 <= rsi_14 <= 68.0:
            entry_ref = current_price
            entry_zone = (round(current_price * 0.998, 2), round(current_price * 1.002, 2))
            struct_warning = recent_swing_low
            hard_sl = round(recent_swing_low - sl_buffer, 2)
            risk_dist = max(1.0, entry_ref - hard_sl)
            risk_pct = (risk_dist / entry_ref * 100.0) if entry_ref > 0 else 0.0

            room_to_res = resistance_level - entry_ref
            rr_to_res = (room_to_res / risk_dist) if risk_dist > 0 else 0.0

            # Core Objective #4: Support / Resistance Aware Targeting
            if room_to_res > 0 and rr_to_res < 1.0:
                pullback_entry_ref = ema_20
                pullback_risk = max(1.0, pullback_entry_ref - hard_sl)
                return TradeSetupEvaluation(
                    setup_state="WAIT_FOR_PULLBACK",
                    direction_bias="LONG",
                    confidence="Moderate",
                    reasons=[
                        f"Bullish structure confirmed, but room to overhead resistance (${resistance_level:,.2f}) is only ${room_to_res:,.2f} vs risk of ${risk_dist:,.2f} (R:R 1:{rr_to_res:.2f} < 1:1.0).",
                        "Taking an immediate long here yields unfavorable Risk-to-Reward before encountering major supply.",
                        f"Wait for a deeper pullback toward EMA20 (${ema_20:,.2f}) to improve R:R, or wait for confirmed breakout above ${resistance_level:,.2f}."
                    ],
                    execution_scenario="Conditional Limit Order on Pullback (Unfavorable R:R at Market)",
                    entry_reference_price=pullback_entry_ref,
                    suggested_entry_zone=(round(ema_20 * 0.998, 2), round((current_price + ema_20) / 2.0, 2)),
                    structural_warning_level=struct_warning,
                    structural_warning_condition=f"Break below recent swing low (${struct_warning:,.2f}) degrades bullish momentum.",
                    suggested_sl_level=hard_sl,
                    hard_sl_distance=round(pullback_risk, 2),
                    hard_sl_risk_pct=round(pullback_risk / pullback_entry_ref * 100.0, 2) if pullback_entry_ref > 0 else 0.0,
                    suggested_tp_levels=[
                        round(pullback_entry_ref + 1.5 * pullback_risk, 2),
                        round(pullback_entry_ref + 2.0 * pullback_risk, 2),
                        round(pullback_entry_ref + 3.0 * pullback_risk, 2)
                    ],
                    tp_target_details=[
                        f"🎯 TP1 (from pullback): ${round(pullback_entry_ref + 1.5 * pullback_risk, 2):,.2f}",
                        f"🎯 TP2 (from pullback): ${round(pullback_entry_ref + 2.0 * pullback_risk, 2):,.2f}",
                        f"🎯 TP3 (from pullback): ${round(pullback_entry_ref + 3.0 * pullback_risk, 2):,.2f}",
                    ],
                    sr_clearance_status=f"⚠️ Resistance at ${resistance_level:,.2f} blocks immediate market entry with R:R < 1:1.",
                    invalidation_level=struct_warning,
                    invalidation_condition=f"Candle close below recent swing low (${struct_warning:,.2f}).",
                    key_risks=["Tight overhead resistance", "Rejection before 1:1 R:R reached", "Pullback depth"]
                )

            # Valid SETUP_READY
            tp1 = round(entry_ref + (1.5 * risk_dist), 2)
            tp2 = round(entry_ref + (2.0 * risk_dist), 2)
            tp3 = round(entry_ref + (3.0 * risk_dist), 2)

            mtf_align = mtf_summary.alignment_status if mtf_summary else ""
            conf = "High" if "Aligned Bullish" in mtf_align else "Moderate"

            sr_clearance = f"Major resistance at ${resistance_level:,.2f}."
            if tp1 > resistance_level:
                sr_clearance += f" Note: TP1 (${tp1:,.2f}) is above resistance (${resistance_level:,.2f}); partial take-profit at resistance advised."
            else:
                sr_clearance += f" Clear runway to TP1 below overhead resistance (R:R to resistance: 1:{rr_to_res:.2f})."

            tp_details = [
                f"🎯 TP1 (1:1.5 R:R): ${tp1:,.2f} (+${1.5 * risk_dist:,.2f} / +{1.5 * risk_pct:.2f}%)",
                f"🎯 TP2 (1:2.0 R:R): ${tp2:,.2f} (+${2.0 * risk_dist:,.2f} / +{2.0 * risk_pct:.2f}%)",
                f"🎯 TP3 (1:3.0 R:R): ${tp3:,.2f} (+${3.0 * risk_dist:,.2f} / +{3.0 * risk_pct:.2f}%)",
            ]

            return TradeSetupEvaluation(
                setup_state="SETUP_READY",
                direction_bias="LONG",
                confidence=conf,
                reasons=[
                    "Bullish market structure confirmed (Higher Highs & Higher Lows).",
                    f"Price (${current_price:,.2f}) is well-positioned near dynamic support / EMA20 (${ema_20:,.2f}).",
                    f"RSI ({rsi_14:.1f}) is in a healthy expansion zone with favorable risk-to-reward to targets."
                ],
                execution_scenario="Market Execution at Current Price",
                entry_reference_price=entry_ref,
                suggested_entry_zone=entry_zone,
                structural_warning_level=struct_warning,
                structural_warning_condition=f"Loss of recent swing low (${struct_warning:,.2f}) weakens bullish structure.",
                suggested_sl_level=hard_sl,
                hard_sl_distance=round(risk_dist, 2),
                hard_sl_risk_pct=round(risk_pct, 2),
                suggested_tp_levels=[tp1, tp2, tp3],
                tp_target_details=tp_details,
                sr_clearance_status=sr_clearance,
                invalidation_level=struct_warning,
                invalidation_condition=f"Candle close below recent swing low (${struct_warning:,.2f}).",
                key_risks=["Sudden volume failure", "Break below swing low", "Macro liquidity flush"]
            )

        # D. In-between state -> WAIT_FOR_PULLBACK
        else:
            entry_ref = ema_20
            entry_zone = (round(ema_20 * 0.998, 2), round((current_price + ema_20) / 2.0, 2))
            struct_warning = recent_swing_low
            hard_sl = round(recent_swing_low - sl_buffer, 2)
            risk_dist = max(1.0, entry_ref - hard_sl)
            risk_pct = (risk_dist / entry_ref * 100.0) if entry_ref > 0 else 0.0

            tp1 = round(entry_ref + 1.5 * risk_dist, 2)
            tp2 = round(entry_ref + 2.0 * risk_dist, 2)
            tp3 = round(entry_ref + 3.0 * risk_dist, 2)

            tp1_status = f" (⚠️ Currently below market ${current_price:,.2f} — active only upon pullback)" if tp1 <= current_price else ""
            tp2_status = f" (⚠️ Currently below market ${current_price:,.2f} — active only upon pullback)" if tp2 <= current_price else ""

            tp_details = [
                f"🎯 TP1 (from pullback): ${tp1:,.2f}{tp1_status}",
                f"🎯 TP2 (from pullback): ${tp2:,.2f}{tp2_status}",
                f"🎯 TP3 (from pullback): ${tp3:,.2f}",
            ]

            return TradeSetupEvaluation(
                setup_state="WAIT_FOR_PULLBACK",
                direction_bias="LONG",
                confidence="Moderate",
                reasons=[
                    "Bullish structure intact, but entry at current market price lacks optimal risk-to-reward alignment.",
                    f"Wait for a controlled retracement toward EMA20 (${ema_20:,.2f}) to establish a high-conviction entry."
                ],
                execution_scenario="Conditional Limit Order on Pullback Retest",
                entry_reference_price=entry_ref,
                suggested_entry_zone=entry_zone,
                structural_warning_level=struct_warning,
                structural_warning_condition=f"Break below recent swing low (${struct_warning:,.2f}) degrades bullish momentum.",
                suggested_sl_level=hard_sl,
                hard_sl_distance=round(risk_dist, 2),
                hard_sl_risk_pct=round(risk_pct, 2),
                suggested_tp_levels=[tp1, tp2, tp3],
                tp_target_details=tp_details,
                sr_clearance_status=f"Resistance at ${resistance_level:,.2f}.",
                invalidation_level=struct_warning,
                invalidation_condition=f"Candle close below recent swing low (${struct_warning:,.2f}).",
                key_risks=["Pullback depth", "Overhead resistance"]
            )

    # 4. Bearish Structure Setups (Strict Long/Short Symmetry)
    if is_bearish_structure:
        # Check if price has broken up above recent swing high
        if current_price > recent_swing_high:
            return TradeSetupEvaluation(
                setup_state="NO_TRADE",
                direction_bias="NEUTRAL / CAUTION",
                confidence="Low",
                reasons=[
                    f"Market price (${current_price:,.2f}) has broken above recent swing high (${recent_swing_high:,.2f}), invalidating the lower-high structure.",
                    "Capital Preservation First: Stand aside until market establishes a new bearish ceiling."
                ],
                execution_scenario="No Action (Bearish Structure Invalidated)",
                entry_reference_price=current_price,
                suggested_entry_zone=None,
                structural_warning_level=recent_swing_high,
                structural_warning_condition=f"Reclaim of swing high (${recent_swing_high:,.2f}) confirms structural invalidation.",
                suggested_sl_level=None,
                hard_sl_distance=None,
                hard_sl_risk_pct=None,
                suggested_tp_levels=[],
                tp_target_details=[],
                sr_clearance_status=f"Structure broken above swing high (${recent_swing_high:,.2f}).",
                invalidation_level=recent_swing_high,
                invalidation_condition=f"Reclaim of recent swing high (${recent_swing_high:,.2f}).",
                key_risks=["Structural reclaim", "Short squeeze", "Trend reversal"]
            )

        # A. Pressing Support -> Breakdown Confirmation
        if near_support and rsi_14 > 18.0 and dist_ema_atr <= 3.2:
            entry_ref = support_level
            entry_zone = (round(support_level * 0.997, 2), support_level)
            struct_warning = recent_swing_high
            hard_sl = round(recent_swing_high + sl_buffer, 2)
            risk_dist = max(1.0, hard_sl - entry_ref)
            risk_pct = (risk_dist / entry_ref * 100.0) if entry_ref > 0 else 0.0
            tp1 = round(max(0.0, entry_ref - (1.5 * risk_dist)), 2)
            tp2 = round(max(0.0, entry_ref - (2.0 * risk_dist)), 2)
            tp3 = round(max(0.0, entry_ref - (3.0 * risk_dist)), 2)

            tp_details = [
                f"🎯 TP1 (1:1.5 R:R): ${tp1:,.2f} (-${1.5 * risk_dist:,.2f} / -{1.5 * risk_pct:.2f}% from breakdown entry)",
                f"🎯 TP2 (1:2.0 R:R): ${tp2:,.2f} (-${2.0 * risk_dist:,.2f} / -{2.0 * risk_pct:.2f}% from breakdown entry)",
                f"🎯 TP3 (1:3.0 R:R): ${tp3:,.2f} (-${3.0 * risk_dist:,.2f} / -{3.0 * risk_pct:.2f}% from breakdown entry)",
            ]

            return TradeSetupEvaluation(
                setup_state="WAIT_FOR_BREAKDOWN_CONFIRMATION",
                direction_bias="BEARISH_WATCH",
                confidence="Moderate",
                reasons=[
                    f"Price (${current_price:,.2f}) is pressing key major support at ${support_level:,.2f}.",
                    "Shorting directly into major support without confirmed breakdown offers poor Risk-to-Reward.",
                    "Wait for a confirmed candle close below support with volume expansion, or wait for the breakdown retest."
                ],
                execution_scenario="Conditional Stop/Retest Order on Confirmed Breakdown",
                entry_reference_price=entry_ref,
                suggested_entry_zone=entry_zone,
                structural_warning_level=struct_warning,
                structural_warning_condition=f"Candle close above recent swing high (${struct_warning:,.2f}) invalidates bearish momentum.",
                suggested_sl_level=hard_sl,
                hard_sl_distance=round(risk_dist, 2),
                hard_sl_risk_pct=round(risk_pct, 2),
                suggested_tp_levels=[tp1, tp2, tp3],
                tp_target_details=tp_details,
                sr_clearance_status=f"Breakdown below ${support_level:,.2f} clears immediate underlying support.",
                invalidation_level=struct_warning,
                invalidation_condition=f"Failure to break support followed by reclaim of swing high (${struct_warning:,.2f}).",
                key_risks=["Support bounce / absorption", "Double bottom formation", "False breakdown / liquidity grab"]
            )

        # B. Extended Downward / Oversold -> WAIT_FOR_PULLBACK (Relief Rally)
        if dist_ema_atr > 1.8 or rsi_14 < 28.0 or pct_b < -0.02:
            entry_ref = ema_20
            entry_zone = (round((current_price + ema_20) / 2.0, 2), round(ema_20 * 1.002, 2))
            struct_warning = recent_swing_high
            hard_sl = round(recent_swing_high + sl_buffer, 2)
            risk_dist = max(1.0, hard_sl - entry_ref)
            risk_pct = (risk_dist / entry_ref * 100.0) if entry_ref > 0 else 0.0
            tp1 = round(max(0.0, entry_ref - (1.5 * risk_dist)), 2)
            tp2 = round(max(0.0, entry_ref - (2.0 * risk_dist)), 2)
            tp3 = round(max(0.0, entry_ref - (3.0 * risk_dist)), 2)

            tp1_status = f" (⚠️ Currently above market ${current_price:,.2f} — active only upon relief bounce)" if tp1 >= current_price else ""
            tp2_status = f" (⚠️ Currently above market ${current_price:,.2f} — active only upon relief bounce)" if tp2 >= current_price else ""

            tp_details = [
                f"🎯 TP1 (1:1.5 R:R from bounce): ${tp1:,.2f}{tp1_status}",
                f"🎯 TP2 (1:2.0 R:R from bounce): ${tp2:,.2f}{tp2_status}",
                f"🎯 TP3 (1:3.0 R:R from bounce): ${tp3:,.2f}",
            ]

            sr_clearance = f"Major support at ${support_level:,.2f}."
            if tp1 < support_level:
                sr_clearance += f" Note: TP1 (${tp1:,.2f}) is below major support (${support_level:,.2f}); monitor price action at support."
            else:
                sr_clearance += " Clear runway to TP1 above support."

            chase_risk = max(1.0, hard_sl - current_price)
            chase_risk_pct = (chase_risk / current_price * 100.0) if current_price > 0 else 0.0

            return TradeSetupEvaluation(
                setup_state="WAIT_FOR_PULLBACK",
                direction_bias="SHORT",
                confidence="Moderate",
                reasons=[
                    f"Trend is Bearish, but price is extended ({dist_ema_atr:.1f}x ATR below EMA20).",
                    f"RSI-14 is at {rsi_14:.1f} (Extreme Bearish Momentum / Oversold threshold). Shorting at market risks selling into a relief bounce.",
                    f"Shorting now at ${current_price:,.2f} risks ${chase_risk:,.2f} ({chase_risk_pct:.2f}%) with poor R:R.",
                    f"Recommended strategy: Wait for a relief rally toward EMA20 (${ema_20:,.2f}) or Resistance (${resistance_level:,.2f}) before entering."
                ],
                execution_scenario="Conditional Limit Order on Relief Bounce",
                entry_reference_price=entry_ref,
                suggested_entry_zone=entry_zone,
                structural_warning_level=struct_warning,
                structural_warning_condition=f"Break above recent swing high (${struct_warning:,.2f}) degrades bearish momentum.",
                suggested_sl_level=hard_sl,
                hard_sl_distance=round(risk_dist, 2),
                hard_sl_risk_pct=round(risk_pct, 2),
                suggested_tp_levels=[tp1, tp2, tp3],
                tp_target_details=tp_details,
                sr_clearance_status=sr_clearance,
                invalidation_level=struct_warning,
                invalidation_condition=f"Candle close above recent swing high (${struct_warning:,.2f}).",
                key_risks=["Short-squeeze / relief bounce", "Late short exhaustion", "Major support bounce"]
            )

        # C. Healthy setup near EMA20
        elif dist_ema_atr <= 1.2 and 32.0 <= rsi_14 <= 55.0:
            entry_ref = current_price
            entry_zone = (round(current_price * 0.998, 2), round(current_price * 1.002, 2))
            struct_warning = recent_swing_high
            hard_sl = round(recent_swing_high + sl_buffer, 2)
            risk_dist = max(1.0, hard_sl - entry_ref)
            risk_pct = (risk_dist / entry_ref * 100.0) if entry_ref > 0 else 0.0

            room_to_sup = entry_ref - support_level
            rr_to_sup = (room_to_sup / risk_dist) if risk_dist > 0 else 0.0

            # Core Objective #4: Support / Resistance Aware Targeting
            if room_to_sup > 0 and rr_to_sup < 1.0:
                pullback_entry_ref = ema_20
                pullback_risk = max(1.0, hard_sl - pullback_entry_ref)
                return TradeSetupEvaluation(
                    setup_state="WAIT_FOR_PULLBACK",
                    direction_bias="SHORT",
                    confidence="Moderate",
                    reasons=[
                        f"Bearish structure confirmed, but room to major support (${support_level:,.2f}) is only ${room_to_sup:,.2f} vs risk of ${risk_dist:,.2f} (R:R 1:{rr_to_sup:.2f} < 1:1.0).",
                        "Taking an immediate short here yields unfavorable Risk-to-Reward before encountering major support demand.",
                        f"Wait for a relief bounce toward EMA20 (${ema_20:,.2f}) to improve R:R, or wait for confirmed breakdown below ${support_level:,.2f}."
                    ],
                    execution_scenario="Conditional Limit Order on Relief Bounce (Unfavorable R:R at Market)",
                    entry_reference_price=pullback_entry_ref,
                    suggested_entry_zone=(round((current_price + ema_20) / 2.0, 2), round(ema_20 * 1.002, 2)),
                    structural_warning_level=struct_warning,
                    structural_warning_condition=f"Break above recent swing high (${struct_warning:,.2f}) degrades bearish momentum.",
                    suggested_sl_level=hard_sl,
                    hard_sl_distance=round(pullback_risk, 2),
                    hard_sl_risk_pct=round(pullback_risk / pullback_entry_ref * 100.0, 2) if pullback_entry_ref > 0 else 0.0,
                    suggested_tp_levels=[
                        round(max(0.0, pullback_entry_ref - 1.5 * pullback_risk), 2),
                        round(max(0.0, pullback_entry_ref - 2.0 * pullback_risk), 2),
                        round(max(0.0, pullback_entry_ref - 3.0 * pullback_risk), 2)
                    ],
                    tp_target_details=[
                        f"🎯 TP1 (from bounce): ${round(max(0.0, pullback_entry_ref - 1.5 * pullback_risk), 2):,.2f}",
                        f"🎯 TP2 (from bounce): ${round(max(0.0, pullback_entry_ref - 2.0 * pullback_risk), 2):,.2f}",
                        f"🎯 TP3 (from bounce): ${round(max(0.0, pullback_entry_ref - 3.0 * pullback_risk), 2):,.2f}",
                    ],
                    sr_clearance_status=f"⚠️ Support at ${support_level:,.2f} blocks immediate market short with R:R < 1:1.",
                    invalidation_level=struct_warning,
                    invalidation_condition=f"Candle close above recent swing high (${struct_warning:,.2f}).",
                    key_risks=["Tight underlying support", "Bounce before 1:1 R:R reached", "Short squeeze"]
                )

            # Valid SETUP_READY (Short)
            tp1 = round(max(0.0, entry_ref - (1.5 * risk_dist)), 2)
            tp2 = round(max(0.0, entry_ref - (2.0 * risk_dist)), 2)
            tp3 = round(max(0.0, entry_ref - (3.0 * risk_dist)), 2)

            mtf_align = mtf_summary.alignment_status if mtf_summary else ""
            conf = "High" if "Aligned Bearish" in mtf_align else "Moderate"

            sr_clearance = f"Major support at ${support_level:,.2f}."
            if tp1 < support_level:
                sr_clearance += f" Note: TP1 (${tp1:,.2f}) is below support (${support_level:,.2f}); partial take-profit at support advised."
            else:
                sr_clearance += f" Clear runway to TP1 above underlying support (R:R to support: 1:{rr_to_sup:.2f})."

            tp_details = [
                f"🎯 TP1 (1:1.5 R:R): ${tp1:,.2f} (-${1.5 * risk_dist:,.2f} / -{1.5 * risk_pct:.2f}%)",
                f"🎯 TP2 (1:2.0 R:R): ${tp2:,.2f} (-${2.0 * risk_dist:,.2f} / -{2.0 * risk_pct:.2f}%)",
                f"🎯 TP3 (1:3.0 R:R): ${tp3:,.2f} (-${3.0 * risk_dist:,.2f} / -{3.0 * risk_pct:.2f}%)",
            ]

            return TradeSetupEvaluation(
                setup_state="SETUP_READY",
                direction_bias="SHORT",
                confidence=conf,
                reasons=[
                    "Bearish market structure confirmed (Lower Highs & Lower Lows).",
                    f"Price (${current_price:,.2f}) is well-positioned near dynamic resistance / EMA20 (${ema_20:,.2f}).",
                    f"RSI ({rsi_14:.1f}) indicates active selling pressure with room toward key support."
                ],
                execution_scenario="Market Execution at Current Price",
                entry_reference_price=entry_ref,
                suggested_entry_zone=entry_zone,
                structural_warning_level=struct_warning,
                structural_warning_condition=f"Reclaim of recent swing high (${struct_warning:,.2f}) weakens bearish structure.",
                suggested_sl_level=hard_sl,
                hard_sl_distance=round(risk_dist, 2),
                hard_sl_risk_pct=round(risk_pct, 2),
                suggested_tp_levels=[tp1, tp2, tp3],
                tp_target_details=tp_details,
                sr_clearance_status=sr_clearance,
                invalidation_level=struct_warning,
                invalidation_condition=f"Candle close above recent swing high (${struct_warning:,.2f}).",
                key_risks=["Sudden short squeeze", "Reclaim of swing high", "Support absorption"]
            )

        # D. In-between state -> WAIT_FOR_PULLBACK
        else:
            entry_ref = ema_20
            entry_zone = (round((current_price + ema_20) / 2.0, 2), round(ema_20 * 1.002, 2))
            struct_warning = recent_swing_high
            hard_sl = round(recent_swing_high + sl_buffer, 2)
            risk_dist = max(1.0, hard_sl - entry_ref)
            risk_pct = (risk_dist / entry_ref * 100.0) if entry_ref > 0 else 0.0

            tp1 = round(max(0.0, entry_ref - 1.5 * risk_dist), 2)
            tp2 = round(max(0.0, entry_ref - 2.0 * risk_dist), 2)
            tp3 = round(max(0.0, entry_ref - 3.0 * risk_dist), 2)

            tp1_status = f" (⚠️ Currently above market ${current_price:,.2f} — active only upon relief bounce)" if tp1 >= current_price else ""
            tp2_status = f" (⚠️ Currently above market ${current_price:,.2f} — active only upon relief bounce)" if tp2 >= current_price else ""

            tp_details = [
                f"🎯 TP1 (from bounce): ${tp1:,.2f}{tp1_status}",
                f"🎯 TP2 (from bounce): ${tp2:,.2f}{tp2_status}",
                f"🎯 TP3 (from bounce): ${tp3:,.2f}",
            ]

            return TradeSetupEvaluation(
                setup_state="WAIT_FOR_PULLBACK",
                direction_bias="SHORT",
                confidence="Moderate",
                reasons=[
                    "Bearish structure intact, but entry at current market price lacks optimal risk-to-reward alignment.",
                    f"Wait for a controlled relief bounce toward EMA20 (${ema_20:,.2f}) to establish a high-conviction short entry."
                ],
                execution_scenario="Conditional Limit Order on Relief Bounce",
                entry_reference_price=entry_ref,
                suggested_entry_zone=entry_zone,
                structural_warning_level=struct_warning,
                structural_warning_condition=f"Break above recent swing high (${struct_warning:,.2f}) degrades bearish momentum.",
                suggested_sl_level=hard_sl,
                hard_sl_distance=round(risk_dist, 2),
                hard_sl_risk_pct=round(risk_pct, 2),
                suggested_tp_levels=[tp1, tp2, tp3],
                tp_target_details=tp_details,
                sr_clearance_status=f"Support at ${support_level:,.2f}.",
                invalidation_level=struct_warning,
                invalidation_condition=f"Candle close above recent swing high (${struct_warning:,.2f}).",
                key_risks=["Relief bounce depth", "Underlying support"]
            )

    # 5. Default Fallback -> NO_TRADE
    return TradeSetupEvaluation(
        setup_state="NO_TRADE",
        direction_bias="NEUTRAL",
        confidence="Low",
        reasons=[
            "Market is in a range-bound / consolidation phase without clear directional edge.",
            "Asymmetrical risk-to-reward entry is not currently established.",
            "Capital Preservation First: Stand aside until market establishes a clear structure or breakout."
        ],
        execution_scenario="No Action (Stand Aside in Consolidation)",
        entry_reference_price=current_price,
        suggested_entry_zone=None,
        structural_warning_level=recent_swing_low,
        structural_warning_condition=f"Break of range boundaries (${support_level:,.2f} - ${resistance_level:,.2f}).",
        suggested_sl_level=None,
        hard_sl_distance=None,
        hard_sl_risk_pct=None,
        suggested_tp_levels=[],
        tp_target_details=[],
        sr_clearance_status=f"Range-bound between support (${support_level:,.2f}) and resistance (${resistance_level:,.2f}).",
        invalidation_level=support_level,
        invalidation_condition=f"Break of range boundaries (${support_level:,.2f} - ${resistance_level:,.2f}).",
        key_risks=["Range chop", "Low liquidity decay", "Whipsaw breakouts / breakdowns"]
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
    suggested_sl = atr_val * DEFAULT_ATR_MULTIPLIER

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
