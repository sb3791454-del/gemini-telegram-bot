"""Unit tests for Cryptocurrency public REST market data client, error sanitization, and fallback."""

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


class TestMarketDataClient(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_symbol_normalization(self):
        """Verify robust normalization and uppercase handling."""
        self.assertEqual(BinanceClient.normalize_symbol("btc"), "BTCUSDT")
        self.assertEqual(BinanceClient.normalize_symbol("eth/usdt"), "ETHUSDT")
        self.assertEqual(BinanceClient.normalize_symbol("sol_usdt"), "SOLUSDT")
        self.assertEqual(BinanceClient.normalize_symbol("bnb-usdt"), "BNBUSDT")
        self.assertEqual(BinanceClient.normalize_symbol("ada"), "ADAUSDT")
        self.assertEqual(BinanceClient.normalize_symbol("usdt"), "USDT")

        with self.assertRaises(ValueError):
            BinanceClient.normalize_symbol("A")  # too short (<2 chars)
        with self.assertRaises(ValueError):
            BinanceClient.normalize_symbol("BTC!@#USDT")  # invalid characters

    def test_get_price_success_binance(self):
        """Verify successful price fetching from Binance primary feed."""
        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse(json.dumps({"symbol": "BTCUSDT", "price": "65432.10"}), status=200)

        client = BinanceClient(mock_fetch)
        ticker = self.loop.run_until_complete(client.get_price("BTCUSDT"))
        self.assertIsInstance(ticker, PriceTicker)
        self.assertEqual(ticker.symbol, "BTCUSDT")
        self.assertEqual(ticker.price, 65432.10)
        self.assertEqual(ticker.source, "Binance Spot")
        self.assertTrue(ticker.timestamp.endswith("Z"))

    def test_get_price_usdt_peg(self):
        """Verify /price USDT returns $1.00 USD tether peg immediately."""
        async def mock_fetch(url, method="GET", **kwargs):
            raise RuntimeError("Should not be called for USDT")

        client = BinanceClient(mock_fetch)
        ticker = self.loop.run_until_complete(client.get_price("USDT"))
        self.assertEqual(ticker.symbol, "USDT")
        self.assertEqual(ticker.price, 1.0)
        self.assertEqual(ticker.source, "Tether USD Peg")

    def test_get_price_fallback_to_bybit_on_binance_403(self):
        """Verify that if Binance returns 403 (geoblock/WAF), client seamlessly falls back to Bybit."""
        async def mock_fetch(url, method="GET", **kwargs):
            if "binance" in url:
                return MockHttpResponse("<html>Forbidden</html>", status=403)
            if "bybit.com" in url:
                return MockHttpResponse(json.dumps({
                    "retCode": 0,
                    "result": {"list": [{"symbol": "BTCUSDT", "lastPrice": "65123.45"}]}
                }), status=200)
            return MockHttpResponse("Not found", status=404)

        client = BinanceClient(mock_fetch)
        ticker = self.loop.run_until_complete(client.get_price("BTCUSDT"))
        self.assertEqual(ticker.price, 65123.45)
        self.assertEqual(ticker.source, "Bybit Spot")

    def test_get_price_fallback_to_okx_on_binance_bybit_fail(self):
        """Verify that if Binance and Bybit fail, client falls back to OKX."""
        async def mock_fetch(url, method="GET", **kwargs):
            if "binance" in url or "bybit" in url:
                return MockHttpResponse("Error", status=500)
            if "okx.com" in url:
                return MockHttpResponse(json.dumps({
                    "code": "0",
                    "data": [{"last": "65200.00"}]
                }), status=200)
            return MockHttpResponse("Not found", status=404)

        client = BinanceClient(mock_fetch)
        ticker = self.loop.run_until_complete(client.get_price("BTCUSDT"))
        self.assertEqual(ticker.price, 65200.00)
        self.assertEqual(ticker.source, "OKX Spot")

    def test_403_html_error_sanitization(self):
        """Verify that if all feeds fail with HTML 403, sanitized error with zero HTML leakage is produced."""
        html_payload = "<!DOCTYPE html><html><head><title>403 Forbidden</title></head><body><h1>403 Forbidden</h1>CloudFront Ray ID: 8b12345678</body></html>"

        async def mock_fetch(url, method="GET", **kwargs):
            return MockHttpResponse(html_payload, status=403)

        client = BinanceClient(mock_fetch)
        with self.assertRaises(BinanceAPIError) as ctx:
            self.loop.run_until_complete(client.get_price("BTCUSDT"))

        err_msg = str(ctx.exception)
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

    def test_400_valid_json_error(self):
        """Verify HTTP 400 with valid JSON preserves numeric error code."""
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

    def test_get_24h_ticker_fallback(self):
        """Verify get_24h_ticker fallback works seamlessly."""
        async def mock_fetch(url, method="GET", **kwargs):
            if "binance" in url:
                return MockHttpResponse("Forbidden", status=403)
            if "bybit.com" in url:
                return MockHttpResponse(json.dumps({
                    "retCode": 0,
                    "result": {"list": [{
                        "symbol": "BTCUSDT",
                        "lastPrice": "65000.00",
                        "highPrice24h": "66000.00",
                        "lowPrice24h": "64000.00",
                        "price24hPcnt": "0.025",
                        "prevPrice24h": "63414.63",
                        "volume24h": "1000.0",
                        "turnover24h": "65000000.0"
                    }]}
                }), status=200)
            return MockHttpResponse("Not found", status=404)

        client = BinanceClient(mock_fetch)
        ticker = self.loop.run_until_complete(client.get_24h_ticker("BTCUSDT"))
        self.assertEqual(ticker.last_price, 65000.00)
        self.assertEqual(ticker.high_price, 66000.00)
        self.assertEqual(ticker.low_price, 64000.00)
        self.assertEqual(ticker.source, "Bybit Spot")

    def test_get_order_book_depth_fallback(self):
        """Verify get_order_book_depth fallback works seamlessly."""
        async def mock_fetch(url, method="GET", **kwargs):
            if "binance" in url:
                return MockHttpResponse("Forbidden", status=403)
            if "bybit.com" in url:
                return MockHttpResponse(json.dumps({
                    "retCode": 0,
                    "result": {
                        "s": "BTCUSDT",
                        "b": [["65000.00", "1.5"], ["64990.00", "2.0"]],
                        "a": [["65010.00", "1.2"], ["65020.00", "3.0"]]
                    }
                }), status=200)
            return MockHttpResponse("Not found", status=404)

        client = BinanceClient(mock_fetch)
        depth = self.loop.run_until_complete(client.get_order_book_depth("BTCUSDT"))
        self.assertEqual(depth.best_bid, 65000.00)
        self.assertEqual(depth.best_ask, 65010.00)
        self.assertEqual(depth.source, "Bybit Order Book")


if __name__ == "__main__":
    unittest.main()
