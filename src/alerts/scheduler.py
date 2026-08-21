"""
Scheduled Tick Orchestrator & Multi-Exchange Market Alert Processor.
Phase 9 — Deterministic Market Monitoring & Alert System.
"""

import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from alerts.models import AlertDefinition, AlertState, AlertTriggerResult
from alerts.evaluator import AlertEvaluator
from trading.binance_client import BinanceClient
from telegram.client import TelegramClient
from config.settings import Settings

logger = logging.getLogger("worker.alerts.scheduler")


def _get_utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlertScheduler:
    """Orchestrates scheduled batch evaluation of all active market alerts."""

    def __init__(
        self,
        alert_repo: Any,
        binance_client: BinanceClient,
        telegram_client: TelegramClient,
        settings: Settings
    ):
        self.alert_repo = alert_repo
        self.binance_client = binance_client
        self.telegram_client = telegram_client
        self.settings = settings
        self.max_symbols_per_tick = getattr(settings, "max_symbols_per_tick", 10)

    async def run_scheduled_tick(self) -> Dict[str, Any]:
        """
        Executes a single cron tick:
        1. Queries D1 for all ARMED and COOLDOWN alerts.
        2. Deduplicates symbols to minimize external exchange requests.
        3. Fetches multi-timeframe market data once per symbol in parallel.
        4. Evaluates all alerts in memory.
        5. Dispatches formatted Telegram push notifications.
        6. Updates alert states and logs trigger history in D1.
        """
        now_iso = _get_utc_now_iso()
        stats = {
            "timestamp": now_iso,
            "alerts_found": 0,
            "symbols_evaluated": 0,
            "notifications_sent": 0,
            "errors": []
        }

        if not self.alert_repo.db.is_available:
            logger.warning("Scheduled tick skipped: D1 database unavailable.")
            stats["errors"].append("D1 database unavailable")
            return stats

        # 1. Query active alerts
        try:
            active_alerts = await self.alert_repo.get_all_active_alerts()
            stats["alerts_found"] = len(active_alerts)
        except Exception as e:
            logger.error(f"Error fetching active alerts: {e}")
            stats["errors"].append(f"D1 fetch error: {str(e)}")
            return stats

        if not active_alerts:
            return stats

        # 2. Deduplicate unique symbols (capped by max_symbols_per_tick)
        unique_symbols = list(dict.fromkeys(a.symbol for a in active_alerts))[:self.max_symbols_per_tick]
        stats["symbols_evaluated"] = len(unique_symbols)

        # 3. Fetch live market state for each symbol in parallel
        async def fetch_symbol_state(sym: str):
            try:
                state = await self.binance_client.get_market_state(
                    sym,
                    primary_timeframe="1h",
                    include_mtf=True
                )
                return sym, state, None
            except Exception as ex:
                logger.warning(f"Failed to fetch market state for {sym}: {ex}")
                return sym, None, str(ex)

        fetch_tasks = [fetch_symbol_state(sym) for sym in unique_symbols]
        fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        market_states: Dict[str, Any] = {}
        for res in fetch_results:
            if isinstance(res, tuple) and len(res) == 3:
                sym, state, err = res
                if state:
                    market_states[sym] = state
                elif err:
                    stats["errors"].append(f"Fetch error for {sym}: {err}")

        # 4. Evaluate each alert against its market state
        for alert in active_alerts:
            sym = alert.symbol
            if sym not in market_states:
                # Market data unavailable for this symbol; fail closed safely
                continue

            market_state = market_states[sym]
            try:
                eval_res: AlertTriggerResult = AlertEvaluator.evaluate_alert(alert, market_state)
            except Exception as e:
                logger.error(f"Error evaluating alert {alert.id} ({sym}): {e}")
                stats["errors"].append(f"Eval error for alert {alert.id}: {str(e)}")
                continue

            # State payload snapshot
            state_payload = json.dumps({
                "price": eval_res.trigger_price,
                "setup_state": eval_res.setup_state,
                "rsi_14": market_state.primary_ta.rsi_14,
                "timestamp": now_iso
            })

            # 5. Handle Triggered Alerts
            if eval_res.triggered and eval_res.notification_text:
                try:
                    # Enforce strict user isolation: destination is strictly alert.telegram_user_id
                    chat_id = alert.telegram_user_id
                    await self.telegram_client.send_message(
                        chat_id=chat_id,
                        text=eval_res.notification_text,
                        parse_mode=""  # Plain text mode for robust formatting
                    )
                    stats["notifications_sent"] += 1
                    delivery_status = "DELIVERED"
                except Exception as e:
                    logger.error(f"Failed to deliver notification for alert {alert.id} to user {alert.telegram_user_id}: {e}")
                    delivery_status = f"FAILED: {str(e)[:50]}"
                    stats["errors"].append(f"Telegram send error: {str(e)}")

                # Log trigger history
                try:
                    await self.alert_repo.record_trigger_history(
                        alert_id=alert.id,
                        telegram_user_id=alert.telegram_user_id,
                        symbol=alert.symbol,
                        trigger_price=eval_res.trigger_price,
                        trigger_reason=eval_res.trigger_reason,
                        setup_state=eval_res.setup_state,
                        hard_sl_price=eval_res.hard_sl_price,
                        tp1_price=eval_res.tp1_price,
                        notification_status=delivery_status
                    )
                except Exception as e:
                    logger.error(f"Failed to record trigger history for alert {alert.id}: {e}")

                # Determine next state
                new_status = alert.status
                if eval_res.should_invalidate:
                    new_status = AlertState.INVALIDATED.value
                elif eval_res.should_disable:
                    new_status = AlertState.DISABLED.value
                elif eval_res.should_cooldown:
                    new_status = AlertState.COOLDOWN.value

                try:
                    await self.alert_repo.update_alert_status(
                        alert_id=alert.id,
                        status=new_status,
                        last_triggered_at=now_iso,
                        last_state_payload=state_payload
                    )
                except Exception as e:
                    logger.error(f"Failed to update alert status for alert {alert.id}: {e}")

            else:
                # If alert status was mutated during evaluation (e.g. COOLDOWN -> ARMED on hysteresis clear)
                if alert.status != AlertState.COOLDOWN.value:
                    try:
                        await self.alert_repo.update_alert_status(
                            alert_id=alert.id,
                            status=alert.status,
                            last_triggered_at=alert.last_triggered_at,
                            last_state_payload=state_payload
                        )
                    except Exception as e:
                        logger.error(f"Failed to update rearmed status for alert {alert.id}: {e}")

            # Small sequential delay between alerts to respect Telegram rate limits
            await asyncio.sleep(0.05)

        return stats
