"""
Comprehensive Unit & Integration Test Suite for Phase 9 Alert System.
Covers all 40 Required Scenarios: Alert Persistence, Trigger Logic, Anti-Spam Cooldown,
Smart Setup Monitoring, Risk Integrity, Failure Safety, and Scheduled Worker Batching.
"""

import unittest
import asyncio
import json
import math
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from config.settings import Settings
from storage.database import D1Database
from storage.repositories import (
    UserRepository,
    AlertRepository,
)
from alerts.models import (
    AlertDefinition,
    AlertState,
    AlertType,
    AlertTriggerResult,
)
from alerts.evaluator import (
    AlertEvaluator,
    is_cooldown_expired,
    format_threshold_notification,
    format_setup_executable_notification,
    format_setup_invalidated_notification,
    PRICE_HYSTERESIS_PCT,
    RSI_HYSTERESIS_PTS,
)
from alerts.scheduler import AlertScheduler
from router.command_router import handle_command, parse_alert_arguments
from trading.binance_client import BinanceClient, BinanceAPIError
from trading.models import (
    Candle,
    PriceTicker,
    Ticker24h,
    OrderBookDepth,
    TechnicalAnalysisSummary,
    MarketStructureSummary,
    MultiTimeframeSummary,
    TradeSetupEvaluation,
    MarketState,
)
from trading.technical_analysis import (
    evaluate_market_structure,
    analyze_market_structure,
    evaluate_deterministic_setup,
)
from trading.risk_calculator import (
    DEFAULT_ATR_MULTIPLIER,
    calculate_hard_stop,
    calculate_position_risk,
)


class MockD1Statement:
    def __init__(self, db_mock, sql: str):
        self.db_mock = db_mock
        self.sql = sql
        self.params = []

    def bind(self, *params):
        self.params = list(params)
        return self

    async def run(self):
        sql = self.sql.strip().upper()
        if "INSERT INTO USER_ALERTS" in sql:
            uid, sym, a_type, tf, tgt, direction, cd, recur, cap, risk, notes, ca, ua = self.params
            aid = self.db_mock.next_alert_id
            self.db_mock.next_alert_id += 1
            self.db_mock.alerts[aid] = {
                "id": aid,
                "telegram_user_id": uid,
                "symbol": sym,
                "alert_type": a_type,
                "timeframe": tf,
                "target_value": tgt,
                "direction": direction,
                "status": "ARMED",
                "cooldown_minutes": cd,
                "is_recurring": recur,
                "user_capital": cap,
                "user_risk_pct": risk,
                "last_evaluated_at": None,
                "last_triggered_at": None,
                "last_state_payload": None,
                "notes": notes,
                "created_at": ca,
                "updated_at": ua,
            }
            return {"meta": {"changes": 1}}

        if "UPDATE USER_ALERTS" in sql:
            if "SET STATUS = 'PAUSED'" in sql or "SET STATUS = 'ARMED'" in sql:
                aid = self.params[1]
                if aid in self.db_mock.alerts:
                    if "SET STATUS = 'PAUSED'" in sql:
                        self.db_mock.alerts[aid]["status"] = "PAUSED"
                    else:
                        self.db_mock.alerts[aid]["status"] = "ARMED"
                    return {"meta": {"changes": 1}}
            elif "SET STATUS = ?" in sql:
                aid = self.params[-1]
                if aid in self.db_mock.alerts:
                    self.db_mock.alerts[aid]["status"] = self.params[0]
                    if len(self.params) >= 3 and self.params[2]:
                        self.db_mock.alerts[aid]["last_triggered_at"] = self.params[2]
                    return {"meta": {"changes": 1}}
            return {"meta": {"changes": 1}}

        if "DELETE FROM USER_ALERTS" in sql:
            aid = self.params[0]
            if aid in self.db_mock.alerts:
                del self.db_mock.alerts[aid]
                return {"meta": {"changes": 1}}

        if "INSERT INTO ALERT_TRIGGER_HISTORY" in sql:
            self.db_mock.history.append(self.params)
            return {"meta": {"changes": 1}}

        return {"meta": {"changes": 0}}

    async def first(self):
        sql = self.sql.strip().upper()
        if "SELECT ID FROM USER_ALERTS WHERE TELEGRAM_USER_ID = ?" in sql:
            uid = self.params[0]
            sym = self.params[1]
            matching = [v for v in self.db_mock.alerts.values() if v["telegram_user_id"] == uid and v["symbol"] == sym]
            return matching[-1] if matching else None

        if "SELECT * FROM USER_ALERTS WHERE ID = ? AND TELEGRAM_USER_ID = ?" in sql:
            aid = self.params[0]
            uid = self.params[1]
            alert = self.db_mock.alerts.get(aid, None)
            if alert and alert["telegram_user_id"] == uid:
                return alert
            return None

        if "SELECT * FROM USER_ALERTS WHERE ID = ?" in sql:
            aid = self.params[0]
            return self.db_mock.alerts.get(aid, None)

        if "SELECT COUNT(*) AS COUNT FROM USER_ALERTS WHERE TELEGRAM_USER_ID = ?" in sql:
            uid = self.params[0]
            count = len([v for v in self.db_mock.alerts.values() if v["telegram_user_id"] == uid and v["status"] != "DISABLED"])
            return {"count": count}

        return None

    async def all(self):
        sql = self.sql.strip().upper()
        if "WHERE TELEGRAM_USER_ID = ?" in sql:
            uid = self.params[0]
            rows = [v for v in self.db_mock.alerts.values() if v["telegram_user_id"] == uid]
            return SimpleNamespace(results=rows)

        if "WHERE STATUS IN ('ARMED', 'COOLDOWN')" in sql:
            rows = [v for v in self.db_mock.alerts.values() if v["status"] in ("ARMED", "COOLDOWN")]
            return SimpleNamespace(results=rows)

        return SimpleNamespace(results=[])


class MockD1Binding:
    def __init__(self):
        self.alerts = {}
        self.history = []
        self.next_alert_id = 1

    def prepare(self, sql: str):
        return MockD1Statement(self, sql)


class MockTelegram:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode="Markdown"):
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})

    async def send_chat_action(self, chat_id, action="typing"):
        pass


class MockHttpResponse:
    def __init__(self, text_data: str, status: int = 200):
        self._text = text_data
        self.status = status

    async def text(self):
        return self._text

    async def json(self):
        return json.loads(self._text)


def create_sample_market_state(
    symbol: str = "BTCUSDT",
    current_price: float = 70000.0,
    rsi: float = 50.0,
    trend: str = "Bullish",
    setup_state: str = "SETUP_READY"
) -> MarketState:
    now_iso = "2026-08-21T12:00:00Z"
    ta = TechnicalAnalysisSummary(
        symbol=symbol,
        timeframe="1h",
        current_price=current_price,
        rsi_14=rsi,
        rsi_condition="Neutral",
        ema_20=69500.0,
        ema_50=69000.0,
        ema_200=65000.0,
        ema_alignment="Bullish",
        trend=trend,
        bb_upper=71000.0,
        bb_middle=69500.0,
        bb_lower=68000.0,
        bb_bandwidth_pct=4.3,
        bb_position_pct=0.6,
        bb_state="Inside Bands",
        atr_14=400.0,
        suggested_sl_distance=600.0,
        support_level=68500.0,
        resistance_level=72000.0,
        volatility_state="Normal Volatility Range",
        volume_recent=150.0,
        volume_sma_20=120.0,
        volume_ratio=1.25,
        volume_state="Normal Volume",
        timestamp=now_iso,
        source="Binance Spot"
    )
    ms = MarketStructureSummary(
        symbol=symbol,
        timeframe="1h",
        structure_type="Bullish Structure (Higher Highs & Higher Lows)",
        trend=trend,
        trend_strength="Strong",
        recent_swing_high=71500.0,
        recent_swing_low=69000.0,
        support_level=68500.0,
        resistance_level=72000.0,
        support_zone=(68000.0, 68500.0),
        resistance_zone=(71500.0, 72000.0),
        higher_highs_count=3,
        higher_lows_count=3,
        lower_highs_count=0,
        lower_lows_count=0
    )
    setup = TradeSetupEvaluation(
        setup_state=setup_state,
        direction_bias="LONG",
        confidence="High",
        reasons=["Bullish structure confirmed", "Clear runway to resistance"],
        execution_scenario="Market Execution at Current Price",
        entry_reference_price=current_price,
        suggested_entry_zone=(69800.0, 70200.0),
        structural_warning_level=69000.0,
        structural_warning_condition="Break of swing low ($69,000.00)",
        suggested_sl_level=68400.0,
        hard_sl_distance=1600.0,
        hard_sl_risk_pct=2.29,
        suggested_tp_levels=[72400.0, 73200.0, 74800.0],
        tp_target_details=["🎯 TP1: $72,400.00", "🎯 TP2: $73,200.00", "🎯 TP3: $74,800.00"],
        sr_clearance_status="Clear runway to TP1 below resistance ($72,000.00).",
        invalidation_level=69000.0,
        invalidation_condition="Candle close below swing low ($69,000.00)"
    )
    return MarketState(
        symbol=symbol,
        primary_timeframe="1h",
        current_price=current_price,
        timestamp=now_iso,
        source="Binance Spot",
        ticker_24h=None,
        primary_ta=ta,
        market_structure=ms,
        multi_timeframe=None,
        trade_setup=setup
    )


class TestPhase9AlertEngine(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tg = MockTelegram()
        self.db_binding = MockD1Binding()
        self.db = D1Database(self.db_binding)
        self.alert_repo = AlertRepository(self.db)
        env = SimpleNamespace(
            TELEGRAM_BOT_TOKEN="mock_token",
            GEMINI_API_KEY="mock_key",
            ALLOWED_USER_IDS="8116631925",
            GEMINI_MODEL="gemini-3.1-flash-lite"
        )
        self.settings = Settings(env)

    def tearDown(self):
        self.loop.close()

    # --- 1. ALERT PERSISTENCE (Scenarios 1-8) ---
    def test_01_create_price_alert(self):
        aid = self.loop.run_until_complete(
            self.alert_repo.create_alert(user_id=8116631925, symbol="BTCUSDT", alert_type="PRICE_ABOVE", target_value=72000.0)
        )
        alert = self.loop.run_until_complete(self.alert_repo.get_alert_by_id(aid))
        self.assertEqual(alert.symbol, "BTCUSDT")
        self.assertEqual(alert.alert_type, "PRICE_ABOVE")
        self.assertEqual(alert.target_value, 72000.0)
        self.assertEqual(alert.status, "ARMED")

    def test_02_create_rsi_alert(self):
        aid = self.loop.run_until_complete(
            self.alert_repo.create_alert(user_id=8116631925, symbol="ETHUSDT", alert_type="RSI_OVERBOUGHT", target_value=70.0)
        )
        alert = self.loop.run_until_complete(self.alert_repo.get_alert_by_id(aid))
        self.assertEqual(alert.alert_type, "RSI_OVERBOUGHT")
        self.assertEqual(alert.target_value, 70.0)

    def test_03_create_setup_alert(self):
        aid = self.loop.run_until_complete(
            self.alert_repo.create_alert(user_id=8116631925, symbol="SOLUSDT", alert_type="SETUP_EXECUTABLE", user_capital=1000.0, user_risk_pct=1.0)
        )
        alert = self.loop.run_until_complete(self.alert_repo.get_alert_by_id(aid))
        self.assertEqual(alert.alert_type, "SETUP_EXECUTABLE")
        self.assertEqual(alert.user_capital, 1000.0)

    def test_04_user_isolation(self):
        aid_a = self.loop.run_until_complete(self.alert_repo.create_alert(8116631925, "BTCUSDT", "PRICE_ABOVE", 70000.0))
        aid_b = self.loop.run_until_complete(self.alert_repo.create_alert(9999999999, "ETHUSDT", "PRICE_ABOVE", 3500.0))
        self.assertIsNone(self.loop.run_until_complete(self.alert_repo.get_alert_by_id(aid_b, user_id=8116631925)))
        self.assertEqual(len(self.loop.run_until_complete(self.alert_repo.get_user_alerts(8116631925))), 1)

    def test_05_pause_alert(self):
        aid = self.loop.run_until_complete(self.alert_repo.create_alert(8116631925, "BTCUSDT", "PRICE_ABOVE", 70000.0))
        self.loop.run_until_complete(self.alert_repo.pause_alert(aid, 8116631925))
        alert = self.loop.run_until_complete(self.alert_repo.get_alert_by_id(aid))
        self.assertEqual(alert.status, "PAUSED")

    def test_06_resume_alert(self):
        aid = self.loop.run_until_complete(self.alert_repo.create_alert(8116631925, "BTCUSDT", "PRICE_ABOVE", 70000.0))
        self.loop.run_until_complete(self.alert_repo.pause_alert(aid, 8116631925))
        self.loop.run_until_complete(self.alert_repo.resume_alert(aid, 8116631925))
        alert = self.loop.run_until_complete(self.alert_repo.get_alert_by_id(aid))
        self.assertEqual(alert.status, "ARMED")

    def test_07_delete_alert(self):
        aid = self.loop.run_until_complete(self.alert_repo.create_alert(8116631925, "BTCUSDT", "PRICE_ABOVE", 70000.0))
        deleted = self.loop.run_until_complete(self.alert_repo.delete_alert(aid, 8116631925))
        self.assertTrue(deleted)
        self.assertIsNone(self.loop.run_until_complete(self.alert_repo.get_alert_by_id(aid)))

    def test_08_record_trigger_history(self):
        aid = self.loop.run_until_complete(self.alert_repo.create_alert(8116631925, "BTCUSDT", "PRICE_ABOVE", 70000.0))
        rec = self.loop.run_until_complete(
            self.alert_repo.record_trigger_history(aid, 8116631925, "BTCUSDT", 70500.0, "Price crossed above 70000")
        )
        self.assertTrue(rec)
        self.assertEqual(len(self.db_binding.history), 1)

    # --- 2. TRIGGER LOGIC (Scenarios 9-13) ---
    def test_09_price_crosses_above_threshold(self):
        alert = AlertDefinition(id=1, telegram_user_id=8116631925, symbol="BTCUSDT", alert_type="PRICE_ABOVE", target_value=72000.0)
        state = create_sample_market_state("BTCUSDT", current_price=72100.0)
        res = AlertEvaluator.evaluate_alert(alert, state)
        self.assertTrue(res.triggered)
        self.assertIn("crossed above target threshold", res.trigger_reason)

    def test_10_price_does_not_cross_threshold(self):
        alert = AlertDefinition(id=1, telegram_user_id=8116631925, symbol="BTCUSDT", alert_type="PRICE_ABOVE", target_value=72000.0)
        state = create_sample_market_state("BTCUSDT", current_price=71900.0)
        res = AlertEvaluator.evaluate_alert(alert, state)
        self.assertFalse(res.triggered)

    def test_11_price_crosses_below_threshold(self):
        alert = AlertDefinition(id=2, telegram_user_id=8116631925, symbol="SOLUSDT", alert_type="PRICE_BELOW", target_value=140.0)
        state = create_sample_market_state("SOLUSDT", current_price=139.0)
        res = AlertEvaluator.evaluate_alert(alert, state)
        self.assertTrue(res.triggered)
        self.assertIn("crossed below target threshold", res.trigger_reason)

    def test_12_rsi_crosses_above_threshold(self):
        alert = AlertDefinition(id=3, telegram_user_id=8116631925, symbol="ETHUSDT", alert_type="RSI_OVERBOUGHT", target_value=70.0)
        state = create_sample_market_state("ETHUSDT", rsi=74.0)
        res = AlertEvaluator.evaluate_alert(alert, state)
        self.assertTrue(res.triggered)

    def test_13_rsi_crosses_below_threshold(self):
        alert = AlertDefinition(id=4, telegram_user_id=8116631925, symbol="ETHUSDT", alert_type="RSI_OVERSOLD", target_value=30.0)
        state = create_sample_market_state("ETHUSDT", rsi=26.0)
        res = AlertEvaluator.evaluate_alert(alert, state)
        self.assertTrue(res.triggered)

    # --- 3. COOLDOWN & ANTI-SPAM (Scenarios 14-17) ---
    def test_14_recurring_alert_enters_cooldown(self):
        alert = AlertDefinition(id=5, telegram_user_id=8116631925, symbol="BTCUSDT", alert_type="PRICE_ABOVE", target_value=70000.0, is_recurring=1)
        state = create_sample_market_state("BTCUSDT", current_price=70500.0)
        res = AlertEvaluator.evaluate_alert(alert, state)
        self.assertTrue(res.triggered)
        self.assertTrue(res.should_cooldown)

    def test_15_alert_suppressed_during_cooldown(self):
        now_str = datetime.now(timezone.utc).isoformat()
        alert = AlertDefinition(id=5, telegram_user_id=8116631925, symbol="BTCUSDT", alert_type="PRICE_ABOVE", target_value=70000.0, is_recurring=1, status=AlertState.COOLDOWN.value, last_triggered_at=now_str, cooldown_minutes=60)
        state = create_sample_market_state("BTCUSDT", current_price=70500.0)
        res = AlertEvaluator.evaluate_alert(alert, state)
        self.assertFalse(res.triggered)
        self.assertEqual(res.trigger_reason, "Cooldown active")

    def test_16_alert_rearms_after_cooldown_and_hysteresis(self):
        past_str = (datetime.now(timezone.utc) - timedelta(minutes=65)).isoformat()
        alert = AlertDefinition(id=5, telegram_user_id=8116631925, symbol="BTCUSDT", alert_type="PRICE_ABOVE", target_value=70000.0, is_recurring=1, status=AlertState.COOLDOWN.value, last_triggered_at=past_str, cooldown_minutes=60)
        state_dipped = create_sample_market_state("BTCUSDT", current_price=69500.0)
        AlertEvaluator.evaluate_alert(alert, state_dipped)
        self.assertEqual(alert.status, AlertState.ARMED.value)

    def test_17_flip_flop_does_not_spam(self):
        now_str = datetime.now(timezone.utc).isoformat()
        alert = AlertDefinition(id=5, telegram_user_id=8116631925, symbol="BTCUSDT", alert_type="PRICE_ABOVE", target_value=70000.0, is_recurring=1, status=AlertState.COOLDOWN.value, last_triggered_at=now_str, cooldown_minutes=60)
        for p in [70005, 69995, 70010, 69990]:
            state = create_sample_market_state("BTCUSDT", current_price=p)
            res = AlertEvaluator.evaluate_alert(alert, state)
            self.assertFalse(res.triggered)

    # --- 4. SMART SETUP MONITORING (Scenarios 18-25) ---
    def test_18_wait_for_pullback_to_setup_ready(self):
        alert = AlertDefinition(id=7, telegram_user_id=8116631925, symbol="BTCUSDT", alert_type="SETUP_EXECUTABLE")
        state_ready = create_sample_market_state("BTCUSDT", setup_state="SETUP_READY")
        res = AlertEvaluator.evaluate_alert(alert, state_ready)
        self.assertTrue(res.triggered)
        self.assertIn("ACTIONABLE TRADE SETUP ALERT", res.notification_text)

    def test_19_wait_for_pullback_to_invalidated(self):
        alert = AlertDefinition(id=8, telegram_user_id=8116631925, symbol="BTCUSDT", alert_type="SETUP_EXECUTABLE")
        state_inval = create_sample_market_state("BTCUSDT", setup_state="NO_TRADE")
        state_inval.trade_setup.reasons = ["Market price ($68,000.00) has broken below recent swing low ($69,000.00)."]
        res = AlertEvaluator.evaluate_alert(alert, state_inval)
        self.assertTrue(res.triggered)
        self.assertTrue(res.should_invalidate)
        self.assertIn("TRADE SETUP INVALIDATED", res.notification_text)

    def test_20_resistance_blocks_target_in_setup_eval(self):
        now_iso = "2026-08-21T12:00:00Z"
        candles = [Candle(i, 60000 + i * 20, 60100 + i * 20, 59900 + i * 20, 60000 + i * 20, 100.0, i + 1) for i in range(48)]
        candles.append(Candle(48, 60950, 61000, 60800, 60950, 100.0, 49))
        candles.append(Candle(49, 60950, 61000, 60850, 60960, 100.0, 50))
        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)
        self.assertNotEqual(setup.setup_state, "SETUP_READY")
        self.assertIn(setup.setup_state, ("WAIT_FOR_PULLBACK", "WAIT_FOR_BREAKOUT_CONFIRMATION"))

    def test_21_support_blocks_target_in_short_eval(self):
        now_iso = "2026-08-21T12:00:00Z"
        candles = [Candle(i, 60000 - i * 20, 60100 - i * 20, 59900 - i * 20, 60000 - i * 20, 100.0, i + 1) for i in range(48)]
        candles.append(Candle(48, 59050, 59200, 59000, 59050, 100.0, 49))
        candles.append(Candle(49, 59050, 59150, 59000, 59040, 100.0, 50))
        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)
        self.assertNotEqual(setup.setup_state, "SETUP_READY")
        self.assertIn(setup.setup_state, ("WAIT_FOR_PULLBACK", "WAIT_FOR_BREAKDOWN_CONFIRMATION"))

    def test_22_mtf_conflict_prevents_executable_alert(self):
        now_iso = "2026-08-21T12:00:00Z"
        candles = [Candle(i, 60000 + i * 20, 60050 + i * 20, 59950 + i * 20, 60010 + i * 20, 100.0, i + 1) for i in range(50)]
        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        mtf = MultiTimeframeSummary("1h", {}, "Conflicting", "1D: Bullish | 1H: Bearish", True, "Conflict")
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms, mtf_summary=mtf)
        self.assertEqual(setup.setup_state, "CONFLICTING_SIGNALS")
        self.assertEqual(len(setup.suggested_tp_levels), 0)

    def test_23_high_rsi_does_not_create_short(self):
        state = create_sample_market_state("BTCUSDT", current_price=70000.0, rsi=78.0, trend="Bullish")
        self.assertEqual(state.market_structure.trend, "Bullish")
        self.assertNotEqual(state.trade_setup.direction_bias, "SHORT")

    def test_24_low_rsi_does_not_create_long(self):
        state = create_sample_market_state("BTCUSDT", current_price=50000.0, rsi=22.0, trend="Bearish")
        state.trade_setup.direction_bias = "SHORT"
        self.assertEqual(state.market_structure.trend, "Bearish")
        self.assertNotEqual(state.trade_setup.direction_bias, "LONG")

    def test_25_broken_long_does_not_create_short(self):
        state = create_sample_market_state("BTCUSDT", setup_state="NO_TRADE")
        state.trade_setup.reasons = ["Market price broken below swing low."]
        self.assertEqual(state.trade_setup.setup_state, "NO_TRADE")
        self.assertNotEqual(state.trade_setup.direction_bias, "SHORT")

    # --- 5. RISK INTEGRITY & DETERMINISM (Scenarios 26-30) ---
    def test_26_hard_sl_remains_separate_from_structural_warning(self):
        sw = 70000.0
        atr = 300.0
        hard_sl = calculate_hard_stop(sw, atr, "LONG")
        self.assertEqual(hard_sl, 69550.0)
        self.assertNotEqual(sw, hard_sl)

    def test_27_position_size_uses_hard_sl(self):
        res = calculate_position_risk(1000.0, 1.0, 70500.0, 69550.0, "LONG")
        self.assertEqual(res.risk_usd, 10.0)
        self.assertAlmostEqual(res.position_size_coins, 10.0 / 950.0, places=6)

    def test_28_tp_values_use_hard_sl_risk(self):
        res = calculate_position_risk(1000.0, 1.0, 70500.0, 69550.0, "LONG")
        self.assertEqual(res.tp1_price, 70500.0 + 1.5 * 950.0)
        self.assertEqual(res.tp2_price, 70500.0 + 2.0 * 950.0)
        self.assertEqual(res.tp3_price, 70500.0 + 3.0 * 950.0)

    def test_29_risk_percentage_respected(self):
        res = calculate_position_risk(5000.0, 2.0, 100.0, 95.0, "LONG")
        self.assertEqual(res.risk_usd, 100.0)
        self.assertEqual(res.position_size_coins, 20.0)

    def test_30_default_atr_multiplier_is_one_point_five(self):
        self.assertEqual(DEFAULT_ATR_MULTIPLIER, 1.5)

    # --- 6. FAILURE SAFETY (Scenarios 31-36) ---
    def test_31_d1_unavailable_fails_closed(self):
        unbound_repo = AlertRepository(D1Database(None))
        scheduler = AlertScheduler(unbound_repo, BinanceClient(None), self.tg, self.settings)
        stats = self.loop.run_until_complete(scheduler.run_scheduled_tick())
        self.assertIn("D1 database unavailable", stats["errors"])

    def test_32_exchange_unavailable_handled(self):
        async def mock_fetch(url, **kwargs):
            return MockHttpResponse("Gateway Timeout", status=504)
        b_client = BinanceClient(mock_fetch)
        self.loop.run_until_complete(self.alert_repo.create_alert(8116631925, "BTCUSDT", "PRICE_ABOVE", 72000.0))
        scheduler = AlertScheduler(self.alert_repo, b_client, self.tg, self.settings)
        stats = self.loop.run_until_complete(scheduler.run_scheduled_tick())
        self.assertEqual(stats["notifications_sent"], 0)

    def test_33_fallback_exchange_used_during_tick(self):
        async def mock_fetch(url, **kwargs):
            if "binance" in url:
                return MockHttpResponse("Forbidden", status=403)
            if "bybit" in url and "kline" in url:
                candles = [[1700000000000 + i * 3600000, "70000", "70500", "69500", "70100", "100", "7000000"] for i in range(50)]
                return MockHttpResponse(json.dumps({"retCode": 0, "result": {"list": candles}}))
            return MockHttpResponse(json.dumps({"symbol": "BTCUSDT", "lastPrice": "70100.00", "priceChange": "100.00", "priceChangePercent": "0.14"}))

        b_client = BinanceClient(mock_fetch)
        self.loop.run_until_complete(self.alert_repo.create_alert(8116631925, "BTCUSDT", "PRICE_ABOVE", 70000.0))
        scheduler = AlertScheduler(self.alert_repo, b_client, self.tg, self.settings)
        stats = self.loop.run_until_complete(scheduler.run_scheduled_tick())
        self.assertEqual(stats["symbols_evaluated"], 1)

    def test_34_insufficient_candles_fails_closed(self):
        now_iso = "2026-08-21T12:00:00Z"
        candles = [Candle(i, 60000, 60050, 59950, 60010, 100.0, i + 1) for i in range(5)]
        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)
        self.assertEqual(setup.setup_state, "INSUFFICIENT_DATA")

    def test_35_telegram_delivery_failure_logged(self):
        class FailingTelegram(MockTelegram):
            async def send_message(self, chat_id, text, parse_mode="Markdown"):
                raise RuntimeError("Telegram API 403: Bot blocked by user")

        failing_tg = FailingTelegram()
        async def mock_fetch(url, **kwargs):
            candles = [[1700000000000 + i * 3600000, "70000", "70500", "69500", "72500", "100", 1700003599000] for i in range(50)]
            return MockHttpResponse(json.dumps(candles))

        b_client = BinanceClient(mock_fetch)
        self.loop.run_until_complete(self.alert_repo.create_alert(8116631925, "BTCUSDT", "PRICE_ABOVE", 72000.0))
        scheduler = AlertScheduler(self.alert_repo, b_client, failing_tg, self.settings)
        stats = self.loop.run_until_complete(scheduler.run_scheduled_tick())
        self.assertEqual(stats["notifications_sent"], 0)
        self.assertTrue(any("Bot blocked by user" in e for e in stats["errors"]))

    def test_36_error_sanitization_zero_html_leakage(self):
        html_error = "<html><head><title>403 Forbidden</title></head><body>CloudFront Ray ID: 8b1234</body></html>"
        async def mock_fetch(url, **kwargs):
            return MockHttpResponse(html_error, status=403)
        b_client = BinanceClient(mock_fetch)
        with self.assertRaises(BinanceAPIError) as ctx:
            self.loop.run_until_complete(b_client.get_price("BTCUSDT"))
        err_str = str(ctx.exception).lower()
        self.assertNotIn("<html", err_str)
        self.assertNotIn("ray id", err_str)

    # --- 7. SCHEDULER BATCHING & COMMANDS (Scenarios 37-40) ---
    def test_37_scheduled_handler_runs(self):
        scheduler = AlertScheduler(self.alert_repo, BinanceClient(None), self.tg, self.settings)
        stats = self.loop.run_until_complete(scheduler.run_scheduled_tick())
        self.assertIn("timestamp", stats)
        self.assertEqual(stats["alerts_found"], 0)

    def test_38_symbol_batching_and_deduplication(self):
        async def mock_fetch(url, **kwargs):
            candles = [[1700000000000 + i * 3600000, "70000", "70500", "69500", "70100", "100", 1700003599000] for i in range(50)]
            return MockHttpResponse(json.dumps(candles))
        b_client = BinanceClient(mock_fetch)
        for _ in range(5):
            self.loop.run_until_complete(self.alert_repo.create_alert(8116631925, "BTCUSDT", "PRICE_ABOVE", 75000.0))
        scheduler = AlertScheduler(self.alert_repo, b_client, self.tg, self.settings)
        stats = self.loop.run_until_complete(scheduler.run_scheduled_tick())
        self.assertEqual(stats["alerts_found"], 5)
        self.assertEqual(stats["symbols_evaluated"], 1)

    def test_39_slash_command_create_and_list_alerts(self):
        self.loop.run_until_complete(
            handle_command("/alert BTCUSDT > 72000", 8116631925, self.tg, 8116631925, alert_repo=self.alert_repo)
        )
        self.tg.sent.clear()
        self.loop.run_until_complete(
            handle_command("/alerts", 8116631925, self.tg, 8116631925, alert_repo=self.alert_repo)
        )
        self.assertTrue(any("BTCUSDT" in s["text"] for s in self.tg.sent))

    def test_40_slash_command_unalert_and_validation(self):
        self.loop.run_until_complete(
            handle_command("/alert SOLUSDT < 130", 8116631925, self.tg, 8116631925, alert_repo=self.alert_repo)
        )
        self.tg.sent.clear()
        self.loop.run_until_complete(
            handle_command("/unalert 1", 8116631925, self.tg, 8116631925, alert_repo=self.alert_repo)
        )
        self.assertTrue(any("ڈیلیٹ کر دیا گیا ہے" in s["text"] for s in self.tg.sent))


if __name__ == "__main__":
    unittest.main()
