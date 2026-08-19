"""
Pure-Python Technical Indicator Mathematics and Market Structure Analyzer.
Runs natively inside Cloudflare Workers Pyodide runtime with zero C-extensions or external dependencies.
"""

import math
from typing import List, Optional
from trading.models import Candle, TechnicalAnalysisSummary


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


def calculate_bollinger_bands(closes: List[float], period: int = 20, num_std: float = 2.0):
    """
    Calculates Bollinger Bands (Middle SMA, Upper Band, Lower Band, Bandwidth %).
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


def calculate_atr(candles: List[Candle], period: int = 14) -> float:
    """
    Calculates Average True Range (ATR-14) using Wilder smoothing.
    """
    if len(candles) < 2:
        if candles:
            return candles[0].high - candles[0].low
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

    return atr


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
    current_price = closes[-1]

    # Calculate indicators
    rsi_val = calculate_rsi(closes, period=14)
    if rsi_val >= 70.0:
        rsi_cond = "Overbought (زیادہ خریدا گیا - Reversal Risk)"
    elif rsi_val <= 30.0:
        rsi_cond = "Oversold (زیادہ بیچا گیا - Value / Bounce Zone)"
    elif rsi_val >= 50.0:
        rsi_cond = "Bullish Neutral (مثبت دباؤ)"
    else:
        rsi_cond = "Bearish Neutral (منفی دباؤ)"

    ema_20 = calculate_ema(closes, period=20)
    ema_50 = calculate_ema(closes, period=50)
    ema_200 = calculate_ema(closes, period=200) if len(closes) >= 100 else None

    # Trend calculation
    if current_price > ema_20 and ema_20 >= ema_50:
        trend = "Bullish (تیزی کا رجحان)"
    elif current_price < ema_20 and ema_20 <= ema_50:
        trend = "Bearish (مندی کا رجحان)"
    else:
        trend = "Consolidating / Neutral (محدود رینج)"

    bb_upper, bb_mid, bb_lower, bb_bw = calculate_bollinger_bands(closes, period=20, num_std=2.0)
    atr_val = calculate_atr(candles, period=14)
    suggested_sl = atr_val * 1.5

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
        trend=trend,
        bb_upper=bb_upper,
        bb_middle=bb_mid,
        bb_lower=bb_lower,
        bb_bandwidth_pct=bb_bw,
        atr_14=atr_val,
        suggested_sl_distance=suggested_sl,
        support_level=support,
        resistance_level=resistance,
        timestamp=timestamp,
        source=source
    )
