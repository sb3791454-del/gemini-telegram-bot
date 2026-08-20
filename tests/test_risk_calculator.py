"""Unit tests for Risk Management & Position Sizing Engine."""

import unittest
from trading.risk_calculator import (
    DEFAULT_ATR_MULTIPLIER,
    calculate_hard_stop,
    calculate_position_risk,
)


class TestRiskCalculator(unittest.TestCase):
    def test_default_atr_multiplier_is_one_point_five(self):
        """Verify the single deterministic source of truth for k is 1.5."""
        self.assertEqual(DEFAULT_ATR_MULTIPLIER, 1.5)

    def test_calculate_hard_stop_long(self):
        """Verify for LONG: Hard SL = Structural Warning - (1.5 * ATR), strictly below structural warning."""
        sw = 70000.0
        atr = 300.0
        hard_sl = calculate_hard_stop(sw, atr, direction="LONG")
        expected_sl = 70000.0 - (1.5 * 300.0)  # 69550.0
        self.assertEqual(hard_sl, expected_sl)
        self.assertLess(hard_sl, sw)
        self.assertNotEqual(hard_sl, sw)

    def test_calculate_hard_stop_short(self):
        """Verify for SHORT: Hard SL = Structural Warning + (1.5 * ATR), strictly above structural warning."""
        sw = 60000.0
        atr = 250.0
        hard_sl = calculate_hard_stop(sw, atr, direction="SHORT")
        expected_sl = 60000.0 + (1.5 * 250.0)  # 60375.0
        self.assertEqual(hard_sl, expected_sl)
        self.assertGreater(hard_sl, sw)
        self.assertNotEqual(hard_sl, sw)

    def test_calculate_hard_stop_invalid_inputs(self):
        """Verify invalid ATR or structural warning values raise ValueError."""
        with self.assertRaises(ValueError):
            calculate_hard_stop(0.0, 300.0)
        with self.assertRaises(ValueError):
            calculate_hard_stop(70000.0, 0.0)
        with self.assertRaises(ValueError):
            calculate_hard_stop(70000.0, -10.0)

    def test_position_size_strictly_uses_hard_sl_not_structural_warning(self):
        """
        Verify that position sizing uses Risk Per Unit = |Entry - Hard SL| (e.g. $950),
        NOT |Entry - Structural Warning| (e.g. $500).
        """
        entry = 70500.0
        sw = 70000.0
        atr = 300.0
        cap = 1000.0
        risk_pct = 1.0

        hard_sl = calculate_hard_stop(sw, atr, direction="LONG")  # 69550.0
        self.assertEqual(hard_sl, 69550.0)

        # Risk budget = 1% of $1,000 = $10.00
        # True risk distance = 70,500 - 69,550 = $950.00
        # Position size = $10.00 / $950.00 = 0.0105263 BTC
        res = calculate_position_risk(capital=cap, risk_pct=risk_pct, entry_price=entry, stop_loss_price=hard_sl, direction="LONG")
        self.assertEqual(res.risk_usd, 10.0)
        self.assertAlmostEqual(res.position_size_coins, 10.0 / 950.0, places=6)
        # If someone mistakenly used SW ($70,000), size would be 10/500 = 0.02 BTC
        self.assertNotAlmostEqual(res.position_size_coins, 10.0 / (entry - sw), places=4)

    def test_tp_targets_strictly_use_hard_sl_risk(self):
        """
        Verify Take-Profit targets use Risk Per Unit = |Entry - Hard SL|:
        TP1 = Entry + 1.5 * 950 = 71,925
        TP2 = Entry + 2.0 * 950 = 72,400
        TP3 = Entry + 3.0 * 950 = 73,350
        """
        entry = 70500.0
        hard_sl = 69550.0
        risk_dist = entry - hard_sl  # 950.0

        res = calculate_position_risk(capital=1000.0, risk_pct=1.0, entry_price=entry, stop_loss_price=hard_sl, direction="LONG")
        self.assertEqual(res.tp1_price, 71925.0)
        self.assertEqual(res.tp2_price, 72400.0)
        self.assertEqual(res.tp3_price, 73350.0)

    def test_long_position_sizing_exact_math(self):
        res = calculate_position_risk(10000, 1.0, 60000, 58000)
        self.assertEqual(res.direction, "LONG")
        self.assertEqual(res.risk_usd, 100.0)
        self.assertAlmostEqual(res.price_risk_pct, 3.333, places=2)
        self.assertAlmostEqual(res.position_size_coins, 0.05, places=4)
        self.assertAlmostEqual(res.position_value_usd, 3000.0, places=2)
        self.assertAlmostEqual(res.effective_leverage, 0.3, places=2)
        self.assertEqual(res.tp1_price, 63000.0)
        self.assertEqual(res.tp2_price, 64000.0)
        self.assertEqual(res.tp3_price, 66000.0)
        self.assertEqual(len(res.warnings), 0)

    def test_short_position_sizing_exact_math(self):
        res = calculate_position_risk(5000, 2.0, 100, 105)
        self.assertEqual(res.direction, "SHORT")
        self.assertEqual(res.risk_usd, 100.0)
        self.assertEqual(res.position_size_coins, 20.0)
        self.assertEqual(res.position_value_usd, 2000.0)
        self.assertEqual(res.tp1_price, 92.5)
        self.assertEqual(res.tp2_price, 90.0)
        self.assertEqual(res.tp3_price, 85.0)

    def test_high_risk_and_leverage_warnings(self):
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
        with self.assertRaises(ValueError):
            calculate_position_risk(1000, 1, 60000, 58000, direction="SHORT")  # Short with SL below entry


if __name__ == "__main__":
    unittest.main()
