import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import metrics  # noqa: E402


class WapeTests(unittest.TestCase):
    def test_perfect_forecast(self):
        self.assertEqual(metrics.wape([10, 20], [10, 20]), 0.0)

    def test_weighted_by_volume(self):
        # |12-10| + |90-100| = 12 ; réel = 110
        self.assertAlmostEqual(metrics.wape([10, 100], [12, 90]), 12 / 110 * 100)

    def test_opposite_errors_do_not_cancel(self):
        self.assertAlmostEqual(metrics.wape([100, 100], [120, 80]), 20.0)

    def test_small_quantity_does_not_dominate(self):
        # 1 contre 3 = 200 % en ligne, mais seulement 2 unités sur 1001
        self.assertLess(metrics.wape([1, 1000], [3, 1000]), 1.0)

    def test_zero_actual_is_nan(self):
        self.assertTrue(math.isnan(metrics.wape([0, 0], [5, 5])))


class BiasTests(unittest.TestCase):
    def test_overestimation_is_positive(self):
        self.assertAlmostEqual(metrics.bias_volume([100], [110]), 10.0)

    def test_underestimation_is_negative(self):
        self.assertAlmostEqual(metrics.bias_volume([100], [90]), -10.0)

    def test_opposite_errors_cancel_in_bias(self):
        self.assertAlmostEqual(metrics.bias_volume([100, 100], [120, 80]), 0.0)

    def test_zero_actual_is_nan(self):
        self.assertTrue(math.isnan(metrics.bias_volume([0], [5])))

    def test_describe_bias(self):
        self.assertIn("surestime", metrics.describe_bias(8))
        self.assertIn("sous-estime", metrics.describe_bias(-8))
        self.assertIn("pas de biais", metrics.describe_bias(1))
        self.assertEqual(metrics.describe_bias(float("nan")), "non calculable")


if __name__ == "__main__":
    unittest.main()
