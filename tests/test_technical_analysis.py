"""Unit tests for Technical Analysis mathematical indicators and market structure."""

import unittest
from trading.models import Candle
from trading.technical_analysis import (
    calculate_sma,
    calculate_ema,
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_atr,
    evaluate_market_structure,
)


class TestTechnicalAnalysis(unittest.TestCase):
    def test_sma_calculation(self):
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        self.assertEqual(calculate_sma(prices, 3), 40.0)
        self.assertEqual(calculate_sma(prices, 5), 30.0)
        self.assertEqual(calculate_sma([], 5), 0.0)

    def test_ema_calculation(self):
        prices = [10.0] * 20 + [20.0]
        ema = calculate_ema(prices, 10)
        self.assertGreater(ema, 10.0)
        self.assertLess(ema, 20.0)

    def test_rsi_calculation_uptrend(self):
        # Monotonically increasing prices should have high RSI
        prices = [float(i) for i in range(10, 40)]
        rsi = calculate_rsi(prices, period=14)
        self.assertGreaterEqual(rsi, 90.0)

    def test_rsi_calculation_downtrend(self):
        # Monotonically decreasing prices should have low RSI
        prices = [float(40 - i) for i in range(30)]
        rsi = calculate_rsi(prices, period=14)
        self.assertLessEqual(rsi, 15.0)

    def test_rsi_flat_market(self):
        # Flat prices should return 50.0
        prices = [100.0] * 30
        rsi = calculate_rsi(prices, period=14)
        self.assertEqual(rsi, 50.0)

    def test_bollinger_bands(self):
        prices = [100.0] * 20
        upper, mid, lower, bw = calculate_bollinger_bands(prices, period=20, num_std=2.0)
        self.assertEqual(mid, 100.0)
        self.assertEqual(upper, 100.0)
        self.assertEqual(lower, 100.0)
        self.assertEqual(bw, 0.0)

        # Non-flat
        prices2 = [100.0 + (i % 5) for i in range(30)]
        upper, mid, lower, bw = calculate_bollinger_bands(prices2, period=20)
        self.assertGreater(upper, mid)
        self.assertLess(lower, mid)
        self.assertGreater(bw, 0.0)

    def test_atr_calculation(self):
        candles = []
        for i in range(30):
            candles.append(Candle(
                open_time=1000 + i * 60,
                open=100.0,
                high=105.0,
                low=95.0,
                close=102.0,
                volume=10.0,
                close_time=1059 + i * 60
            ))
        atr = calculate_atr(candles, period=14)
        self.assertAlmostEqual(atr, 10.0, places=1)

    def test_market_structure_evaluation(self):
        candles = []
        base = 50000.0
        for i in range(50):
            p = base + i * 100
            candles.append(Candle(
                open_time=i * 3600,
                open=p,
                high=p + 50,
                low=p - 30,
                close=p + 40,
                volume=50.0,
                close_time=(i + 1) * 3600 - 1
            ))
        summary = evaluate_market_structure("BTCUSDT", "1h", candles, "2026-08-19T12:00:00Z")
        self.assertEqual(summary.symbol, "BTCUSDT")
        self.assertEqual(summary.timeframe, "1h")
        self.assertIn("Bullish", summary.trend)
        self.assertGreater(summary.resistance_level, summary.support_level)
        self.assertGreater(summary.suggested_sl_distance, 0.0)


if __name__ == "__main__":
    unittest.main()
