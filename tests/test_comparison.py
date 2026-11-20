import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import comparison  # noqa: E402


def frame(rows):
    df = pd.DataFrame(rows, columns=["Date", "Item", "Quantité"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df


class MergeTests(unittest.TestCase):
    def test_complete_rows(self):
        orders = frame([("2026-08-03", "A", 100)])
        forecast = frame([("2026-08-03", "A", 110)])
        merged = comparison.merge_orders_forecast(orders, forecast, "W-MON")
        row = merged.iloc[0]
        self.assertEqual(row["Données"], comparison.COMPLETE)
        self.assertEqual(row["Écart"], 10)
        self.assertAlmostEqual(row["Écart %"], 10.0)

    def test_missing_orders_counts_as_zero_demand(self):
        orders = frame([("2026-08-03", "A", 100)])
        forecast = frame([("2026-08-03", "A", 100), ("2026-08-10", "A", 50)])
        merged = comparison.merge_orders_forecast(orders, forecast, "W-MON")
        row = merged[merged["Données"] == comparison.REAL_MISSING].iloc[0]
        self.assertEqual(row["Réel"], 0)
        self.assertEqual(row["Écart"], 50)  # surestimation réelle, conservée
        self.assertTrue(pd.isna(row["Écart %"]))  # division par un réel nul

    def test_missing_forecast_is_flagged_and_gap_left_empty(self):
        orders = frame([("2026-08-03", "A", 100), ("2026-08-10", "A", 80)])
        forecast = frame([("2026-08-03", "A", 100)])
        merged = comparison.merge_orders_forecast(orders, forecast, "W-MON")
        row = merged[merged["Données"] == comparison.FORECAST_MISSING].iloc[0]
        self.assertEqual(row["Prévision"], 0)
        self.assertTrue(pd.isna(row["Écart"]))
        self.assertTrue(pd.isna(row["Écart %"]))

    def test_gap_counts(self):
        orders = frame([("2026-08-03", "A", 1), ("2026-08-10", "B", 2)])
        forecast = frame([("2026-08-03", "A", 1), ("2026-08-17", "A", 3)])
        merged = comparison.merge_orders_forecast(orders, forecast, "W-MON")
        self.assertEqual(comparison.data_gap_counts(merged), (1, 1))


class AccuracyTests(unittest.TestCase):
    def test_missing_forecast_rows_are_excluded_from_wape(self):
        orders = frame([("2026-08-03", "A", 100), ("2026-08-10", "A", 500)])
        forecast = frame([("2026-08-03", "A", 110)])
        merged = comparison.merge_orders_forecast(orders, forecast, "W-MON")
        acc = comparison.accuracy_by_item(merged).iloc[0]
        self.assertAlmostEqual(acc["WAPE (%)"], 10.0)  # la semaine sans prévision n'entre pas
        self.assertAlmostEqual(acc["Biais (%)"], 10.0)

    def test_missing_orders_rows_stay_in_wape(self):
        orders = frame([("2026-08-03", "A", 100)])
        forecast = frame([("2026-08-03", "A", 100), ("2026-08-10", "A", 50)])
        merged = comparison.merge_orders_forecast(orders, forecast, "W-MON")
        acc = comparison.accuracy_by_item(merged).iloc[0]
        self.assertAlmostEqual(acc["WAPE (%)"], 50.0)  # 50 d'écart sur 100 de réel
        self.assertAlmostEqual(acc["Biais (%)"], 50.0)

    def test_item_without_actual_has_no_wape(self):
        orders = frame([("2026-08-03", "A", 10)])
        forecast = frame([("2026-08-03", "A", 10), ("2026-08-03", "B", 5)])
        merged = comparison.merge_orders_forecast(orders, forecast, "W-MON")
        acc = comparison.accuracy_by_item(merged).set_index("Item")
        self.assertTrue(pd.isna(acc.loc["B", "WAPE (%)"]))

    def test_empty_accuracy_rows(self):
        orders = frame([("2026-08-03", "A", 10)])
        forecast = frame([("2027-01-04", "B", 5)])
        merged = comparison.merge_orders_forecast(orders, forecast, "W-MON")
        # A sans prévision, B sans commande : seule la ligne B est mesurable (réel 0 → NaN)
        acc = comparison.accuracy_by_item(merged).set_index("Item")
        self.assertNotIn("A", acc.index)


if __name__ == "__main__":
    unittest.main()
