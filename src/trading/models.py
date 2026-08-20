"""Data models for cryptocurrency market data, technical analysis, market structure, and risk management."""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any


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
class SwingPoint:
    """Detected swing high or swing low pivot point."""
    index: int
    open_time: int
    price: float
    kind: str  # "HIGH" or "LOW"


@dataclass
class MarketStructureSummary:
    """Deterministic market structure evaluation from pure OHLCV price action."""
    symbol: str
    timeframe: str
    structure_type: str  # e.g. "Bullish Structure (HH + HL)", "Bearish Structure (LH + LL)", "Consolidation / Range (Equilibrium)"
    trend: str  # "Bullish", "Bearish", "Neutral"
    trend_strength: str  # "Strong", "Moderate", "Weak", "Neutral"
    recent_swing_high: float
    recent_swing_low: float
    support_level: float
    resistance_level: float
    support_zone: Tuple[float, float]
    resistance_zone: Tuple[float, float]
    higher_highs_count: int
    higher_lows_count: int
    lower_highs_count: int
    lower_lows_count: int
    breakout_level: Optional[float] = None
    breakdown_level: Optional[float] = None


@dataclass
class TechnicalAnalysisSummary:
    """Calculated technical indicators and market structure summary."""
    symbol: str
    timeframe: str
    current_price: float
    rsi_14: float
    rsi_condition: str  # "Strong Bullish Momentum (Overbought Threshold)", "Bullish Momentum", etc.
    ema_20: float
    ema_50: float
    ema_200: Optional[float]
    ema_alignment: str
    trend: str  # Bullish, Bearish, Neutral
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_bandwidth_pct: float
    bb_position_pct: float  # %b oscillator (0.0 to 1.0+)
    bb_state: str  # "Inside Bands (Upper Zone)", "Testing Upper Band", etc.
    atr_14: float
    suggested_sl_distance: float  # 1.5 * ATR
    support_level: float
    resistance_level: float
    volatility_state: str  # "Normal Volatility Range", "High Volatility / Expansion", "Volatility Squeeze"
    volume_recent: float
    volume_sma_20: float
    volume_ratio: float
    volume_state: str
    timestamp: str
    source: str = "Spot Klines"


@dataclass
class TimeframeAnalysis:
    """Lightweight single-timeframe summary for multi-timeframe matrices."""
    timeframe: str
    trend: str
    structure_type: str
    rsi_14: float
    current_price: float
    ema_20: float
    ema_50: float


@dataclass
class MultiTimeframeSummary:
    """Multi-timeframe confirmation, alignment, and signal conflict detector."""
    primary_timeframe: str
    timeframes: Dict[str, TimeframeAnalysis]
    alignment_status: str  # "Aligned Bullish", "Aligned Bearish", "Conflicting / Pullback", "Mixed / Choppy"
    alignment_description: str
    has_conflict: bool
    conflict_details: Optional[str] = None


@dataclass
class TradeSetupEvaluation:
    """Deterministic trade setup evaluation based on structure, momentum, and risk."""
    setup_state: str  # SETUP_READY, WAIT_FOR_PULLBACK, WAIT_FOR_BREAKOUT_CONFIRMATION, WAIT_FOR_BREAKDOWN_CONFIRMATION, CONFLICTING_SIGNALS, NO_TRADE, INSUFFICIENT_DATA
    direction_bias: str  # "LONG", "SHORT", "NEUTRAL", "BULLISH_WATCH", "BEARISH_WATCH", "NEUTRAL / CAUTION"
    confidence: str  # "High", "Moderate", "Low", "None"
    reasons: List[str]
    suggested_entry_zone: Optional[Tuple[float, float]] = None
    suggested_sl_level: Optional[float] = None
    suggested_tp_levels: List[float] = field(default_factory=list)
    invalidation_level: Optional[float] = None
    invalidation_condition: str = "N/A"
    key_risks: List[str] = field(default_factory=list)


@dataclass
class MarketState:
    """Complete consolidated market state object combining facts, structure, MTF, and setup evaluation."""
    symbol: str
    primary_timeframe: str
    current_price: float
    timestamp: str
    source: str
    ticker_24h: Optional[Ticker24h]
    primary_ta: TechnicalAnalysisSummary
    market_structure: MarketStructureSummary
    multi_timeframe: Optional[MultiTimeframeSummary]
    trade_setup: TradeSetupEvaluation


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
