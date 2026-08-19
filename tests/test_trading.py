"""Unit tests for Binance public REST market data client and error sanitization."""

import unittest
import asyncio
import json
from trading.binance_client import BinanceClient, BinanceAPIError, handle_binance_error_response
from trading.models import PriceTicker, Ticker24h, OrderBookDepth


class MockHttpResponse:
    def __init__(self, text_data: str, status: int = 200):
        self._text = text_data
        self.status = status

    async def text(self):
        return self._text

    async def json(self):
        return json.loads(self._text)


class TestBinanceClient(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_base_url_remains_data_api_binance_vision(self):
        """Verify BASE_URL is data-api.binance.vision and api.binance.com is absent."""
        self.assertEqual(BinanceClient.BASE_URL, "https://data-api.binance.vision")
        self.assertNotIn("api.binance.com", BinanceClient.BASE_URL)

    def test_symbol_normalization(self):
        """Verify robust normalization and uppercase handling."""
        self.assertEqual(BinanceClient.normalize_symbol("btc"), "BTCUSDT")
        self.assertEqual(BinanceClient.normalize_symbol("eth/usdt"), "ETHUSDT")
        self.assertEqual(BinanceClient.normalize_symbol("sol_usdt"), "SOLUSDT")
        self.assertEqual(BinanceClient.normalize_symbol("bnb-usdt"), "BNBUSDT")
        self.assertEqual(BinanceClient.normalize_symbol("ada"), "ADAUSDT")

        with self.assertRaises(ValueError):
            BinanceClient.normalize_symbol("A")  # too short (<2 chars)
        with self.assertRaises(ValueError):
            BinanceClient.normalize_symbol("BTC!@#USDT")  # invalid characters

    def test_get_price_success(self):
        """Verify successful price fetching."""
        async def mock_fetch(url, method="GET", **kwargs):
            self.assertIn("https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT", url)
            return MockHttpResponse(json.dumps({"symbol": "BTCUSDT", "price": "65432.10"}), status=200)

        client = BinanceClient(mock_fetch)
        ticker = self.loop.run_until_complete(client.get_price("BTCUSDT"))
        self.assertIsInstance(ticker, PriceTicker)
        self.assertEqual(ticker.symbol, "BTCUSDT")
        self.assertEqual(ticker.price, 65432.10)
        self.assertTrue(ticker.timestamp.endswith("Z"))

    def test_403_html_error_sanitization(self):
        """Verify 403 Forbidden with HTML body produces exactly sanitized error with zero HTML leakage."""
        html_payload = "<!DOCTYPE html><html><head><title>403 Forbidden</title></head><body><h1>403 Forbidden</h1>CloudFront Ray ID: 8b12345678</body></html>"

        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse(html_payload, status=403)

        client = BinanceClient(mock_fetch)
        with self.assertRaises(BinanceAPIError) as ctx:
            self.loop.run_until_complete(client.get_price("BTCUSDT"))

        err_msg = str(ctx.exception)
        self.assertEqual(err_msg, "Binance returned error status 403.")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertNotIn("<html", err_msg.lower())
        self.assertNotIn("cloudfront", err_msg.lower())
        self.assertNotIn("ray id", err_msg.lower())

    def test_429_rate_limit_error(self):
        """Verify HTTP 429 produces deterministic rate limit error."""
        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse("Too Many Requests", status=429)

        client = BinanceClient(mock_fetch)
        with self.assertRaises(BinanceAPIError) as ctx:
            self.loop.run_until_complete(client.get_price("BTCUSDT"))

        self.assertEqual(str(ctx.exception), "Rate limit reached (HTTP 429).")
        self.assertEqual(ctx.exception.status_code, 429)

    def test_418_ip_ban_error(self):
        """Verify HTTP 418 produces deterministic IP ban error."""
        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse("IP Banned", status=418)

        client = BinanceClient(mock_fetch)
        with self.assertRaises(BinanceAPIError) as ctx:
            self.loop.run_until_complete(client.get_price("BTCUSDT"))

        self.assertEqual(str(ctx.exception), "IP temporarily banned by Binance (HTTP 418).")
        self.assertEqual(ctx.exception.status_code, 418)

    def test_400_valid_binance_json_error(self):
        """Verify HTTP 400 with valid Binance JSON preserves numeric error code but does not blindly forward raw msg."""
        json_payload = json.dumps({"code": -1121, "msg": "Invalid symbol."})

        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse(json_payload, status=400)

        client = BinanceClient(mock_fetch)
        with self.assertRaises(BinanceAPIError) as ctx:
            self.loop.run_until_complete(client.get_price("INVALID"))

        err_msg = str(ctx.exception)
        self.assertEqual(err_msg, "Binance returned error status 400 (code -1121).")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.error_code, -1121)

    def test_500_html_error_sanitization(self):
        """Verify HTTP 500 with HTML body produces sanitized error with zero HTML."""
        html_payload = "<html><body><h1>500 Internal Server Error</h1></body></html>"

        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse(html_payload, status=500)

        client = BinanceClient(mock_fetch)
        with self.assertRaises(BinanceAPIError) as ctx:
            self.loop.run_until_complete(client.get_price("BTCUSDT"))

        err_msg = str(ctx.exception)
        self.assertEqual(err_msg, "Binance returned error status 500.")
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertNotIn("<", err_msg)
        self.assertNotIn(">", err_msg)

    def test_get_24h_ticker_error_sanitization(self):
        """Verify get_24h_ticker sanitizes errors consistently."""
        html_payload = "<html><body>Error 403</body></html>"
        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse(html_payload, status=403)

        client = BinanceClient(mock_fetch)
        with self.assertRaises(BinanceAPIError) as ctx:
            self.loop.run_until_complete(client.get_24h_ticker("BTCUSDT"))
        self.assertEqual(str(ctx.exception), "Binance returned error status 403.")
        self.assertNotIn("html", str(ctx.exception).lower())

    def test_get_order_book_depth_error_sanitization(self):
        """Verify get_order_book_depth sanitizes errors consistently."""
        html_payload = "<html><body>Error 502 Bad Gateway</body></html>"
        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse(html_payload, status=502)

        client = BinanceClient(mock_fetch)
        with self.assertRaises(BinanceAPIError) as ctx:
            self.loop.run_until_complete(client.get_order_book_depth("BTCUSDT"))
        self.assertEqual(str(ctx.exception), "Binance returned error status 502.")
        self.assertNotIn("html", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
