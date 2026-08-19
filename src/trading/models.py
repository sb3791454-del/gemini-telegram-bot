"""Data models for cryptocurrency market data, technical analysis, and risk management."""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class PriceTicker:
    """Normalized spot price response."""
    symbol: str
    price: float
    timestamp: str
    source: str = "Binance Spot"


@dataclass
class Ticker24h:
    """24-hour rolling price statistics."""
    symbol: str
    last_price: float
    price_change: float
    price_change_percent: float
    high_price: float
    low_price: float
    volume: float
    quote_volume: float
    timestamp: str
    source: str = "Binance Spot"


@dataclass
class OrderBookDepth:
    """Order book depth (bids and asks)."""
    symbol: str
    bids: List[Tuple[float, float]]
    asks: List[Tuple[float, float]]
    best_bid: float
    best_ask: float
    spread: float
    spread_percentage: float
    timestamp: str
    source: str = "Binance Order Book"


@dataclass
class Candle:
    """OHLCV Candlestick data point."""
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


@dataclass
class TechnicalAnalysisSummary:
    """Calculated technical indicators and market structure summary."""
    symbol: str
    timeframe: str
    current_price: float
    rsi_14: float
    rsi_condition: str  # Overbought (>70), Oversold (<30), Bullish Neutral, Bearish Neutral
    ema_20: float
    ema_50: float
    ema_200: Optional[float]
    trend: str  # Bullish, Bearish, Neutral
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_bandwidth_pct: float
    atr_14: float
    suggested_sl_distance: float  # 1.5 * ATR
    support_level: float
    resistance_level: float
    timestamp: str
    source: str = "Spot Klines"


@dataclass
class RiskCalculationResult:
    """Deterministic position sizing and risk-to-reward calculation."""
    capital: float
    risk_pct: float
    risk_usd: float
    entry_price: float
    stop_loss_price: float
    direction: str  # LONG or SHORT
    price_risk_pct: float
    position_size_coins: float
    position_value_usd: float
    effective_leverage: float
    tp1_price: float  # 1:1.5 R:R
    tp2_price: float  # 1:2.0 R:R
    tp3_price: float  # 1:3.0 R:R
    warnings: List[str] = field(default_factory=list)
