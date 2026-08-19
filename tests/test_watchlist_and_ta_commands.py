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
from ai.prompts_builder import extract_crypto_symbols


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


if __name__ == "__main__":
    unittest.main()
