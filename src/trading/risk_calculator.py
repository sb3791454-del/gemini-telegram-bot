"""
Deterministic Position Sizing and Risk Management Calculator.
Enforces the Foundational Trading Assistant Constitution: CAPITAL PRESERVATION FIRST.
"""

from typing import Optional, List
from trading.models import RiskCalculationResult


def calculate_position_risk(
    capital: float,
    risk_pct: float,
    entry_price: float,
    stop_loss_price: float,
    direction: Optional[str] = None
) -> RiskCalculationResult:
    """
    Calculates exact risk-budgeted position size, dollar exposure, effective leverage,
    and structured Take-Profit targets (1:1.5, 1:2.0, 1:3.0 R:R).
    """
    if capital <= 0:
        raise ValueError("Capital must be greater than zero.")
    if risk_pct <= 0 or risk_pct > 100:
        raise ValueError("Risk percentage must be between 0.1% and 100%.")
    if entry_price <= 0:
        raise ValueError("Entry price must be greater than zero.")
    if stop_loss_price <= 0:
        raise ValueError("Stop-loss price must be greater than zero.")
    if entry_price == stop_loss_price:
        raise ValueError("Entry price and stop-loss price cannot be identical.")

    # Determine trade direction
    if direction:
        trade_dir = direction.strip().upper()
        if trade_dir not in ("LONG", "SHORT"):
            trade_dir = "LONG" if entry_price > stop_loss_price else "SHORT"
    else:
        trade_dir = "LONG" if entry_price > stop_loss_price else "SHORT"

    # Validation of stop loss position relative to direction
    if trade_dir == "LONG" and stop_loss_price >= entry_price:
        raise ValueError("For a LONG position, Stop-Loss must be below Entry price.")
    if trade_dir == "SHORT" and stop_loss_price <= entry_price:
        raise ValueError("For a SHORT position, Stop-Loss must be above Entry price.")

    price_diff = abs(entry_price - stop_loss_price)
    price_risk_pct = (price_diff / entry_price) * 100.0

    risk_usd = capital * (risk_pct / 100.0)
    position_size_coins = risk_usd / price_diff
    position_value_usd = position_size_coins * entry_price
    effective_leverage = position_value_usd / capital

    if trade_dir == "LONG":
        tp1 = entry_price + (1.5 * price_diff)
        tp2 = entry_price + (2.0 * price_diff)
        tp3 = entry_price + (3.0 * price_diff)
    else:
        tp1 = max(0.0, entry_price - (1.5 * price_diff))
        tp2 = max(0.0, entry_price - (2.0 * price_diff))
        tp3 = max(0.0, entry_price - (3.0 * price_diff))

    warnings: List[str] = []
    if risk_pct > 3.0:
        warnings.append(f"⚠️ *زیادہ رسک (High Risk):* {risk_pct:.1f}% رسک فی ٹریڈ کیپٹل پرزرویشن کے اصولوں کے خلاف ہے۔ تجویز کردہ رسک 1% سے 2% ہے۔")
    if effective_leverage > 10.0:
        warnings.append(f"⚠️ *ہائی لیوریج (High Leverage):* {effective_leverage:.1f}x افیکٹیو لیوریج میں لیکویڈیشن کا خطرہ بہت زیادہ ہوتا ہے۔")

    return RiskCalculationResult(
        capital=capital,
        risk_pct=risk_pct,
        risk_usd=risk_usd,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        direction=trade_dir,
        price_risk_pct=price_risk_pct,
        position_size_coins=position_size_coins,
        position_value_usd=position_value_usd,
        effective_leverage=effective_leverage,
        tp1_price=tp1,
        tp2_price=tp2,
        tp3_price=tp3,
        warnings=warnings
    )
