"""Tests for Telegram message routing and deterministic command interception."""

import unittest
import asyncio
import json
from types import SimpleNamespace
from config.settings import Settings
from router.command_router import handle_command, parse_command_and_args
from router.message_router import dispatch_telegram_update
from trading.binance_client import BinanceClient, BinanceAPIError
from trading.models import PriceTicker, Ticker24h, OrderBookDepth


class MockHttpResponse:
    def __init__(self, text_data: str, status: int = 200):
        self._text = text_data
        self.status = status

    async def text(self):
        return self._text

    async def json(self):
        return json.loads(self._text)


class MockTelegramClient:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, parse_mode="Markdown"):
        self.sent_messages.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})

    async def send_chat_action(self, chat_id, action="typing"):
        pass


class MockGeminiClient:
    def __init__(self):
        self.generate_text_called = False
        self.generate_vision_called = False

    async def generate_text(self, prompt, model_name=None):
        self.generate_text_called = True
        return "Gemini text response"

    async def generate_vision(self, image_bytes, caption=None, model_name=None):
        self.generate_vision_called = True
        return "Gemini vision response"


class TestMessageRouterAndCommands(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.telegram_client = MockTelegramClient()
        self.gemini_client = MockGeminiClient()
        env = SimpleNamespace(
            TELEGRAM_BOT_TOKEN="dummy_token",
            GEMINI_API_KEY="dummy_gemini_key",
            ALLOWED_USER_IDS="8116631925",
            GEMINI_MODEL="gemini-3.1-flash-lite"
        )
        self.settings = Settings(env)

    def tearDown(self):
        self.loop.close()

    def test_parse_command_and_args(self):
        """Verify command and argument parsing with various formats."""
        cmd, args = parse_command_and_args("/price BTCUSDT")
        self.assertEqual(cmd, "/price")
        self.assertEqual(args, "BTCUSDT")

        cmd, args = parse_command_and_args("/price@sultan_bot  ETHUSDT ")
        self.assertEqual(cmd, "/price")
        self.assertEqual(args, "ETHUSDT")

        cmd, args = parse_command_and_args("/ticker SOL")
        self.assertEqual(cmd, "/ticker")
        self.assertEqual(args, "SOL")

        cmd, args = parse_command_and_args("/depth BTCUSDT")
        self.assertEqual(cmd, "/depth")
        self.assertEqual(args, "BTCUSDT")

        cmd, args = parse_command_and_args("hello there")
        self.assertIsNone(cmd)

    def test_price_command_success_does_not_call_gemini(self):
        """Verify /price successfully formats price and never invokes Gemini."""
        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse(json.dumps({"symbol": "BTCUSDT", "price": "60000.00"}), status=200)

        binance_client = BinanceClient(mock_fetch)
        update = {
            "message": {
                "message_id": 1,
                "date": 1723900000,
                "chat": {"id": 12345},
                "from": {"id": 8116631925, "is_bot": False, "first_name": "Test"},
                "text": "/price BTCUSDT"
            }
        }

        self.loop.run_until_complete(
            dispatch_telegram_update(
                update,
                self.settings,
                self.telegram_client,
                self.gemini_client,
                binance_client=binance_client
            )
        )

        self.assertFalse(self.gemini_client.generate_text_called)
        self.assertEqual(len(self.telegram_client.sent_messages), 1)
        msg = self.telegram_client.sent_messages[0]["text"]
        self.assertIn("BTCUSDT Live Price", msg)
        self.assertIn("60,000.00", msg)

    def test_price_command_binance_failure_does_not_call_gemini(self):
        """CRITICAL: Verify that when Binance returns error (403 HTML), error is sent and Gemini is NEVER called."""
        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse("<html>Forbidden</html>", status=403)

        binance_client = BinanceClient(mock_fetch)
        update = {
            "message": {
                "message_id": 1,
                "date": 1723900000,
                "chat": {"id": 12345},
                "from": {"id": 8116631925, "is_bot": False, "first_name": "Test"},
                "text": "/price BTCUSDT"
            }
        }

        self.loop.run_until_complete(
            dispatch_telegram_update(
                update,
                self.settings,
                self.telegram_client,
                self.gemini_client,
                binance_client=binance_client
            )
        )

        # Gemini must NEVER be called
        self.assertFalse(self.gemini_client.generate_text_called)
        self.assertEqual(len(self.telegram_client.sent_messages), 1)
        msg = self.telegram_client.sent_messages[0]["text"]
        self.assertIn("Market Data Error", msg)
        self.assertIn("Binance returned error status 403.", msg)
        self.assertNotIn("html", msg.lower())
        self.assertIn("No market value or analysis will be guessed", msg)

    def test_ticker_command_binance_failure_does_not_call_gemini(self):
        """Verify that /ticker error never falls through to Gemini."""
        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse("Rate limit", status=429)

        binance_client = BinanceClient(mock_fetch)
        update = {
            "message": {
                "message_id": 2,
                "date": 1723900000,
                "chat": {"id": 12345},
                "from": {"id": 8116631925, "is_bot": False, "first_name": "Test"},
                "text": "/ticker ETHUSDT"
            }
        }

        self.loop.run_until_complete(
            dispatch_telegram_update(
                update,
                self.settings,
                self.telegram_client,
                self.gemini_client,
                binance_client=binance_client
            )
        )

        self.assertFalse(self.gemini_client.generate_text_called)
        self.assertEqual(len(self.telegram_client.sent_messages), 1)
        msg = self.telegram_client.sent_messages[0]["text"]
        self.assertIn("Market Data Error", msg)
        self.assertIn("Rate limit reached (HTTP 429).", msg)

    def test_depth_command_binance_failure_does_not_call_gemini(self):
        """Verify that /depth error never falls through to Gemini."""
        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse("<html>Server Error</html>", status=500)

        binance_client = BinanceClient(mock_fetch)
        update = {
            "message": {
                "message_id": 3,
                "date": 1723900000,
                "chat": {"id": 12345},
                "from": {"id": 8116631925, "is_bot": False, "first_name": "Test"},
                "text": "/depth SOLUSDT"
            }
        }

        self.loop.run_until_complete(
            dispatch_telegram_update(
                update,
                self.settings,
                self.telegram_client,
                self.gemini_client,
                binance_client=binance_client
            )
        )

        self.assertFalse(self.gemini_client.generate_text_called)
        self.assertEqual(len(self.telegram_client.sent_messages), 1)
        msg = self.telegram_client.sent_messages[0]["text"]
        self.assertIn("Market Data Error", msg)
        self.assertIn("Binance returned error status 500.", msg)


if __name__ == "__main__":
    unittest.main()
