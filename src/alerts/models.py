"""
Data models for Alert definitions, triggers, state machine, and evaluation contexts.
Phase 9 — Deterministic Market Monitoring & Alert System.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List


class AlertState(str, Enum):
    """Finite deterministic states for alert lifecycle."""
    ARMED = "ARMED"              # Actively monitoring on every scheduled tick
    TRIGGERED = "TRIGGERED"      # Condition met and notification dispatched
    COOLDOWN = "COOLDOWN"        # Triggered recurring alert in anti-spam rest window
    INVALIDATED = "INVALIDATED"  # Underlying structural trade thesis invalidated
    PAUSED = "PAUSED"            # Temporarily disabled by user command
    DISABLED = "DISABLED"        # Permanently inactive (e.g. one-shot fired or deleted)


class AlertType(str, Enum):
    """Supported deterministic alert trigger categories."""
    PRICE_ABOVE = "PRICE_ABOVE"
    PRICE_BELOW = "PRICE_BELOW"
    RSI_OVERBOUGHT = "RSI_OVERBOUGHT"
    RSI_OVERSOLD = "RSI_OVERSOLD"
    PULLBACK_ENTRY = "PULLBACK_ENTRY"
    SETUP_EXECUTABLE = "SETUP_EXECUTABLE"
    STRUCTURAL_BREAK = "STRUCTURAL_BREAK"
    BREAKOUT_CONFIRMATION = "BREAKOUT_CONFIRMATION"


@dataclass
class AlertDefinition:
    """Persistent user-configured alert definition."""
    id: int
    telegram_user_id: int
    symbol: str
    alert_type: str
    timeframe: str = "1h"
    target_value: Optional[float] = None
    direction: Optional[str] = None
    status: str = AlertState.ARMED.value
    cooldown_minutes: int = 60
    is_recurring: int = 0
    user_capital: Optional[float] = None
    user_risk_pct: Optional[float] = None
    last_evaluated_at: Optional[str] = None
    last_triggered_at: Optional[str] = None
    last_state_payload: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class AlertTriggerResult:
    """Result of evaluating an alert against live market data."""
    alert_id: int
    telegram_user_id: int
    symbol: str
    triggered: bool
    trigger_price: float
    trigger_reason: str
    setup_state: Optional[str] = None
    hard_sl_price: Optional[float] = None
    tp1_price: Optional[float] = None
    notification_text: Optional[str] = None
    should_cooldown: bool = False
    should_disable: bool = False
    should_invalidate: bool = False
    new_state_payload: Optional[str] = None
