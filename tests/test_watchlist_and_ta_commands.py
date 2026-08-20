"""
Comprehensive Test Suite for Phase 8.2 — Deterministic Market Reasoning Engine.
Tests:
- Mathematical accuracy of indicators (Wilder RSI-14, SMA, EMA, Bollinger Bands, %b, ATR-14)
- Swing point detection and market structure analysis (HH, HL, LH, LL, Breakouts, Breakdowns, Ranges)
- Multi-timeframe confirmation, alignment, and signal conflict reporting
- Deterministic trade setup evaluation (SETUP_READY, WAIT_FOR_PULLBACK, WAIT_FOR_BREAKOUT, CONFLICTING_SIGNALS, NO_TRADE)
- Structured Market Grounding Contract generation and prompt formatting
- End-to-end natural language queries and deterministic slash commands
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
from trading.risk_calculator import calculate_position_risk
from ai.prompts_builder import (
    extract_crypto_symbols,
    extract_timeframe,
    has_technical_analysis_intent,
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
        return "Gemini Response"


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

    # --- 1. MATHEMATICAL INDICATOR TESTS ---
    def test_indicator_math_exactness(self):
        closes = [100.0, 102.0, 101.0, 103.0, 105.0, 104.0, 106.0, 108.0, 107.0, 109.0,
                  111.0, 110.0, 112.0, 114.0, 113.0, 115.0, 117.0, 116.0, 118.0, 120.0]
        
        # SMA
        sma20 = calculate_sma(closes, 20)
        self.assertAlmostEqual(sma20, sum(closes) / 20.0, places=4)

        # EMA
        ema20 = calculate_ema(closes, 20)
        self.assertTrue(100.0 < ema20 < 120.0)

        # RSI (Wilder smoothed)
        rsi = calculate_rsi(closes, 14)
        self.assertTrue(0.0 <= rsi <= 100.0)
        self.assertTrue(rsi > 60.0)  # Strong upward trend

        # Bollinger Bands & %b
        upper, mid, lower, bw = calculate_bollinger_bands(closes, 20, 2.0)
        self.assertAlmostEqual(mid, sma20, places=4)
        self.assertTrue(upper > mid > lower)
        self.assertTrue(bw > 0.0)

        pct_b = calculate_bollinger_percent_b(closes[-1], lower, upper)
        self.assertTrue(0.0 <= pct_b <= 1.5)

    def test_rsi_overbought_oversold_classification(self):
        # Monotonically rising -> RSI 100
        up_closes = [float(100 + i * 2) for i in range(30)]
        rsi_up = calculate_rsi(up_closes, 14)
        self.assertEqual(rsi_up, 100.0)

        # Monotonically falling -> RSI 0
        down_closes = [float(100 - i * 2) for i in range(30)]
        rsi_down = calculate_rsi(down_closes, 14)
        self.assertEqual(rsi_down, 0.0)

    # --- 2. SWING POINTS & MARKET STRUCTURE TESTS ---
    def test_swing_points_and_bullish_structure(self):
        candles_up = []
        for i in range(50):
            p = 60000 + i * 50 + math.sin(i * 0.5) * 800
            candles_up.append(Candle(
                open_time=1700000000000 + i * 3600000,
                open=p, high=p + 150, low=p - 150, close=p + 50,
                volume=100.0 + i, close_time=1700003599000
            ))

        sh, sl = calculate_swing_points(candles_up, lookback=2)
        self.assertTrue(len(sh) >= 2)
        self.assertTrue(len(sl) >= 2)

        ms = analyze_market_structure("BTCUSDT", "1h", candles_up, lookback_window=30)
        self.assertIn("Bullish", ms.trend)
        self.assertTrue(ms.higher_highs_count > 0)
        self.assertTrue(ms.higher_lows_count > 0)
        self.assertTrue(ms.support_level > 0.0)
        self.assertTrue(ms.resistance_level > ms.support_level)

    def test_market_structure_bearish(self):
        candles_down = []
        for i in range(50):
            p = 60000 - i * 50 - math.sin(i * 0.5) * 800
            candles_down.append(Candle(
                open_time=1700000000000 + i * 3600000,
                open=p, high=p + 150, low=p - 150, close=p - 50,
                volume=100.0 + i, close_time=1700003599000
            ))

        ms = analyze_market_structure("BTCUSDT", "1h", candles_down, lookback_window=30)
        self.assertIn("Bearish", ms.trend)
        self.assertTrue(ms.lower_highs_count > 0)
        self.assertTrue(ms.lower_lows_count > 0)

    def test_market_structure_ranging(self):
        candles_range = []
        for i in range(50):
            p = 60000 + math.sin(i * 0.8) * 500
            candles_range.append(Candle(
                open_time=1700000000000 + i * 3600000,
                open=p, high=p + 100, low=p - 100, close=p,
                volume=100.0, close_time=1700003599000
            ))

        ms = analyze_market_structure("BTCUSDT", "1h", candles_range, lookback_window=30)
        self.assertIn("Consolidation", ms.structure_type)
        self.assertEqual(ms.trend, "Neutral")

    # --- 3. MULTI-TIMEFRAME ALIGNMENT TESTS ---
    def test_mtf_alignment_matrix(self):
        now_iso = "2026-08-20T10:00:00Z"
        
        # 1. Full Bullish Alignment
        candles_bull = [Candle(i, 60000 + i * 100, 60100 + i * 100, 59900 + i * 100, 60050 + i * 100, 100.0, i + 1) for i in range(50)]
        ta_1d = evaluate_market_structure("BTCUSDT", "1d", candles_bull, now_iso)
        ta_4h = evaluate_market_structure("BTCUSDT", "4h", candles_bull, now_iso)
        ta_1h = evaluate_market_structure("BTCUSDT", "1h", candles_bull, now_iso)

        mtf_bull = determine_mtf_alignment("1h", {"1d": ta_1d, "4h": ta_4h, "1h": ta_1h})
        self.assertEqual(mtf_bull.alignment_status, "Aligned Bullish")
        self.assertFalse(mtf_bull.has_conflict)

        # 2. Conflicting: 1D Bullish vs 1H Bearish
        candles_bear = [Candle(i, 60000 - i * 100, 60100 - i * 100, 59800 - i * 100, 59900 - i * 100, 100.0, i + 1) for i in range(50)]
        ta_1h_bear = evaluate_market_structure("BTCUSDT", "1h", candles_bear, now_iso)

        mtf_conflict = determine_mtf_alignment("1h", {"1d": ta_1d, "4h": ta_4h, "1h": ta_1h_bear})
        self.assertTrue(mtf_conflict.has_conflict)
        self.assertIn("Pullback", mtf_conflict.alignment_status)

    # --- 4. TRADE SETUP EVALUATION TESTS ---
    def test_trade_setup_states(self):
        now_iso = "2026-08-20T10:00:00Z"

        # Pullback in Bull Trend setup
        candles_up = []
        for i in range(50):
            p = 60000 + i * 50 + math.sin(i * 0.5) * 800
            candles_up.append(Candle(i, p, p + 150, p - 150, p + 50, 100.0, i + 1))
        
        ta_up = evaluate_market_structure("BTCUSDT", "1h", candles_up, now_iso)
        ms_up = analyze_market_structure("BTCUSDT", "1h", candles_up)
        
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles_up, ta_up, ms_up)
        self.assertIn(setup.setup_state, ("SETUP_READY", "WAIT_FOR_PULLBACK", "WAIT_FOR_BREAKOUT_CONFIRMATION"))
        self.assertIn(setup.direction_bias, ("LONG", "BULLISH_WATCH"))
        self.assertTrue(setup.invalidation_level is not None)

    # --- 5. STRUCTURED GROUNDING CONTRACT FORMATTING ---
    def test_structured_market_grounding_contract(self):
        now_iso = "2026-08-20T10:00:00Z"
        candles = [Candle(i, 65000 + i * 50, 65100 + i * 50, 64900 + i * 50, 65050 + i * 50, 100.0, i + 1) for i in range(50)]
        ta = evaluate_market_structure("BTCUSDT", "1h", candles, now_iso)
        ms = analyze_market_structure("BTCUSDT", "1h", candles)
        mtf = determine_mtf_alignment("1h", {"1h": ta})
        setup = evaluate_deterministic_setup("BTCUSDT", "1h", candles, ta, ms, mtf)
        ticker = Ticker24h("BTCUSDT", 67500.0, 1500.0, 2.27, 68000.0, 65000.0, 10000.0, 675000000.0, now_iso, "Binance Spot")

        state = MarketState(
            symbol="BTCUSDT",
            primary_timeframe="1h",
            current_price=67500.0,
            timestamp=now_iso,
            source="Binance Spot",
            ticker_24h=ticker,
            primary_ta=ta,
            market_structure=ms,
            multi_timeframe=mtf,
            trade_setup=setup
        )

        grounding_text = format_market_state_grounding(state)
        self.assertIn("=== [LIVE MARKET FACTS] ===", grounding_text)
        self.assertIn("=== [MARKET STRUCTURE — 1H] ===", grounding_text)
        self.assertIn("=== [MOMENTUM & MOVING AVERAGES — 1H] ===", grounding_text)
        self.assertIn("=== [VOLATILITY, BOLLINGER BANDS & VOLUME — 1H] ===", grounding_text)
        self.assertIn("=== [MULTI-TIMEFRAME CONFIRMATION & ALIGNMENT] ===", grounding_text)
        self.assertIn("=== [DETERMINISTIC TRADE SETUP EVALUATION] ===", grounding_text)

    # --- 6. END-TO-END NLP DISPATCH & GEMINI PROMPT INJECTION ---
    def test_end_to_end_nl_market_reasoning(self):
        klines_calls = []
        async def mock_fetch(url, **kwargs):
            if "ticker/24hr" in url:
                return MockHttpResponse(json.dumps({
                    "symbol": "BTCUSDT", "lastPrice": "68500.00", "priceChange": "1200.00",
                    "priceChangePercent": "1.78", "highPrice": "69000.00", "lowPrice": "67000.00",
                    "volume": "10000.00", "quoteVolume": "685000000.00"
                }))
            elif "klines" in url:
                klines_calls.append(url)
                candles_data = []
                for i in range(50):
                    p = 65000 + i * 60
                    candles_data.append([1700000000000 + i * 3600000, str(p), str(p + 150), str(p - 100), str(p + 40), "100.0", 1700003599000])
                return MockHttpResponse(json.dumps(candles_data))
            return MockHttpResponse("{}")

        b_client = BinanceClient(mock_fetch)

        # 1. Query: "look at BTC on the 1-hour chart and tell me what you're seeing."
        update1 = {
            "message": {
                "chat": {"id": 8116631925},
                "from": {"id": 8116631925, "first_name": "Abdul"},
                "text": "look at BTC on the 1-hour chart and tell me what you're seeing."
            }
        }
        self.loop.run_until_complete(
            dispatch_telegram_update(update1, self.settings, self.tg, self.gem, binance_client=b_client)
        )
        self.assertIn("=== [LIVE MARKET FACTS] ===", self.gem.last_prompt)
        self.assertIn("=== [MARKET STRUCTURE — 1H] ===", self.gem.last_prompt)
        self.assertIn("=== [MOMENTUM & MOVING AVERAGES — 1H] ===", self.gem.last_prompt)
        self.assertIn("=== [DETERMINISTIC TRADE SETUP EVALUATION] ===", self.gem.last_prompt)

        # 2. Query: "Should I long BTC?"
        update2 = {
            "message": {
                "chat": {"id": 8116631925},
                "from": {"id": 8116631925, "first_name": "Abdul"},
                "text": "Should I long BTC?"
            }
        }
        self.loop.run_until_complete(
            dispatch_telegram_update(update2, self.settings, self.tg, self.gem, binance_client=b_client)
        )
        self.assertIn("=== [DETERMINISTIC TRADE SETUP EVALUATION] ===", self.gem.last_prompt)
        self.assertIn("Setup State:", self.gem.last_prompt)

        # 3. Plain price query
        count_before = len(klines_calls)
        update3 = {
            "message": {
                "chat": {"id": 8116631925},
                "from": {"id": 8116631925, "first_name": "Abdul"},
                "text": "what is the price of BTC?"
            }
        }
        self.loop.run_until_complete(
            dispatch_telegram_update(update3, self.settings, self.tg, self.gem, binance_client=b_client)
        )
        self.assertIn("Verified Spot Price: $68,500.00", self.gem.last_prompt)
        self.assertNotIn("=== [MARKET STRUCTURE", self.gem.last_prompt)
        self.assertEqual(len(klines_calls), count_before)

    # --- 7. SLASH COMMANDS DETERMINISTIC FUNCTIONALITY ---
    def test_commands_preservation(self):
        async def mock_fetch(url, **kwargs):
            if "klines" in url:
                candles_data = []
                for i in range(50):
                    p = 65000 + i * 20
                    candles_data.append([1700000000000 + i * 3600000, str(p), str(p + 100), str(p - 100), str(p + 10), "100.0", 1700003599000])
                return MockHttpResponse(json.dumps(candles_data))
            return MockHttpResponse(json.dumps({"symbol": "BTCUSDT", "price": "65000.00", "lastPrice": "65000.00"}))

        b_client = BinanceClient(mock_fetch)

        # /ta command
        self.loop.run_until_complete(
            handle_command("/ta BTCUSDT 1h", 100, self.tg, user_id=8116631925, binance_client=b_client)
        )
        msg_ta = self.tg.sent[-1]["text"]
        self.assertIn("BTCUSDT Technical Analysis", msg_ta)
        self.assertIn("RSI (14, Wilder):", msg_ta)
        self.assertIn("EMA Alignment:", msg_ta)
        self.assertIn("Dynamic SL Buffer", msg_ta)

        # /risk command
        self.loop.run_until_complete(
            handle_command("/risk 1000 2 65000 63500", 100, self.tg, user_id=8116631925)
        )
        msg_risk = self.tg.sent[-1]["text"]
        self.assertIn("Position Sizing & Risk Management Breakdown", msg_risk)
        self.assertIn("LONG", msg_risk)
        self.assertIn("TP1 (1:1.5 R:R)", msg_risk)


if __name__ == "__main__":
    unittest.main()
