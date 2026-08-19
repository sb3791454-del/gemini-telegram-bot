"""Data models for cryptocurrency market data and trading intelligence."""

from dataclasses import dataclass
from typing import List, Tuple

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
