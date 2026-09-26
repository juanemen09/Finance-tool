import unittest

from ai_trading_lab.sizing import auto_notional, loss_fraction


class AutoNotional(unittest.TestCase):
    def test_link_of_2026_09_26_shrinks_to_fit_the_cap(self):
        # Zona 13.860-14.069, stop 12.379: con 7 USDT la base estimaba 0,8619 y exigía el "autorizo".
        self.assertAlmostEqual(7 * loss_fraction(14.069, 12.379), 0.8619, places=4)
        s = auto_notional(14.069, 12.379)
        self.assertTrue(s["auto_eligible"])
        self.assertLess(s["notional_usdt"], 7)
        self.assertLessEqual(s["estimated_max_loss_usdt"], 0.8)
        self.assertGreaterEqual(s["notional_usdt"] * 12.379 / 14.069, 5.0, "la venta del stop debe ser operable")

    def test_tight_stop_keeps_the_maximum(self):
        s = auto_notional(100, 97)
        self.assertEqual(s["notional_usdt"], 7)
        self.assertTrue(s["auto_eligible"])

    def test_very_wide_stop_needs_the_user(self):
        # Stop a -25 %: para no perder más de 0,8 habría que comprar ~3,1 USDT, por debajo del mínimo operable (6,8).
        s = auto_notional(100, 75)
        self.assertFalse(s["auto_eligible"])
        self.assertEqual(s["notional_usdt"], s["min_operable_usdt"])
        self.assertGreater(s["estimated_max_loss_usdt"], 0.8)

    def test_no_valid_size(self):
        s = auto_notional(100, 50)  # el mínimo operable (10,2 USDT) supera el máximo de 7
        self.assertIsNone(s["notional_usdt"])
        self.assertFalse(s["auto_eligible"])

    def test_bad_levels(self):
        with self.assertRaises(ValueError):
            auto_notional(100, 101)


if __name__ == "__main__":
    unittest.main()
