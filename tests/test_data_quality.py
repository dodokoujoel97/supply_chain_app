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


class ParseDatesTests(unittest.TestCase):
    def test_iso_dates_are_not_swapped_when_dayfirst(self):
        parsed = dq.parse_dates(pd.Series(["2026-08-01", "2026-08-15"]), dayfirst=True)
        self.assertEqual(parsed.tolist(), [pd.Timestamp("2026-08-01"), pd.Timestamp("2026-08-15")])

    def test_french_format_with_dayfirst(self):
        parsed = dq.parse_dates(pd.Series(["01/08/2026", "15/08/2026"]), dayfirst=True)
        self.assertEqual(parsed.tolist(), [pd.Timestamp("2026-08-01"), pd.Timestamp("2026-08-15")])

    def test_us_format_without_dayfirst(self):
        parsed = dq.parse_dates(pd.Series(["08/01/2026"]), dayfirst=False)
        self.assertEqual(parsed.tolist(), [pd.Timestamp("2026-08-01")])

    def test_mixed_formats_and_invalid_values(self):
        parsed = dq.parse_dates(pd.Series(["2026-08-01", "15/08/2026", "n/a", None]), dayfirst=True)
        self.assertEqual(parsed.iloc[:2].tolist(), [pd.Timestamp("2026-08-01"), pd.Timestamp("2026-08-15")])
        self.assertTrue(parsed.iloc[2:].isna().all())

    def test_existing_datetime_column_is_kept(self):
        series = pd.Series(pd.to_datetime(["2026-08-01"]))
        self.assertEqual(dq.parse_dates(series, True).tolist(), series.tolist())


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


def tagged(rows, source, cols=("Date", "Item", "Quantité")):
    df = frame(rows, cols)
    df["_source"] = source
    return df


class MultiSourceTests(unittest.TestCase):
    def test_single_source_has_no_issue(self):
        df = tagged([("2026-08-01", "A", 10)], "a.csv")
        self.assertEqual(dq.check_multi_source(df, "Commandes", "Quantité"), [])

    def test_identical_files_are_reported_once(self):
        rows = [("2026-08-01", "A", 10), ("2026-08-08", "A", 12)]
        df = pd.concat([tagged(rows, "mars.csv"), tagged(rows, "mars_copie.csv")], ignore_index=True)
        issues = dq.check_multi_source(df, "Commandes", "Quantité")
        self.assertEqual(len(issues), 1)
        self.assertIn("contenu identique", issues[0]["message"])
        self.assertIn("mars_copie.csv", issues[0]["message"])

    def test_overlapping_periods_are_reported(self):
        a = tagged([("2026-08-01", "A", 10), ("2026-08-08", "A", 12)], "a.csv")
        b = tagged([("2026-08-08", "A", 15), ("2026-08-15", "A", 9)], "b.csv")
        issues = dq.check_multi_source(pd.concat([a, b], ignore_index=True), "Commandes", "Quantité")
        self.assertEqual(len(issues), 1)
        self.assertIn("1 combinaison(s) date/article", issues[0]["message"])

    def test_distinct_periods_have_no_issue(self):
        a = tagged([("2026-08-01", "A", 10)], "a.csv")
        b = tagged([("2026-08-08", "A", 15)], "b.csv")
        self.assertEqual(dq.check_multi_source(pd.concat([a, b], ignore_index=True), "Commandes", "Quantité"), [])

    def test_stock_same_item_in_two_files(self):
        a = tagged([("A", 10)], "s1.csv", cols=("Item", "Stock")).drop(columns=[])
        b = tagged([("A", 7)], "s2.csv", cols=("Item", "Stock"))
        issues = dq.check_multi_source(pd.concat([a, b], ignore_index=True), "Stock", "Stock")
        self.assertIn("article", issues[0]["message"])


class PriceConflictTests(unittest.TestCase):
    def test_conflicting_prices(self):
        df = pd.DataFrame({"Item": ["A", "A", "B"], "Prix vente": [10.0, 12.0, 5.0]})
        issues = dq.check_price_conflicts(df)
        self.assertEqual(len(issues), 1)
        self.assertIn("A", issues[0]["message"])

    def test_same_price_twice_is_fine(self):
        df = pd.DataFrame({"Item": ["A", "A"], "Prix vente": [10.0, 10.0], "Prix achat": [4.0, 4.0]})
        self.assertEqual(dq.check_price_conflicts(df), [])


if __name__ == "__main__":
    unittest.main()
