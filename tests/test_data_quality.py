import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_quality as dq  # noqa: E402


def frame(rows, cols=("Date", "Item", "Quantité")):
    df = pd.DataFrame(rows, columns=list(cols))
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
    return df


def messages(issues):
    return " | ".join(i["message"] for i in issues)


class CheckFrameTests(unittest.TestCase):
    def test_clean_frame_has_no_issue(self):
        df = frame([("2026-08-01", "A", 10), ("2026-08-08", "A", 12)])
        self.assertEqual(dq.check_frame(df, "f.csv"), [])

    def test_negative_quantity_is_reported(self):
        df = frame([("2026-08-01", "A", -5), ("2026-08-08", "A", 12)])
        self.assertIn("négative", messages(dq.check_frame(df, "f.csv")))

    def test_exact_duplicates_are_reported(self):
        df = frame([("2026-08-01", "A", 10), ("2026-08-01", "A", 10)])
        issues = dq.check_frame(df, "f.csv")
        self.assertIn("1 ligne(s) strictement identiques", messages(issues))

    def test_same_date_item_different_quantity_is_not_duplicate(self):
        df = frame([("2026-08-01", "A", 10), ("2026-08-01", "A", 11)])
        self.assertEqual(dq.check_frame(df, "f.csv"), [])

    def test_stock_with_repeated_item_is_reported(self):
        df = frame([("A", 10), ("A", 5), ("B", 1)], cols=("Item", "Stock"))
        self.assertIn("plusieurs lignes", messages(dq.check_frame(df, "s.csv", "Stock")))

    def test_empty_item_is_reported(self):
        df = frame([("2026-08-01", "", 10), ("2026-08-01", "nan", 3)])
        self.assertIn("2 ligne(s) sans identifiant", messages(dq.check_frame(df, "f.csv")))


class CheckConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.orders = frame([("2026-08-01", "A", 10), ("2026-08-01", "B", 5)])
        self.forecast = frame([("2026-08-01", "A", 9), ("2026-08-01", "B", 6)])

    def test_consistent_data_has_no_issue(self):
        stock = frame([("A", 5), ("B", 5)], cols=("Item", "Stock"))
        self.assertEqual(dq.check_consistency(self.orders, self.forecast, stock), [])

    def test_item_missing_from_stock(self):
        stock = frame([("A", 5)], cols=("Item", "Stock"))
        text = messages(dq.check_consistency(self.orders, self.forecast, stock))
        self.assertIn("absents du fichier de stock", text)
        self.assertIn("B", text)

    def test_item_missing_from_forecast(self):
        forecast = frame([("2026-08-01", "A", 9)])
        text = messages(dq.check_consistency(self.orders, forecast))
        self.assertIn("absents du prévisionnel", text)

    def test_case_difference_hint(self):
        forecast = frame([("2026-08-01", "a", 9), ("2026-08-01", "B", 6)])
        text = messages(dq.check_consistency(self.orders, forecast))
        self.assertIn("casse", text)

    def test_no_common_period_is_an_error(self):
        forecast = frame([("2027-01-01", "A", 9), ("2027-01-01", "B", 6)])
        issues = dq.check_consistency(self.orders, forecast)
        self.assertEqual(dq.summarize(issues), (1, 0))

    def test_item_without_price(self):
        prices = pd.DataFrame({"Item": ["A"], "Prix vente": [10.0]})
        text = messages(dq.check_consistency(self.orders, self.forecast, None, prices))
        self.assertIn("fichier de prix", text)

    def test_none_inputs_are_safe(self):
        self.assertEqual(dq.check_consistency(None, None), [])


if __name__ == "__main__":
    unittest.main()
