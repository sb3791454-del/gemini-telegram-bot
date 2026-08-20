"""Integration tests for Watchlist, Technical Analysis, and Risk commands in router."""

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
from ai.prompts_builder import (
    extract_crypto_symbols,
    extract_timeframe,
    has_technical_analysis_intent,
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
        self.watchlist = {}  # (user_id, symbol) -> item

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


class TestPhase8Commands(unittest.TestCase):
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

    def test_extract_crypto_symbols(self):
        symbols = extract_crypto_symbols("What is the trend for Bitcoin and Solana today?")
        self.assertIn("BTCUSDT", symbols)
        self.assertIn("SOLUSDT", symbols)

        symbols_pepe = extract_crypto_symbols("Should I buy PEPE or ETH?")
        self.assertIn("PEPEUSDT", symbols_pepe)
        self.assertIn("ETHUSDT", symbols_pepe)

    def test_extract_timeframe(self):
        self.assertEqual(extract_timeframe("look at BTC on the 1-hour chart and tell me what you're seeing."), "1h")
        self.assertEqual(extract_timeframe("analyze BTC on 4h"), "4h")
        self.assertEqual(extract_timeframe("what is ETH looking like on the 15 minute chart?"), "15m")
        self.assertEqual(extract_timeframe("give me technical confirmation for SOL on 1h"), "1h")
        self.assertEqual(extract_timeframe("what does BTC look like on the daily timeframe?"), "1d")
        self.assertEqual(extract_timeframe("check SOL on 15m"), "15m")
        self.assertEqual(extract_timeframe("what is Bitcoin doing hourly?"), "1h")
        self.assertEqual(extract_timeframe("analyze Ethereum weekly chart"), "1w")
        self.assertEqual(extract_timeframe("how is btc looking on 4 hours timeframe"), "4h")
        self.assertIsNone(extract_timeframe("what is the price of BTC?"))
        self.assertIsNone(extract_timeframe("tell me a joke"))

    def test_has_technical_analysis_intent(self):
        self.assertTrue(has_technical_analysis_intent("look at BTC on the 1-hour chart and tell me what you're seeing"))
        self.assertTrue(has_technical_analysis_intent("analyze BTC on 4h"))
        self.assertTrue(has_technical_analysis_intent("is BTC overbought?"))
        self.assertTrue(has_technical_analysis_intent("what is RSI for Solana?"))
        self.assertTrue(has_technical_analysis_intent("give me technical confirmation for SOL on 1h"))
        self.assertFalse(has_technical_analysis_intent("what is the price of BTC?"))
        self.assertFalse(has_technical_analysis_intent("hello assistant"))

    def test_watch_and_watchlist_commands(self):
        async def mock_fetch(url, **kwargs):
            return MockHttpResponse(json.dumps({
                "symbol": "SOLUSDT",
                "price": "150.00",
                "lastPrice": "150.00",
                "priceChange": "5.0",
                "priceChangePercent": "3.45"
            }))

        b_client = BinanceClient(mock_fetch)

        # 1. /watch SOL
        self.loop.run_until_complete(
            handle_command("/watch SOL", 100, self.tg, user_id=8116631925, watchlist_repo=self.wl_repo, binance_client=b_client)
        )
        self.assertIn("Watchlist Added", self.tg.sent[-1]["text"])
        self.assertIn("SOLUSDT", self.tg.sent[-1]["text"])

        # 2. /watchlist
        self.loop.run_until_complete(
            handle_command("/watchlist", 100, self.tg, user_id=8116631925, watchlist_repo=self.wl_repo, binance_client=b_client)
        )
        self.assertIn("SOLUSDT", self.tg.sent[-1]["text"])
        self.assertIn("150.00", self.tg.sent[-1]["text"])

        # 3. /unwatch SOL
        self.loop.run_until_complete(
            handle_command("/unwatch SOL", 100, self.tg, user_id=8116631925, watchlist_repo=self.wl_repo, binance_client=b_client)
        )
        self.assertIn("Removed from Watchlist", self.tg.sent[-1]["text"])

    def test_risk_command(self):
        self.loop.run_until_complete(
            handle_command("/risk 1000 2 65000 63500", 100, self.tg, user_id=8116631925)
        )
        msg = self.tg.sent[-1]["text"]
        self.assertIn("Position Sizing & Risk Management Breakdown", msg)
        self.assertIn("LONG", msg)
        self.assertIn("Max Risk Budget", msg)
        self.assertIn("TP1", msg)

    def test_ta_command_deterministic(self):
        async def mock_fetch(url, **kwargs):
            klines = []
            for i in range(50):
                klines.append([1700000000000 + i * 3600000, "60000", "61000", "59000", "60500", "100.0", 1700003599000])
            return MockHttpResponse(json.dumps(klines))

        b_client = BinanceClient(mock_fetch)
        self.loop.run_until_complete(
            handle_command("/ta BTCUSDT 1h", 100, self.tg, user_id=8116631925, binance_client=b_client)
        )
        msg = self.tg.sent[-1]["text"]
        self.assertIn("BTCUSDT Technical Analysis", msg)
        self.assertIn("RSI (14)", msg)
        self.assertIn("EMA 20", msg)
        self.assertIn("Bollinger Bands", msg)
        self.assertIn("ATR (14)", msg)

    def test_memory_crud_and_status_commands(self):
        mem_storage = []
        class MockFullD1Binding:
            def prepare(self, sql):
                class Stmt:
                    def __init__(self, s):
                        self.s = s
                        self.params = []
                    def bind(self, *params):
                        self.params = list(params)
                        return self
                    async def run(self):
                        if "INSERT INTO conversation_memories" in self.s:
                            uid, mtype, content, now, _ = self.params
                            mem_storage.append({"id": len(mem_storage) + 1, "telegram_user_id": uid, "memory_type": mtype, "content": content})
                        elif "DELETE FROM conversation_memories" in self.s:
                            mid, uid = self.params
                            mem_storage[:] = [m for m in mem_storage if not (m["telegram_user_id"] == uid and m["id"] == mid)]
                        return {"meta": {"changes": 1}}
                    async def first(self):
                        if "SELECT COUNT(*)" in self.s and "conversation_memories" in self.s:
                            return {"count": len(mem_storage)}
                        if "SELECT COUNT(*)" in self.s and "user_watchlist" in self.s:
                            return {"count": 1}
                        if "SELECT COUNT(*)" in self.s and "conversation_messages" in self.s:
                            return {"count": 5}
                        if "SELECT * FROM user_profiles" in self.s:
                            return {"display_name": "Abdul"}
                        if "LOWER(TRIM(content))" in self.s:
                            return None
                        return None
                    async def all(self):
                        if "conversation_memories" in self.s:
                            return SimpleNamespace(results=list(mem_storage))
                        return SimpleNamespace(results=[])
                return Stmt(sql)

        full_db = D1Database(MockFullD1Binding())
        user_repo = UserRepository(full_db)
        mem_repo = MemoryRepository(full_db)
        conv_repo = ConversationRepository(full_db)

        # 1. /remember
        self.loop.run_until_complete(
            handle_command("/remember Always risk max 1%", 100, self.tg, user_id=8116631925, memory_repo=mem_repo)
        )
        self.assertIn("Memory Saved", self.tg.sent[-1]["text"])
        self.assertEqual(len(mem_storage), 1)

        # 2. /memories
        self.loop.run_until_complete(
            handle_command("/memories", 100, self.tg, user_id=8116631925, memory_repo=mem_repo)
        )
        self.assertIn("Always risk max 1%", self.tg.sent[-1]["text"])

        # 3. /forget 1
        self.loop.run_until_complete(
            handle_command("/forget 1", 100, self.tg, user_id=8116631925, memory_repo=mem_repo)
        )
        self.assertIn("Memory #1 Deleted", self.tg.sent[-1]["text"])
        self.assertEqual(len(mem_storage), 0)

        # 4. /memory status
        self.loop.run_until_complete(
            handle_command("/memory", 100, self.tg, user_id=8116631925, user_repo=user_repo, memory_repo=mem_repo, conversation_repo=conv_repo, watchlist_repo=self.wl_repo)
        )
        self.assertIn("State & Memory Status", self.tg.sent[-1]["text"])
        self.assertIn("واچ لسٹ کوائنز", self.tg.sent[-1]["text"])

    def test_natural_language_timeframe_aware_ta_grounding(self):
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
                klines = []
                for i in range(50):
                    klines.append([1700000000000 + i * 3600000, "67000", "68000", "66500", "67800", "100.0", 1700003599000])
                return MockHttpResponse(json.dumps(klines))
            return MockHttpResponse("{}")

        b_client = BinanceClient(mock_fetch)

        # 1. 1-hour natural language query
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
        self.assertIn("BTCUSDT - 1H Timeframe", self.gem.last_prompt)
        self.assertIn("RSI (14, Wilder Smoothed)", self.gem.last_prompt)
        self.assertIn("EMA 20", self.gem.last_prompt)
        self.assertIn("Bollinger Bands", self.gem.last_prompt)
        self.assertIn("ATR-14", self.gem.last_prompt)
        self.assertIn("interval=1h", klines_calls[-1])

        # 2. 4h natural language query
        update2 = {
            "message": {
                "chat": {"id": 8116631925},
                "from": {"id": 8116631925, "first_name": "Abdul"},
                "text": "analyze BTC on 4h"
            }
        }
        self.loop.run_until_complete(
            dispatch_telegram_update(update2, self.settings, self.tg, self.gem, binance_client=b_client)
        )
        self.assertIn("BTCUSDT - 4H Timeframe", self.gem.last_prompt)
        self.assertIn("interval=4h", klines_calls[-1])

        # 3. Daily timeframe natural language query
        update3 = {
            "message": {
                "chat": {"id": 8116631925},
                "from": {"id": 8116631925, "first_name": "Abdul"},
                "text": "what does BTC look like on the daily timeframe?"
            }
        }
        self.loop.run_until_complete(
            dispatch_telegram_update(update3, self.settings, self.tg, self.gem, binance_client=b_client)
        )
        self.assertIn("BTCUSDT - 1D Timeframe", self.gem.last_prompt)
        self.assertIn("interval=1d", klines_calls[-1])

        # 4. Plain price query without TA intent
        count_before = len(klines_calls)
        update4 = {
            "message": {
                "chat": {"id": 8116631925},
                "from": {"id": 8116631925, "first_name": "Abdul"},
                "text": "what is the price of BTC?"
            }
        }
        self.loop.run_until_complete(
            dispatch_telegram_update(update4, self.settings, self.tg, self.gem, binance_client=b_client)
        )
        self.assertIn("Verified Spot Price: $68,500.00", self.gem.last_prompt)
        self.assertNotIn("Deterministic Technical Analysis", self.gem.last_prompt)
        self.assertEqual(len(klines_calls), count_before)


if __name__ == "__main__":
    unittest.main()
