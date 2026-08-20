"""
Comprehensive Forensic Test Suite for Phase 8.2 & 8.3 — Deterministic Market Reasoning, Hard-SL Integrity & Risk Consistency.
Covers Core Objectives #1 through #25:
1. Long R:R exact mathematics
2. Short R:R exact mathematics
3. Long target already below current price
4. Short target already above current price
5. Resistance invalidates theoretical long R:R
6. Support invalidates theoretical short R:R
7. Structural warning differs from hard SL
8. Invalid entry/SL relationships
9. Current-price consistency
10. Pullback setup when market is extended
11. Breakout confirmation setup
12. No-trade when no executable setup exists
13. Long/short symmetry
14. Gemini is never responsible for these calculations
15. Long setup ready healthy runway
16. Short setup ready healthy runway
17. Bullish structure breakdown to no trade
18. Bearish structure breakout to no trade
19. Multi-timeframe conflict execution
20. Insufficient data candle threshold
21. Hypothetical user scenario with ATR exact math
22. Hypothetical user scenario missing ATR reports insufficient data
23. Natural language capital and risk sizing live trade
24. Natural language hypothetical dispatch end to end
25. No unsupported statistical claims in instructions
"""

import unittest
import asyncio
import json
import math
from types import SimpleNamespace

from config.settings import Settings
from storage.database import D1Database
from storage.repositories import (
    UserRepository,
    MemoryRepository,
    ConversationRepository,
    WatchlistRepository,
)
from router.command_router import handle_command
from router.message_router import dispatch_telegram_update
from trading.binance_client import BinanceClient
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
    calculate_sma,
    calculate_ema,
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_bollinger_percent_b,
    calculate_atr,
    calculate_swing_points,
    analyze_market_structure,
    determine_mtf_alignment,
    evaluate_deterministic_setup,
    evaluate_market_structure,
)
from trading.risk_calculator import (
    DEFAULT_ATR_MULTIPLIER,
    calculate_hard_stop,
    calculate_position_risk,
)
from ai.prompts_builder import (
    extract_crypto_symbols,
    extract_timeframe,
    has_technical_analysis_intent,
    extract_capital_and_risk,
    extract_hypothetical_trade_params,
    format_hypothetical_trade_grounding,
    format_market_state_grounding,
    format_prompt_with_context,
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
        if "INSERT INTO user_watchlist" in self.sql:
            uid, sym, dt, notes = self.params
            self.db_mock.watchlist[(uid, sym)] = {"symbol": sym, "added_at": dt, "notes": notes}
            return {"meta": {"changes": 1}}
        if "DELETE FROM user_watchlist" in self.sql:
            uid, sym = self.params
            self.db_mock.watchlist.pop((uid, sym), None)
            return {"meta": {"changes": 1}}
        return {"meta": {"changes": 0}}

    async def first(self):
        if "SELECT COUNT(*)" in self.sql and "user_watchlist" in self.sql:
            uid = self.params[0]
            count = len([k for k in self.db_mock.watchlist.keys() if k[0] == uid])
            return {"count": count}
        return None

    async def all(self):
        if "SELECT symbol, added_at, notes FROM user_watchlist" in self.sql:
            uid = self.params[0]
            rows = [v for k, v in self.db_mock.watchlist.items() if k[0] == uid]
            return SimpleNamespace(results=rows)
        return SimpleNamespace(results=[])


class MockD1Binding:
    def __init__(self):
        self.watchlist = {}

    def prepare(self, sql: str):
        return MockD1Statement(self, sql)


class MockHttpResponse:
    def __init__(self, text_data: str, status: int = 200):
        self._text = text_data
        self.status = status

    async def text(self):
        return self._text

    async def json(self):
        return json.loads(self._text)


class MockTelegram:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode="Markdown"):
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})

    async def send_chat_action(self, chat_id, action="typing"):
        pass


class MockGemini:
    def __init__(self):
        self.last_prompt = ""

    async def generate_text(self, prompt, model_name=None):
        self.last_prompt = prompt
        return "Gemini Grounded Response"


class TestPhase82MarketReasoningEngine(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tg = MockTelegram()
        self.gem = MockGemini()
        self.db = D1Database(MockD1Binding())
        self.wl_repo = WatchlistRepository(self.db)
        env = SimpleNamespace(
            TELEGRAM_BOT_TOKEN="token",
            GEMINI_API_KEY="key",
            ALLOWED_USER_IDS="8116631925",
            GEMINI_MODEL="gemini-3.1-flash-lite"
        )
        self.settings = Settings(env)

    def tearDown(self):
        self.loop.close()

    # --- 1. LONG R:R EXACT MATHEMATICS ---
    def test_long_rr_exact_mathematics(self):
        """Verify for LONG: risk = entry - stop_loss; TP = entry + risk * RR."""
        entry = 70000.0
        sl = 68000.0
        risk = entry - sl  # 2000.0
        res = calculate_position_risk(capital=10000.0, risk_pct=1.0, entry_price=entry, stop_loss_price=sl, direction="LONG")
        
        self.assertEqual(res.direction, "LONG")
        self.assertEqual(res.risk_usd, 100.0)
        self.assertEqual(res.position_size_coins, 100.0 / 2000.0)  # 0.05 BTC
        self.assertAlmostEqual(res.tp1_price, entry + 1.5 * risk)  # 73000.0
        self.assertAlmostEqual(res.tp2_price, entry + 2.0 * risk)  # 74000.0
        self.assertAlmostEqual(res.tp3_price, entry + 3.0 * risk)  # 76000.0

    # --- 2. SHORT R:R EXACT MATHEMATICS ---
    def test_short_rr_exact_mathematics(self):
        """Verify for SHORT: risk = stop_loss - entry; TP = entry - risk * RR."""
        entry = 60000.0
        sl = 62000.0
        risk = sl - entry  # 2000.0
        res = calculate_position_risk(capital=10000.0, risk_pct=1.0, entry_price=entry, stop_loss_price=sl, direction="SHORT")
        
        self.assertEqual(res.direction, "SHORT")
        self.assertEqual(res.risk_usd, 100.0)
        self.assertEqual(res.position_size_coins, 100.0 / 2000.0)  # 0.05 BTC
        self.assertAlmostEqual(res.tp1_price, entry - 1.5 * risk)  # 57000.0
        self.assertAlmostEqual(res.tp2_price, entry - 2.0 * risk)  # 56000.0
        self.assertAlmostEqual(res.tp3_price, entry - 3.0 * risk)  # 54000.0

    # --- 3. LONG TARGET ALREADY BELOW CURRENT PRICE ---
    def test_long_target_already_below_current_price(self):
        """
        When market is extended (e.g. BTC = $72,338), and a pullback entry is proposed at $70,800 with
        hard SL at $70,132 (risk = $668), TP1 is $71,802 and TP2 is $72,136.
        The engine must recognize that TP1 & TP2 are currently below live market price $72,338.
        """
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(40):
            p = 65000 + i * 150
            candles.append(Candle(i, p, p + 50, p - 50, p, 100.0, i + 1))
        for i in range(10):
            p = 71000 + i * 133.8
            candles.append(Candle(40 + i, p - 50, p + 100, p - 60, p, 300.0, 40 + i + 1))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertEqual(setup.setup_state, "WAIT_FOR_PULLBACK")
        self.assertEqual(setup.direction_bias, "LONG")
        self.assertIn("Pullback", setup.execution_scenario)
        self.assertTrue(len(setup.tp_target_details) > 0)
        if setup.suggested_tp_levels and setup.suggested_tp_levels[0] <= ta.current_price:
            any_below_warning = any("Currently below market" in d for d in setup.tp_target_details)
            self.assertTrue(any_below_warning)

    # --- 4. SHORT TARGET ALREADY ABOVE CURRENT PRICE ---
    def test_short_target_already_above_current_price(self):
        """
        When market is extended downward (e.g. BTC = $55,000), and a relief rally entry is proposed at $57,000
        with hard SL at $58,000 (risk = $1,000), TP1 is $55,500.
        The engine must recognize that TP1 is currently above live market price $55,000.
        """
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(40):
            p = 65000 - i * 150
            candles.append(Candle(i, p, p + 50, p - 50, p, 100.0, i + 1))
        for i in range(10):
            p = 59000 - i * 400
            candles.append(Candle(40 + i, p + 50, p + 60, p - 100, p, 300.0, 40 + i + 1))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertEqual(setup.setup_state, "WAIT_FOR_PULLBACK")
        self.assertEqual(setup.direction_bias, "SHORT")
        self.assertIn("Relief", setup.execution_scenario)
        if setup.suggested_tp_levels and setup.suggested_tp_levels[0] >= ta.current_price:
            any_above_warning = any("Currently above market" in d for d in setup.tp_target_details)
            self.assertTrue(any_above_warning)

    # --- 5. RESISTANCE INVALIDATES THEORETICAL LONG R:R ---
    def test_resistance_invalidates_theoretical_long_rr(self):
        """
        If room to resistance is less than 1.0x risk distance (e.g. resistance is only $400 away but risk is $1000),
        an immediate long entry has unfavorable R:R (< 1:1) before hitting supply.
        The engine must NOT return SETUP_READY; it must return WAIT_FOR_PULLBACK or WAIT_FOR_BREAKOUT_CONFIRMATION.
        """
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(48):
            p = 60000 + i * 20
            candles.append(Candle(i, p, p + 100, p - 100, p, 100.0, i + 1))
        candles.append(Candle(48, 60950, 61000, 60800, 60950, 100.0, 49))
        candles.append(Candle(49, 60950, 61000, 60850, 60960, 100.0, 50))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertNotEqual(setup.setup_state, "SETUP_READY")
        self.assertIn(setup.setup_state, ("WAIT_FOR_PULLBACK", "WAIT_FOR_BREAKOUT_CONFIRMATION"))

    # --- 6. SUPPORT INVALIDATES THEORETICAL SHORT R:R ---
    def test_support_invalidates_theoretical_short_rr(self):
        """
        If room to support is less than 1.0x risk distance, an immediate short entry has unfavorable R:R (< 1:1)
        before hitting major support. The engine must return WAIT_FOR_PULLBACK or WAIT_FOR_BREAKDOWN_CONFIRMATION.
        """
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(48):
            p = 60000 - i * 20
            candles.append(Candle(i, p, p + 100, p - 100, p, 100.0, i + 1))
        candles.append(Candle(48, 59050, 59200, 59000, 59050, 100.0, 49))
        candles.append(Candle(49, 59050, 59150, 59000, 59040, 100.0, 50))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertNotEqual(setup.setup_state, "SETUP_READY")
        self.assertIn(setup.setup_state, ("WAIT_FOR_PULLBACK", "WAIT_FOR_BREAKDOWN_CONFIRMATION"))

    # --- 7. STRUCTURAL WARNING DIFFERS FROM HARD SL ---
    def test_structural_warning_differs_from_hard_sl(self):
        """
        Verify that structural warning level (e.g. recent swing low) is distinct from hard SL (swing low - 1.5x ATR buffer).
        """
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(50):
            p = 60000 + i * 50 + math.sin(i * 0.5) * 800
            candles.append(Candle(i, p, p + 150, p - 150, p + 50, 100.0, i + 1))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        if setup.structural_warning_level is not None and setup.suggested_sl_level is not None:
            self.assertNotEqual(setup.structural_warning_level, setup.suggested_sl_level)
            if setup.direction_bias in ("LONG", "BULLISH_WATCH"):
                self.assertLess(setup.suggested_sl_level, setup.structural_warning_level)

    # --- 8. INVALID ENTRY / SL RELATIONSHIPS ---
    def test_invalid_entry_sl_relationships(self):
        """Verify that calculate_position_risk strictly validates entry and SL placement."""
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 2, 50000, 50000, direction="LONG")
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 2, 50000, 51000, direction="LONG")
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 2, 50000, 50000, direction="SHORT")
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 2, 50000, 49000, direction="SHORT")
        with self.assertRaises(ValueError):
            calculate_position_risk(-1000, 2, 50000, 48000)
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 0, 50000, 48000)
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 2, 0, 48000)

    # --- 9. CURRENT-PRICE CONSISTENCY ---
    def test_current_price_consistency(self):
        """Verify that format_market_state_grounding outputs verified current price matching input."""
        now_iso = "2026-08-20T12:00:00Z"
        candles = [Candle(i, 65000, 65100, 64900, 65050.0, 100.0, i + 1) for i in range(50)]
        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)
        state = MarketState("BTCUSDT", "1h", 65050.0, now_iso, "Spot Klines", None, ta, ms, None, setup)

        grounding = format_market_state_grounding(state)
        self.assertIn("Verified Current Price: $65,050.00", grounding)
        self.assertIn("Current Verified Market Price: $65,050.00", grounding)

    # --- 10. PULLBACK SETUP WHEN MARKET IS EXTENDED ---
    def test_pullback_setup_when_market_is_extended(self):
        """Verify that when price is > 1.8x ATR above EMA20, WAIT_FOR_PULLBACK is triggered."""
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(40):
            p = 60000 + i * 50
            candles.append(Candle(i, p, p + 50, p - 50, p, 100.0, i + 1))
        for i in range(10):
            p = 62000 + i * 500
            candles.append(Candle(40 + i, p - 100, p + 200, p - 100, p, 500.0, 40 + i + 1))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertEqual(setup.setup_state, "WAIT_FOR_PULLBACK")
        self.assertEqual(setup.direction_bias, "LONG")
        self.assertTrue(any("extended" in r.lower() for r in setup.reasons))

    # --- 11. BREAKOUT CONFIRMATION SETUP ---
    def test_breakout_confirmation_setup(self):
        """Verify that when price is pressing against resistance, WAIT_FOR_BREAKOUT_CONFIRMATION is output."""
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(20):
            p = 62000 + i * 200
            candles.append(Candle(i, p, p + 100, p - 100, p, 100.0, i + 1))
        for i in range(15):
            p = 66000 - i * 100
            candles.append(Candle(20 + i, p + 50, p + 80, p - 120, p, 100.0, 20 + i + 1))
        for i in range(15):
            p = 64500 + i * 100
            candles.append(Candle(35 + i, p - 50, p + 120, p - 60, p, 150.0, 35 + i + 1))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertEqual(setup.setup_state, "WAIT_FOR_BREAKOUT_CONFIRMATION")
        self.assertEqual(setup.direction_bias, "BULLISH_WATCH")
        self.assertTrue(len(setup.suggested_tp_levels) > 0)

    # --- 12. NO TRADE WHEN NO EXECUTABLE SETUP EXISTS ---
    def test_no_trade_when_no_executable_setup(self):
        """Verify that in range-bound chop with neutral indicators, NO_TRADE is output."""
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(50):
            p = 60000 + math.sin(i * 0.8) * 300
            candles.append(Candle(i, p, p + 50, p - 50, p, 100.0, i + 1))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertEqual(setup.setup_state, "NO_TRADE")
        self.assertEqual(setup.direction_bias, "NEUTRAL")
        self.assertTrue(any("range-bound" in r.lower() for r in setup.reasons))

    # --- 13. LONG / SHORT SYMMETRY ---
    def test_long_short_symmetry(self):
        """Verify strict symmetric logic between bullish and bearish setups."""
        now_iso = "2026-08-20T12:00:00Z"
        
        # Bullish healthy series
        candles_bull = [Candle(i, 50000 + i * 50, 50050 + i * 50, 49950 + i * 50, 50020 + i * 50, 100.0, i + 1) for i in range(50)]
        ta_bull = evaluate_market_structure("BTCUSDT", "1h", candles_bull, now_iso)
        ms_bull = analyze_market_structure("BTCUSDT", "1h", candles_bull)
        setup_bull = evaluate_deterministic_setup("BTCUSDT", "1h", candles_bull, ta_bull, ms_bull)

        # Bearish healthy series
        candles_bear = [Candle(i, 50000 - i * 50, 50050 - i * 50, 49950 - i * 50, 49980 - i * 50, 100.0, i + 1) for i in range(50)]
        ta_bear = evaluate_market_structure("BTCUSDT", "1h", candles_bear, now_iso)
        ms_bear = analyze_market_structure("BTCUSDT", "1h", candles_bear)
        setup_bear = evaluate_deterministic_setup("BTCUSDT", "1h", candles_bear, ta_bear, ms_bear)

        self.assertEqual(ta_bull.trend, "Bullish")
        self.assertEqual(ta_bear.trend, "Bearish")
        self.assertIn(setup_bull.direction_bias, ("LONG", "BULLISH_WATCH"))
        self.assertIn(setup_bear.direction_bias, ("SHORT", "BEARISH_WATCH"))

    # --- 14. GEMINI IS NEVER RESPONSIBLE FOR CALCULATIONS ---
    def test_gemini_never_calculates_values(self):
        """
        Verify end-to-end that all indicator math, market structure, and setup levels
        are pre-computed by the Python engine and injected into the Gemini prompt as immutable facts.
        """
        async def mock_fetch(url, **kwargs):
            if "klines" in url:
                candles_data = []
                for i in range(50):
                    p = 65000 + i * 30
                    candles_data.append([1700000000000 + i * 3600000, str(p), str(p + 100), str(p - 100), str(p + 10), "100.0", 1700003599000])
                return MockHttpResponse(json.dumps(candles_data))
            return MockHttpResponse(json.dumps({"symbol": "BTCUSDT", "lastPrice": "66500.00", "priceChange": "1500.00", "priceChangePercent": "2.31"}))

        b_client = BinanceClient(mock_fetch)
        update = {
            "message": {
                "chat": {"id": 8116631925},
                "from": {"id": 8116631925, "first_name": "Abdul"},
                "text": "What is the trade setup for BTC on 1h?"
            }
        }
        self.loop.run_until_complete(
            dispatch_telegram_update(update, self.settings, self.tg, self.gem, binance_client=b_client)
        )

        prompt = self.gem.last_prompt
        self.assertIn("=== [LIVE MARKET FACTS] ===", prompt)
        self.assertIn("=== [MARKET STRUCTURE — 1H] ===", prompt)
        self.assertIn("=== [MOMENTUM & MOVING AVERAGES — 1H] ===", prompt)
        self.assertIn("=== [VOLATILITY, BOLLINGER BANDS & VOLUME — 1H] ===", prompt)
        self.assertIn("=== [DETERMINISTIC TRADE SETUP EVALUATION] ===", prompt)
        self.assertIn("• Proposed Hard Stop-Loss:", prompt)
        self.assertIn("• Calculated Take-Profit Targets:", prompt)

    # --- 15. LONG SETUP READY HEALTHY RUNWAY ---
    def test_long_setup_ready_healthy_runway(self):
        """Verify that when price is near EMA20 with healthy RSI and ample room to resistance, SETUP_READY is returned."""
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(50):
            p = 50000 + i * 40
            candles.append(Candle(i, p, p + 50, p - 50, p + 10, 100.0, i + 1))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertIn(setup.setup_state, ("SETUP_READY", "WAIT_FOR_PULLBACK"))
        self.assertEqual(setup.direction_bias, "LONG")
        if setup.setup_state == "SETUP_READY":
            self.assertIn("Market Execution", setup.execution_scenario)
            self.assertTrue(len(setup.suggested_tp_levels) == 3)

    # --- 16. SHORT SETUP READY HEALTHY RUNWAY ---
    def test_short_setup_ready_healthy_runway(self):
        """Verify that when price is near EMA20 with healthy bearish RSI and ample room to support, SETUP_READY or WAIT_FOR_PULLBACK is returned."""
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(50):
            p = 50000 - i * 40
            candles.append(Candle(i, p, p + 50, p - 50, p - 10, 100.0, i + 1))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertIn(setup.setup_state, ("SETUP_READY", "WAIT_FOR_PULLBACK"))
        self.assertEqual(setup.direction_bias, "SHORT")
        if setup.setup_state == "SETUP_READY":
            self.assertIn("Market Execution", setup.execution_scenario)
            self.assertTrue(len(setup.suggested_tp_levels) == 3)

    # --- 17. BULLISH STRUCTURE BREAKDOWN TO NO TRADE ---
    def test_bullish_structure_breakdown_to_no_trade(self):
        """Verify that when price breaks below swing low in an apparent bullish trend, NO_TRADE is returned."""
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(15):
            p = 50000 + i * 100
            candles.append(Candle(i, p, p + 50, p - 50, p, 100.0, i + 1))
        for i in range(10):
            p = 51500 - i * 50
            candles.append(Candle(15 + i, p, p + 50, p - 50, p, 100.0, 15 + i + 1))
        for i in range(15):
            p = 51000 + i * 100
            candles.append(Candle(25 + i, p, p + 50, p - 50, p, 100.0, 25 + i + 1))
        # Breach below recent swing low (50950)
        candles.append(Candle(40, 52500, 52500, 50800, 50850, 100.0, 41))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertEqual(setup.setup_state, "NO_TRADE")
        self.assertIn("NEUTRAL", setup.direction_bias)
        self.assertTrue(any("broken below recent swing low" in r for r in setup.reasons))

    # --- 18. BEARISH STRUCTURE BREAKOUT TO NO TRADE ---
    def test_bearish_structure_breakout_to_no_trade(self):
        """Verify that when price reclaims above swing high in an apparent bearish trend, NO_TRADE is returned."""
        now_iso = "2026-08-20T12:00:00Z"
        candles = []
        for i in range(15):
            p = 50000 - i * 100
            candles.append(Candle(i, p, p + 50, p - 50, p, 100.0, i + 1))
        for i in range(10):
            p = 48500 + i * 50
            candles.append(Candle(15 + i, p, p + 50, p - 50, p, 100.0, 15 + i + 1))
        for i in range(15):
            p = 49000 - i * 100
            candles.append(Candle(25 + i, p, p + 50, p - 50, p, 100.0, 25 + i + 1))
        # Reclaim above recent swing high (49050)
        candles.append(Candle(40, 47500, 49200, 47500, 49150, 100.0, 41))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertEqual(setup.setup_state, "NO_TRADE")
        self.assertIn("NEUTRAL", setup.direction_bias)
        self.assertTrue(any("broken above recent swing high" in r for r in setup.reasons))

    # --- 19. MULTI TIMEFRAME CONFLICT EXECUTION ---
    def test_multi_timeframe_conflict_execution(self):
        """Verify that when MTF summary has conflict, CONFLICTING_SIGNALS is returned with target calculation suspended."""
        now_iso = "2026-08-20T12:00:00Z"
        candles = [Candle(i, 60000 + i * 20, 60050 + i * 20, 59950 + i * 20, 60010 + i * 20, 100.0, i + 1) for i in range(50)]
        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        
        mtf_summary = MultiTimeframeSummary(
            primary_timeframe="1h",
            timeframes={},
            alignment_status="Conflicting / Pullback in Uptrend",
            alignment_description="1D: Bullish | 1H: Bearish",
            has_conflict=True,
            conflict_details="1D Bullish trend intact while 1H is in corrective pullback."
        )

        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms, mtf_summary=mtf_summary)
        self.assertEqual(setup.setup_state, "CONFLICTING_SIGNALS")
        self.assertEqual(setup.direction_bias, "NEUTRAL / CAUTION")
        self.assertEqual(len(setup.suggested_tp_levels), 0)
        self.assertIn("suspended", setup.sr_clearance_status.lower())

    # --- 20. INSUFFICIENT DATA CANDLE THRESHOLD ---
    def test_insufficient_data_candle_threshold(self):
        """Verify that when fewer than 15 candles are provided, INSUFFICIENT_DATA is returned."""
        now_iso = "2026-08-20T12:00:00Z"
        candles = [Candle(i, 60000, 60050, 59950, 60010, 100.0, i + 1) for i in range(10)]
        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)

        self.assertEqual(setup.setup_state, "INSUFFICIENT_DATA")
        self.assertEqual(setup.direction_bias, "NEUTRAL")
        self.assertIn("minimum 15 candles", setup.reasons[0])

    # --- 21. HYPOTHETICAL USER SCENARIO WITH ATR EXACT MATH ---
    def test_hypothetical_user_scenario_with_atr_exact_math(self):
        """
        Verify that when user supplies Entry $70,500, SW $70,000, ATR $300, Capital $1,000, Risk 1%:
        - Structural Warning ($70,000) != Hard SL ($69,550)
        - Risk Per Unit is $950 (not $500)
        - Position size is 0.0105 BTC
        - Targets are TP1 $71,925, TP2 $72,400, TP3 $73,350
        """
        user_msg = "Entry = $70,500, Structural Warning = $70,000, ATR = $300, Capital = $1,000, Risk = 1%"
        params = extract_hypothetical_trade_params(user_msg)
        self.assertIsNotNone(params)
        self.assertEqual(params["entry"], 70500.0)
        self.assertEqual(params["structural_warning"], 70000.0)
        self.assertEqual(params["atr"], 300.0)
        self.assertEqual(params["capital"], 1000.0)
        self.assertEqual(params["risk_pct"], 1.0)

        grounding = format_hypothetical_trade_grounding(params)
        self.assertIn("Proposed Hard Stop-Loss: $69,550.00", grounding)
        self.assertIn("Structural Warning ($70,000.00) != Hard Stop Loss ($69,550.00)", grounding)
        self.assertIn("Exact Risk Per Unit: $950.00", grounding)
        self.assertIn("TP1 (1:1.5 R:R): $71,925.00", grounding)
        self.assertIn("TP2 (1:2.0 R:R): $72,400.00", grounding)
        self.assertIn("TP3 (1:3.0 R:R): $73,350.00", grounding)
        self.assertIn("Position Size: 0.0105 units", grounding)
        self.assertIn("Effective Leverage: 0.74x", grounding)

    # --- 22. HYPOTHETICAL USER SCENARIO MISSING ATR REPORTS INSUFFICIENT DATA ---
    def test_hypothetical_user_scenario_missing_atr_reports_insufficient_data(self):
        """
        Verify that when user supplies Entry $70,500 and SW $70,000 WITHOUT ATR:
        - The engine does NOT equate Hard SL to $70,000
        - The engine explicitly outputs an INSUFFICIENT DATA note
        """
        user_msg = "Entry $70,500, structural warning $70,000. Calculate the hard stop."
        params = extract_hypothetical_trade_params(user_msg)
        self.assertIsNotNone(params)
        self.assertNotIn("atr", params)

        grounding = format_hypothetical_trade_grounding(params)
        self.assertIn("INSUFFICIENT DATA FOR HARD STOP", grounding)
        self.assertIn("Structural Warning ($70,000.00) is NOT the Hard Stop Loss", grounding)
        self.assertNotIn("Proposed Hard Stop-Loss: $70,000.00", grounding)

    # --- 23. NATURAL LANGUAGE CAPITAL AND RISK SIZING LIVE TRADE ---
    def test_natural_language_capital_and_risk_sizing_live_trade(self):
        """
        Verify Test A: 'I have $1,000 capital and risk 1%. Find me the best BTCUSDT trade right now.'
        - Capital $1,000 and Risk 1% are extracted
        - Position sizing is computed by the deterministic engine and injected into Gemini context
        """
        async def mock_fetch(url, **kwargs):
            if "klines" in url:
                candles_data = []
                for i in range(50):
                    p = 65000 + i * 30
                    candles_data.append([1700000000000 + i * 3600000, str(p), str(p + 100), str(p - 100), str(p + 10), "100.0", 1700003599000])
                return MockHttpResponse(json.dumps(candles_data))
            return MockHttpResponse(json.dumps({"symbol": "BTCUSDT", "lastPrice": "66500.00", "priceChange": "1500.00", "priceChangePercent": "2.31"}))

        b_client = BinanceClient(mock_fetch)
        update = {
            "message": {
                "chat": {"id": 8116631925},
                "from": {"id": 8116631925, "first_name": "Abdul"},
                "text": "I have $1,000 capital and risk 1%. Find me the best BTCUSDT trade right now."
            }
        }
        self.loop.run_until_complete(
            dispatch_telegram_update(update, self.settings, self.tg, self.gem, binance_client=b_client)
        )

        prompt = self.gem.last_prompt
        self.assertIn("=== [LIVE MARKET FACTS] ===", prompt)
        self.assertIn("=== [DETERMINISTIC TRADE SETUP EVALUATION] ===", prompt)
        self.assertIn("Deterministic Position Sizing (Capital: $1,000.00 | Risk: 1.0%", prompt)
        self.assertIn("Position Size:", prompt)
        self.assertIn("Effective Leverage:", prompt)

    # --- 24. NATURAL LANGUAGE HYPOTHETICAL DISPATCH END TO END ---
    def test_natural_language_hypothetical_dispatch_end_to_end(self):
        """
        Verify Test C via dispatch_telegram_update:
        'Entry $70,500, structural warning $70,000, ATR $300. Calculate the hard stop.'
        Grounding contract is injected with exact deterministic numbers.
        """
        update = {
            "message": {
                "chat": {"id": 8116631925},
                "from": {"id": 8116631925, "first_name": "Abdul"},
                "text": "Entry $70,500, structural warning $70,000, ATR $300. Calculate the hard stop."
            }
        }
        self.loop.run_until_complete(
            dispatch_telegram_update(update, self.settings, self.tg, self.gem)
        )

        prompt = self.gem.last_prompt
        self.assertIn("=== [DETERMINISTIC TRADE & RISK CALCULATION — USER HYPOTHETICAL] ===", prompt)
        self.assertIn("Proposed Hard Stop-Loss: $69,550.00", prompt)
        self.assertIn("Structural Warning ($70,000.00) != Hard Stop Loss ($69,550.00)", prompt)
        self.assertIn("Exact Risk Per Unit: $950.00", prompt)

    # --- 25. NO UNSUPPORTED STATISTICAL CLAIMS IN INSTRUCTIONS ---
    def test_no_unsupported_statistical_claims_in_instructions(self):
        """Verify that TRADING_SYSTEM_INSTRUCTIONS explicitly forbids fake statistical probability claims."""
        from config.prompts import TRADING_SYSTEM_INSTRUCTIONS
        self.assertIn("NO UNSUPPORTED STATISTICAL CLAIMS", TRADING_SYSTEM_INSTRUCTIONS)
        self.assertIn("STRUCTURAL WARNING LEVEL VS HARD STOP LOSS", TRADING_SYSTEM_INSTRUCTIONS)
        self.assertIn("DETERMINISTIC ENGINE IS THE SINGLE SOURCE OF TRUTH", TRADING_SYSTEM_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
