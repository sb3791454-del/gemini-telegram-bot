"""
Production Forensic Verification Test Suite for Phase 8.3.
Verifies all 17 Required Invariants and Tests A through E.
"""

import unittest
import asyncio
import json
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
    evaluate_market_structure,
    analyze_market_structure,
    evaluate_deterministic_setup,
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
)
from config.prompts import TRADING_SYSTEM_INSTRUCTIONS


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
        return "Gemini Deterministic Verification Response"


class TestPhase83ProductionForensic(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tg = MockTelegram()
        self.gem = MockGemini()
        env = SimpleNamespace(
            TELEGRAM_BOT_TOKEN="mock_token",
            GEMINI_API_KEY="mock_key",
            ALLOWED_USER_IDS="8116631925",
            GEMINI_MODEL="gemini-3.1-flash-lite"
        )
        self.settings = Settings(env)

    def tearDown(self):
        self.loop.close()

    # INVARIANT 1: Structural Warning != Hard SL
    def test_invariant_1_structural_warning_not_equal_hard_sl(self):
        sw = 70000.0
        atr = 300.0
        hard_sl_long = calculate_hard_stop(sw, atr, "LONG")
        hard_sl_short = calculate_hard_stop(sw, atr, "SHORT")
        self.assertNotEqual(sw, hard_sl_long)
        self.assertNotEqual(sw, hard_sl_short)
        self.assertEqual(hard_sl_long, 69550.0)
        self.assertEqual(hard_sl_short, 70450.0)

    # INVARIANT 2: LONG hard SL is below Structural Warning
    def test_invariant_2_long_hard_sl_is_below_structural_warning(self):
        sw = 65000.0
        atr = 400.0
        hard_sl = calculate_hard_stop(sw, atr, "LONG")
        self.assertLess(hard_sl, sw)
        self.assertEqual(hard_sl, 65000.0 - (1.5 * 400.0))

    # INVARIANT 3: SHORT hard SL is above Structural Warning
    def test_invariant_3_short_hard_sl_is_above_structural_warning(self):
        sw = 65000.0
        atr = 400.0
        hard_sl = calculate_hard_stop(sw, atr, "SHORT")
        self.assertGreater(hard_sl, sw)
        self.assertEqual(hard_sl, 65000.0 + (1.5 * 400.0))

    # INVARIANT 4 & 5: Deterministic source of k = 1.5, missing k cannot produce fabricated SL
    def test_invariant_4_and_5_k_multiplier_and_missing_atr(self):
        self.assertEqual(DEFAULT_ATR_MULTIPLIER, 1.5)
        # When ATR is missing for hypothetical setup, engine reports insufficient data
        params = {"entry": 70500.0, "structural_warning": 70000.0, "direction": "LONG"}
        grounding = format_hypothetical_trade_grounding(params)
        self.assertIn("INSUFFICIENT DATA FOR HARD STOP", grounding)
        self.assertIn("Structural Warning ($70,000.00) is NOT the Hard Stop Loss", grounding)
        self.assertNotIn("Proposed Hard Stop-Loss: $70,000.00", grounding)

    # INVARIANT 6: Position size uses hard SL, never structural warning
    def test_invariant_6_position_size_uses_hard_sl(self):
        entry = 70500.0
        sw = 70000.0
        atr = 300.0
        cap = 1000.0
        risk_pct = 1.0
        hard_sl = calculate_hard_stop(sw, atr, "LONG") # 69550.0 (risk distance $950)
        res = calculate_position_risk(cap, risk_pct, entry, hard_sl, "LONG")
        self.assertEqual(res.risk_usd, 10.0)
        expected_size = 10.0 / 950.0
        self.assertAlmostEqual(res.position_size_coins, expected_size, places=6)
        wrong_size = 10.0 / 500.0 # using SW
        self.assertNotAlmostEqual(res.position_size_coins, wrong_size, places=3)

    # INVARIANT 7: TP1/TP2/TP3 use hard-stop risk
    def test_invariant_7_tp_targets_use_hard_stop_risk(self):
        entry = 70500.0
        hard_sl = 69550.0
        risk = entry - hard_sl # 950
        res = calculate_position_risk(1000.0, 1.0, entry, hard_sl, "LONG")
        self.assertEqual(res.tp1_price, 70500.0 + 1.5 * 950.0) # 71925.0
        self.assertEqual(res.tp2_price, 70500.0 + 2.0 * 950.0) # 72400.0
        self.assertEqual(res.tp3_price, 70500.0 + 3.0 * 950.0) # 73350.0

    # INVARIANT 8: Target-behind-current-price annotation
    def test_invariant_8_target_behind_current_price(self):
        now_iso = "2026-08-20T12:00:00Z"
        candles = [Candle(i, 65000 + i * 150, 65050 + i * 150, 64950 + i * 150, 65000 + i * 150, 100.0, i + 1) for i in range(40)]
        for i in range(10):
            p = 71000 + i * 150
            candles.append(Candle(40 + i, p - 50, p + 100, p - 60, p, 300.0, 40 + i + 1))
        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)
        self.assertEqual(setup.setup_state, "WAIT_FOR_PULLBACK")
        if setup.suggested_tp_levels and setup.suggested_tp_levels[0] <= ta.current_price:
            self.assertTrue(any("Currently below market" in d for d in setup.tp_target_details))

    # INVARIANT 9 & 10: Resistance / Support clearance rejection
    def test_invariant_9_and_10_sr_clearance(self):
        now_iso = "2026-08-20T12:00:00Z"
        candles = [Candle(i, 60000 + i * 20, 60100 + i * 20, 59900 + i * 20, 60000 + i * 20, 100.0, i + 1) for i in range(48)]
        candles.append(Candle(48, 60950, 61000, 60800, 60950, 100.0, 49))
        candles.append(Candle(49, 60950, 61000, 60850, 60960, 100.0, 50))
        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)
        self.assertNotEqual(setup.setup_state, "SETUP_READY")
        self.assertIn(setup.setup_state, ("WAIT_FOR_PULLBACK", "WAIT_FOR_BREAKOUT_CONFIRMATION"))

    # INVARIANT 11: NO_TRADE cannot become an executable trade
    def test_invariant_11_no_trade_structure_breakdown(self):
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
        # Price breaches below recent swing low (50950)
        candles.append(Candle(40, 52500, 52500, 50800, 50850, 100.0, 41))

        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms)
        self.assertEqual(setup.setup_state, "NO_TRADE")
        self.assertIn("NEUTRAL", setup.direction_bias)
        self.assertIsNone(setup.suggested_sl_level)
        self.assertEqual(len(setup.suggested_tp_levels), 0)

    # INVARIANT 12 & 13: Natural-language trade request uses deterministic engine
    def test_invariant_12_and_13_nl_trade_request_grounding(self):
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

    # INVARIANT 14: No unsupported statistical claims in instructions
    def test_invariant_14_no_unsupported_statistical_claims(self):
        self.assertIn("NO UNSUPPORTED STATISTICAL CLAIMS", TRADING_SYSTEM_INSTRUCTIONS)
        self.assertIn("THREE-TIER EPISTEMIC SEPARATION", TRADING_SYSTEM_INSTRUCTIONS)

    # INVARIANT 15: Long and short geometry valid
    def test_invariant_15_long_short_geometry(self):
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 1, 70000, 71000, "LONG")
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 1, 70000, 69000, "SHORT")

    # INVARIANT 16 & 17: Risk percentage and maximum risk budget enforced
    def test_invariant_16_and_17_risk_budget_enforced(self):
        res = calculate_position_risk(capital=5000.0, risk_pct=2.0, entry_price=100.0, stop_loss_price=95.0, direction="LONG")
        self.assertEqual(res.risk_usd, 100.0)
        self.assertEqual(res.position_size_coins, 100.0 / 5.0) # 20 coins
        # Dollar risk cannot exceed $100
        dollar_loss_at_sl = res.position_size_coins * (res.entry_price - res.stop_loss_price)
        self.assertEqual(dollar_loss_at_sl, res.risk_usd)
        self.assertLessEqual(dollar_loss_at_sl, 5000.0 * 0.02)

    # REGRESSION TEST A
    def test_regression_test_a(self):
        text = "I have $1,000 capital and risk 1%. Find me the best BTCUSDT trade right now."
        syms = extract_crypto_symbols(text)
        cap, risk = extract_capital_and_risk(text)
        self.assertEqual(syms, ["BTCUSDT"])
        self.assertEqual(cap, 1000.0)
        self.assertEqual(risk, 1.0)

    # REGRESSION TEST B
    def test_regression_test_b(self):
        text = "Give me the complete BTCUSDT long setup."
        syms = extract_crypto_symbols(text)
        self.assertEqual(syms, ["BTCUSDT"])
        self.assertTrue(has_technical_analysis_intent(text))

    # REGRESSION TEST C
    def test_regression_test_c(self):
        text = "Entry $70,500, structural warning $70,000, ATR $300. Calculate the hard stop."
        params = extract_hypothetical_trade_params(text)
        self.assertIsNotNone(params)
        self.assertEqual(params["entry"], 70500.0)
        self.assertEqual(params["structural_warning"], 70000.0)
        self.assertEqual(params["atr"], 300.0)
        grounding = format_hypothetical_trade_grounding(params)
        self.assertIn("Proposed Hard Stop-Loss: $69,550.00", grounding)
        self.assertIn("Structural Warning ($70,000.00) != Hard Stop Loss ($69,550.00)", grounding)
        self.assertIn("Exact Risk Per Unit: $950.00", grounding)
        self.assertIn("TP1 (1:1.5 R:R): $71,925.00", grounding)
        self.assertIn("TP2 (1:2.0 R:R): $72,400.00", grounding)
        self.assertIn("TP3 (1:3.0 R:R): $73,350.00", grounding)

    # REGRESSION TEST D
    def test_regression_test_d(self):
        text = "Calculate a BTCUSDT position using 1% risk."
        syms = extract_crypto_symbols(text)
        cap, risk = extract_capital_and_risk(text)
        self.assertEqual(syms, ["BTCUSDT"])
        self.assertIsNone(cap)
        self.assertEqual(risk, 1.0)
        self.assertTrue(has_technical_analysis_intent(text))

    # REGRESSION TEST E
    def test_regression_test_e(self):
        text = "Give me TP1, TP2 and TP3."
        syms = extract_crypto_symbols(text)
        params = extract_hypothetical_trade_params(text)
        self.assertEqual(syms, [])
        self.assertIsNone(params)


if __name__ == "__main__":
    unittest.main()
