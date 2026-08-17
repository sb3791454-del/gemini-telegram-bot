"""Normalized market data models for Sultan Assistant trading engine."""

from dataclasses import dataclass
from typing import List, Tuple

@dataclass(frozen=True)
class PriceTicker:
    symbol: str
    price: float
    timestamp: str

@dataclass(frozen=True)
class Ticker24h:
    symbol: str
    last_price: float
    price_change: float
    price_change_percent: float
    high_price: float
    low_price: float
    volume: float
    quote_volume: float
    timestamp: str

@dataclass(frozen=True)
class OrderBookDepth:
    symbol: str
    bids: List[Tuple[float, float]]
    asks: List[Tuple[float, float]]
    best_bid: float
    best_ask: float
    spread: float
    spread_percentage: float
    timestamp: str
