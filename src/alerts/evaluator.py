"""
Pure-Python Deterministic Alert Evaluation Engine.
Evaluates price thresholds, RSI levels, market structure shifts, and trade setup transitions.
Phase 9 — Deterministic Market Monitoring & Alert System.
"""

import json
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any, List

from alerts.models import AlertDefinition, AlertState, AlertType, AlertTriggerResult
from trading.models import MarketState, TradeSetupEvaluation
from trading.risk_calculator import (
    DEFAULT_ATR_MULTIPLIER,
    calculate_hard_stop,
    calculate_position_risk,
)

PRICE_HYSTERESIS_PCT: float = 0.003  # 0.3% price buffer to clear before re-arming
RSI_HYSTERESIS_PTS: float = 2.0      # 2.0 RSI points to clear before re-arming


def is_cooldown_expired(last_triggered_at_iso: Optional[str], cooldown_minutes: int) -> bool:
    """Checks if the configured cooldown period has elapsed since last trigger."""
    if not last_triggered_at_iso:
        return True
    try:
        # Standardize ISO parse
        clean_ts = last_triggered_at_iso.replace("Z", "+00:00")
        last_dt = datetime.fromisoformat(clean_ts)
        now_dt = datetime.now(timezone.utc)
        diff_secs = (now_dt - last_dt).total_seconds()
        return diff_secs >= (cooldown_minutes * 60.0)
    except Exception:
        return True


def format_threshold_notification(
    alert: AlertDefinition,
    market_state: MarketState,
    trigger_reason: str
) -> str:
    """Formats deterministic price/RSI threshold alert notification."""
    curr_p = market_state.current_price
    price_str = f"${curr_p:,.2f}" if curr_p >= 1.0 else f"${curr_p:.6f}"
    ta = market_state.primary_ta
    ms = market_state.market_structure

    lines = [
        f"🔔 *MARKET ALERT — {market_state.symbol} ({alert.timeframe.upper()})*",
        "",
        f"• *Trigger Event:* {trigger_reason}",
        f"• *Verified Spot Price:* `{price_str}`",
        f"• *1H Market Structure:* {ms.structure_type} ({ms.trend})",
        f"• *RSI-14 (Wilder):* `{ta.rsi_14:.1f}` [{ta.rsi_condition}]",
        f"• *ATR-14 Volatility:* `${ta.atr_14:,.2f}`",
        f"• *Data Source:* {market_state.source} (UTC: {market_state.timestamp})",
        "",
        f"_Use `/ta {market_state.symbol}` for full multi-timeframe analysis._"
    ]
    return "\n".join(lines)


def format_setup_executable_notification(
    alert: AlertDefinition,
    market_state: MarketState,
    setup: TradeSetupEvaluation
) -> str:
    """Formats actionable deterministic trade setup notification with complete trade levels."""
    curr_p = market_state.current_price
    price_str = f"${curr_p:,.2f}" if curr_p >= 1.0 else f"${curr_p:.6f}"
    ta = market_state.primary_ta
    ms = market_state.market_structure

    lines = [
        f"🎯 *ACTIONABLE TRADE SETUP ALERT — {market_state.symbol} ({alert.timeframe.upper()})*",
        "",
        "*[FACT: DETERMINISTIC SETUP VALIDATED]*",
        f"• *Direction Bias:* *{setup.direction_bias}*",
        f"• *Setup State:* `{setup.setup_state}` ({setup.execution_scenario})",
        f"• *Verified Spot Price:* `{price_str}`",
    ]

    if setup.suggested_entry_zone and setup.entry_reference_price is not None:
        lines.append(f"• *Proposed Entry Zone:* `${setup.suggested_entry_zone[0]:,.2f} - ${setup.suggested_entry_zone[1]:,.2f}` (Reference: `${setup.entry_reference_price:,.2f}`)")
    elif setup.entry_reference_price is not None:
        lines.append(f"• *Reference Entry:* `${setup.entry_reference_price:,.2f}`")

    if setup.structural_warning_level is not None:
        lines.append(f"• *Structural Warning Level:* `${setup.structural_warning_level:,.2f}` ({setup.structural_warning_condition})")

    if setup.suggested_sl_level is not None:
        dist_str = f" | Risk Distance: `${setup.hard_sl_distance:,.2f}` (`{setup.hard_sl_risk_pct:.2f}%`)" if setup.hard_sl_distance is not None else ""
        lines.append(f"• *Proposed Hard Stop-Loss:* `${setup.suggested_sl_level:,.2f}`{dist_str}")
        if setup.structural_warning_level is not None:
            lines.append(f"• *Structural Invariant:* Structural Warning (${setup.structural_warning_level:,.2f}) != Hard Stop Loss (${setup.suggested_sl_level:,.2f})")

    if setup.tp_target_details:
        lines.append("")
        lines.append("*[DETERMINISTIC TAKE-PROFIT TARGETS]*")
        for tp_d in setup.tp_target_details:
            lines.append(f"• {tp_d}")
    elif setup.suggested_tp_levels:
        lines.append("")
        lines.append("*[DETERMINISTIC TAKE-PROFIT TARGETS]*")
        tp_strs = [f"`${tp:,.2f}`" for tp in setup.suggested_tp_levels]
        lines.append(f"• Take-Profit Levels: {', '.join(tp_strs)}")

    if setup.sr_clearance_status and setup.sr_clearance_status != "N/A":
        lines.append(f"• *Runway Clearance:* {setup.sr_clearance_status}")

    # Position sizing if configured on alert
    if alert.user_capital and alert.user_risk_pct and setup.entry_reference_price and setup.suggested_sl_level:
        try:
            trade_dir = "LONG" if ("LONG" in setup.direction_bias or "BULLISH" in setup.direction_bias) else "SHORT"
            sizing_res = calculate_position_risk(
                capital=alert.user_capital,
                risk_pct=alert.user_risk_pct,
                entry_price=setup.entry_reference_price,
                stop_loss_price=setup.suggested_sl_level,
                direction=trade_dir
            )
            lines.append("")
            lines.append(f"*[DETERMINISTIC RISK SIZING (${alert.user_capital:,.2f} Capital | {alert.user_risk_pct:.1f}% Risk)]*")
            lines.append(f"• *Max Risk Budget:* `${sizing_res.risk_usd:,.2f}`")
            lines.append(f"• *Recommended Position Size:* `{sizing_res.position_size_coins:,.4f} {market_state.symbol.replace('USDT', '')}` (`${sizing_res.position_value_usd:,.2f}` total value)")
            lines.append(f"• *Effective Leverage:* `{sizing_res.effective_leverage:.2f}x`")
        except Exception:
            pass

    if setup.invalidation_level is not None:
        lines.append("")
        lines.append(f"• *Invalidation Condition:* {setup.invalidation_condition} (${setup.invalidation_level:,.2f})")

    lines.append("")
    lines.append(f"• *Data Source:* {market_state.source} (UTC: {market_state.timestamp})")
    lines.append("⚠️ _This is a deterministic market-condition alert, NOT a guarantee of profit._")
    return "\n".join(lines)


def format_setup_invalidated_notification(
    alert: AlertDefinition,
    market_state: MarketState,
    reason: str
) -> str:
    """Formats setup invalidation notification."""
    curr_p = market_state.current_price
    price_str = f"${curr_p:,.2f}" if curr_p >= 1.0 else f"${curr_p:.6f}"

    lines = [
        f"⚠️ *TRADE SETUP INVALIDATED — {market_state.symbol} ({alert.timeframe.upper()})*",
        "",
        "• *Status:* *NO TRADE / STAND ASIDE*",
        f"• *Current Verified Price:* `{price_str}`",
        f"• *Invalidation Reason:* {reason}",
        f"• *Action Taken:* The monitored setup has been marked *INVALIDATED*.",
        "• *Capital Preservation:* Stand aside until the market establishes a fresh structural base.",
        "",
        f"• *Source:* {market_state.source} (UTC: {market_state.timestamp})"
    ]
    return "\n".join(lines)


class AlertEvaluator:
    """Pure-Python deterministic evaluator for all alert rules."""

    @staticmethod
    def evaluate_alert(
        alert: AlertDefinition,
        market_state: MarketState
    ) -> AlertTriggerResult:
        """
        Evaluates an individual alert rule against a live MarketState snapshot.
        Returns AlertTriggerResult with state transition instructions.
        """
        curr_price = market_state.current_price
        ta = market_state.primary_ta
        ms = market_state.market_structure
        setup = market_state.trade_setup
        a_type = alert.alert_type.upper()

        # 1. Handle COOLDOWN state re-arming check
        if alert.status == AlertState.COOLDOWN.value:
            cooldown_done = is_cooldown_expired(alert.last_triggered_at, alert.cooldown_minutes)
            if not cooldown_done:
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=False,
                    trigger_price=curr_price,
                    trigger_reason="Cooldown active",
                    setup_state=setup.setup_state
                )

            # Check hysteresis clearance before re-arming
            rearm = False
            if a_type == AlertType.PRICE_ABOVE.value and alert.target_value is not None:
                if curr_price <= alert.target_value * (1.0 - PRICE_HYSTERESIS_PCT):
                    rearm = True
            elif a_type == AlertType.PRICE_BELOW.value and alert.target_value is not None:
                if curr_price >= alert.target_value * (1.0 + PRICE_HYSTERESIS_PCT):
                    rearm = True
            elif a_type == AlertType.RSI_OVERBOUGHT.value:
                target_rsi = alert.target_value if alert.target_value is not None else 70.0
                if ta.rsi_14 <= target_rsi - RSI_HYSTERESIS_PTS:
                    rearm = True
            elif a_type == AlertType.RSI_OVERSOLD.value:
                target_rsi = alert.target_value if alert.target_value is not None else 30.0
                if ta.rsi_14 >= target_rsi + RSI_HYSTERESIS_PTS:
                    rearm = True
            elif a_type in (AlertType.SETUP_EXECUTABLE.value, AlertType.PULLBACK_ENTRY.value):
                # Re-arm if market is back in a healthy waiting state
                if setup.setup_state in ("WAIT_FOR_PULLBACK", "WAIT_FOR_BREAKOUT_CONFIRMATION"):
                    rearm = True
            else:
                rearm = True

            if rearm:
                # Alert re-armed, proceed to evaluate in current tick
                alert.status = AlertState.ARMED.value
            else:
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=False,
                    trigger_price=curr_price,
                    trigger_reason="Hysteresis reset pending",
                    setup_state=setup.setup_state
                )

        # 2. Check if alert is paused or disabled
        if alert.status in (AlertState.PAUSED.value, AlertState.DISABLED.value, AlertState.INVALIDATED.value):
            return AlertTriggerResult(
                alert_id=alert.id,
                telegram_user_id=alert.telegram_user_id,
                symbol=alert.symbol,
                triggered=False,
                trigger_price=curr_price,
                trigger_reason=f"Alert is {alert.status}",
                setup_state=setup.setup_state
            )

        # 3. Evaluate Condition based on Alert Type
        # --- Type A: PRICE_ABOVE ---
        if a_type == AlertType.PRICE_ABOVE.value:
            if alert.target_value is not None and curr_price >= alert.target_value:
                reason = f"Spot price (${curr_price:,.2f}) crossed above target threshold (${alert.target_value:,.2f})"
                msg = format_threshold_notification(alert, market_state, reason)
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=True,
                    trigger_price=curr_price,
                    trigger_reason=reason,
                    setup_state=setup.setup_state,
                    notification_text=msg,
                    should_cooldown=(alert.is_recurring == 1),
                    should_disable=(alert.is_recurring == 0)
                )

        # --- Type B: PRICE_BELOW ---
        elif a_type == AlertType.PRICE_BELOW.value:
            if alert.target_value is not None and curr_price <= alert.target_value:
                reason = f"Spot price (${curr_price:,.2f}) crossed below target threshold (${alert.target_value:,.2f})"
                msg = format_threshold_notification(alert, market_state, reason)
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=True,
                    trigger_price=curr_price,
                    trigger_reason=reason,
                    setup_state=setup.setup_state,
                    notification_text=msg,
                    should_cooldown=(alert.is_recurring == 1),
                    should_disable=(alert.is_recurring == 0)
                )

        # --- Type C: RSI_OVERBOUGHT ---
        elif a_type == AlertType.RSI_OVERBOUGHT.value:
            target_rsi = alert.target_value if alert.target_value is not None else 70.0
            if ta.rsi_14 >= target_rsi:
                reason = f"RSI-14 ({ta.rsi_14:.1f}) reached overbought threshold ({target_rsi:.1f})"
                msg = format_threshold_notification(alert, market_state, reason)
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=True,
                    trigger_price=curr_price,
                    trigger_reason=reason,
                    setup_state=setup.setup_state,
                    notification_text=msg,
                    should_cooldown=(alert.is_recurring == 1),
                    should_disable=(alert.is_recurring == 0)
                )

        # --- Type D: RSI_OVERSOLD ---
        elif a_type == AlertType.RSI_OVERSOLD.value:
            target_rsi = alert.target_value if alert.target_value is not None else 30.0
            if ta.rsi_14 <= target_rsi:
                reason = f"RSI-14 ({ta.rsi_14:.1f}) reached oversold threshold ({target_rsi:.1f})"
                msg = format_threshold_notification(alert, market_state, reason)
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=True,
                    trigger_price=curr_price,
                    trigger_reason=reason,
                    setup_state=setup.setup_state,
                    notification_text=msg,
                    should_cooldown=(alert.is_recurring == 1),
                    should_disable=(alert.is_recurring == 0)
                )

        # --- Type E: SETUP_EXECUTABLE ---
        elif a_type == AlertType.SETUP_EXECUTABLE.value:
            if setup.setup_state == "SETUP_READY":
                reason = f"Deterministic trade setup is now confirmed and actionable ({setup.direction_bias})"
                msg = format_setup_executable_notification(alert, market_state, setup)
                hard_sl = setup.suggested_sl_level
                tp1 = setup.suggested_tp_levels[0] if setup.suggested_tp_levels else None
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=True,
                    trigger_price=curr_price,
                    trigger_reason=reason,
                    setup_state=setup.setup_state,
                    hard_sl_price=hard_sl,
                    tp1_price=tp1,
                    notification_text=msg,
                    should_cooldown=(alert.is_recurring == 1),
                    should_disable=(alert.is_recurring == 0)
                )
            elif setup.setup_state == "NO_TRADE" and any("broken below" in r or "broken above" in r for r in setup.reasons):
                reason = setup.reasons[0] if setup.reasons else "Market structure breakdown"
                msg = format_setup_invalidated_notification(alert, market_state, reason)
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=True,
                    trigger_price=curr_price,
                    trigger_reason=reason,
                    setup_state="NO_TRADE",
                    notification_text=msg,
                    should_invalidate=True
                )

        # --- Type F: PULLBACK_ENTRY ---
        elif a_type == AlertType.PULLBACK_ENTRY.value:
            # Check if setup is invalidated by structural breakdown
            if setup.setup_state == "NO_TRADE" and any("broken below" in r or "broken above" in r for r in setup.reasons):
                reason = setup.reasons[0] if setup.reasons else "Market price broke beyond structural warning level"
                msg = format_setup_invalidated_notification(alert, market_state, reason)
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=True,
                    trigger_price=curr_price,
                    trigger_reason=reason,
                    setup_state="NO_TRADE",
                    notification_text=msg,
                    should_invalidate=True
                )

            # Check if price has entered the entry zone or reached EMA20 with confirmed setup
            is_in_zone = False
            if setup.suggested_entry_zone:
                z_min, z_max = sorted(setup.suggested_entry_zone)
                if z_min <= curr_price <= z_max:
                    is_in_zone = True

            if (setup.setup_state == "SETUP_READY") or (is_in_zone and setup.setup_state != "NO_TRADE"):
                reason = f"Price (${curr_price:,.2f}) entered favorable pullback entry zone with valid structure"
                msg = format_setup_executable_notification(alert, market_state, setup)
                hard_sl = setup.suggested_sl_level
                tp1 = setup.suggested_tp_levels[0] if setup.suggested_tp_levels else None
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=True,
                    trigger_price=curr_price,
                    trigger_reason=reason,
                    setup_state=setup.setup_state,
                    hard_sl_price=hard_sl,
                    tp1_price=tp1,
                    notification_text=msg,
                    should_cooldown=(alert.is_recurring == 1),
                    should_disable=(alert.is_recurring == 0)
                )

        # --- Type G: STRUCTURAL_BREAK ---
        elif a_type == AlertType.STRUCTURAL_BREAK.value:
            if curr_price < ms.recent_swing_low or curr_price > ms.recent_swing_high or setup.setup_state == "NO_TRADE":
                reason = f"Price (${curr_price:,.2f}) confirmed structural break of key swing level"
                msg = format_threshold_notification(alert, market_state, reason)
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=True,
                    trigger_price=curr_price,
                    trigger_reason=reason,
                    setup_state=setup.setup_state,
                    notification_text=msg,
                    should_cooldown=(alert.is_recurring == 1),
                    should_disable=(alert.is_recurring == 0)
                )

        # --- Type H: BREAKOUT_CONFIRMATION ---
        elif a_type == AlertType.BREAKOUT_CONFIRMATION.value:
            if setup.setup_state == "WAIT_FOR_BREAKOUT_CONFIRMATION" or curr_price >= ms.resistance_level:
                reason = f"Price (${curr_price:,.2f}) testing resistance at ${ms.resistance_level:,.2f} for confirmed breakout"
                msg = format_setup_executable_notification(alert, market_state, setup)
                return AlertTriggerResult(
                    alert_id=alert.id,
                    telegram_user_id=alert.telegram_user_id,
                    symbol=alert.symbol,
                    triggered=True,
                    trigger_price=curr_price,
                    trigger_reason=reason,
                    setup_state=setup.setup_state,
                    hard_sl_price=setup.suggested_sl_level,
                    tp1_price=setup.suggested_tp_levels[0] if setup.suggested_tp_levels else None,
                    notification_text=msg,
                    should_cooldown=(alert.is_recurring == 1),
                    should_disable=(alert.is_recurring == 0)
                )

        # Default: Not triggered in this evaluation
        return AlertTriggerResult(
            alert_id=alert.id,
            telegram_user_id=alert.telegram_user_id,
            symbol=alert.symbol,
            triggered=False,
            trigger_price=curr_price,
            trigger_reason="Conditions not met",
            setup_state=setup.setup_state
        )
