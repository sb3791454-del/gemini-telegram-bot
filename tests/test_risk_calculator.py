"""Unit tests for Risk Management & Position Sizing Engine."""

import unittest
from trading.risk_calculator import calculate_position_risk


class TestRiskCalculator(unittest.TestCase):
    def test_long_position_sizing_exact_math(self):
        # Capital: $10,000, Risk: 1% ($100), Entry: $60,000, Stop Loss: $58,000 (diff $2,000)
        # Position size in BTC = 100 / 2000 = 0.05 BTC
        # Position value USD = 0.05 * 60,000 = $3,000
        # Effective leverage = 3,000 / 10,000 = 0.3x
        res = calculate_position_risk(10000, 1.0, 60000, 58000)
        self.assertEqual(res.direction, "LONG")
        self.assertEqual(res.risk_usd, 100.0)
        self.assertAlmostEqual(res.price_risk_pct, 3.333, places=2)
        self.assertAlmostEqual(res.position_size_coins, 0.05, places=4)
        self.assertAlmostEqual(res.position_value_usd, 3000.0, places=2)
        self.assertAlmostEqual(res.effective_leverage, 0.3, places=2)
        # Take profits: TP1 = 60,000 + 1.5 * 2000 = 63,000
        self.assertEqual(res.tp1_price, 63000.0)
        # TP2 = 60,000 + 2.0 * 2000 = 64,000
        self.assertEqual(res.tp2_price, 64000.0)
        # TP3 = 60,000 + 3.0 * 2000 = 66,000
        self.assertEqual(res.tp3_price, 66000.0)
        self.assertEqual(len(res.warnings), 0)

    def test_short_position_sizing_exact_math(self):
        # Capital: $5,000, Risk: 2% ($100), Entry: $100, Stop Loss: $105 (diff $5)
        # Position size = 100 / 5 = 20 coins
        # Value USD = 20 * 100 = $2,000
        # TP1 (1:1.5) = 100 - 1.5 * 5 = 92.5
        res = calculate_position_risk(5000, 2.0, 100, 105)
        self.assertEqual(res.direction, "SHORT")
        self.assertEqual(res.risk_usd, 100.0)
        self.assertEqual(res.position_size_coins, 20.0)
        self.assertEqual(res.position_value_usd, 2000.0)
        self.assertEqual(res.tp1_price, 92.5)
        self.assertEqual(res.tp2_price, 90.0)
        self.assertEqual(res.tp3_price, 85.0)

    def test_high_risk_and_leverage_warnings(self):
        # Capital: $100, Risk: 10% ($10), Entry: $60,000, Stop Loss: $59,500 (diff $500)
        # Size = 10 / 500 = 0.02 BTC -> Value $1,200 -> Leverage 12x
        res = calculate_position_risk(100, 10.0, 60000, 59500)
        self.assertGreater(len(res.warnings), 0)
        warning_text = " ".join(res.warnings)
        self.assertIn("High Risk", warning_text)
        self.assertIn("High Leverage", warning_text)

    def test_invalid_parameters_raise_value_error(self):
        with self.assertRaises(ValueError):
            calculate_position_risk(0, 1, 60000, 58000)  # zero capital
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, -1, 60000, 58000)  # negative risk
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 1, 60000, 60000)  # identical entry and SL
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 1, 60000, 62000, direction="LONG")  # Long with SL above entry


if __name__ == "__main__":
    unittest.main()
