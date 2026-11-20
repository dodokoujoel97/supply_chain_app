import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import comparison  # noqa: E402
import planning  # noqa: E402


def frame(rows):
    df = pd.DataFrame(rows, columns=["Date", "Item", "Quantité"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def stock(rows):
    return pd.DataFrame(rows, columns=["Item", "Stock"])


def merged_from(orders, forecast):
    return comparison.merge_orders_forecast(frame(orders), frame(forecast), "W-MON")


class ProjectStockTests(unittest.TestCase):
    def setUp(self):
        self.merged = merged_from(
            [("2026-08-03", "A", 120), ("2026-08-10", "A", 140), ("2026-08-17", "A", 130)],
            [("2026-08-03", "A", 150), ("2026-08-10", "A", 135), ("2026-08-17", "A", 125)],
        )

    def test_stock_is_decremented_period_after_period(self):
        out = planning.project_stock(self.merged, stock([("A", 200)]))
        self.assertEqual(out["Stock projeté"].tolist(), [80, -60, -190])

    def test_shortage_status_and_net_need(self):
        out = planning.project_stock(self.merged, stock([("A", 200)]))
        self.assertEqual(out["Statut couverture"].tolist(), [planning.STATUS_COVERED] + [planning.STATUS_SHORTAGE] * 2)
        self.assertEqual(out["Besoin net"].tolist(), [0, 60, 190])
        self.assertEqual(out["Lancer OF"].tolist(), ["Non", "Oui", "Oui"])

    def test_stock_exactly_zero_is_covered(self):
        out = planning.project_stock(self.merged, stock([("A", 390)]))
        self.assertEqual(out["Stock projeté"].iloc[-1], 0)
        self.assertEqual(out["Statut couverture"].iloc[-1], planning.STATUS_COVERED)

    def test_item_without_stock_row_is_treated_as_zero(self):
        out = planning.project_stock(self.merged, stock([("B", 999)]))
        self.assertEqual(out["Stock initial"].tolist(), [0, 0, 0])
        self.assertTrue((out["Statut couverture"] == planning.STATUS_SHORTAGE).all())

    def test_without_stock_file(self):
        out = planning.project_stock(self.merged, None)
        self.assertTrue(out["Stock projeté"].isna().all())
        self.assertTrue((out["Statut couverture"] == planning.STATUS_NO_STOCK).all())
        self.assertEqual(out["Lancer OF"].tolist(), ["Non", "Oui", "Oui"])  # réel > prévision seulement en S2, S3

    def test_input_is_not_modified(self):
        before = self.merged.copy()
        planning.project_stock(self.merged, stock([("A", 200)]))
        pd.testing.assert_frame_equal(self.merged, before)


class ValuationTests(unittest.TestCase):
    def setUp(self):
        merged = merged_from([("2026-08-03", "A", 100)], [("2026-08-03", "A", 110)])
        self.merged = planning.project_stock(merged, stock([("A", 40)]))

    def test_sales_value_and_gap(self):
        prices = pd.DataFrame({"Item": ["A"], "Prix vente": [10.0]})
        out = planning.add_valuation(self.merged, prices)
        self.assertEqual(out["CA réel"].iloc[0], 1000)
        self.assertEqual(out["CA prévision"].iloc[0], 1100)
        self.assertEqual(out["Écart CA"].iloc[0], 100)

    def test_shortage_is_not_a_negative_asset(self):
        prices = pd.DataFrame({"Item": ["A"], "Prix achat": [4.0]})
        out = planning.add_valuation(self.merged, prices)
        self.assertEqual(out["Stock projeté"].iloc[0], -60)
        self.assertEqual(out["Valeur stock projeté"].iloc[0], 0)
        self.assertEqual(out["Besoin net valorisé"].iloc[0], 240)

    def test_gap_ca_empty_without_forecast_line(self):
        merged = planning.project_stock(
            merged_from([("2026-08-03", "A", 100)], [("2026-08-10", "A", 50)]), None
        )
        prices = pd.DataFrame({"Item": ["A"], "Prix vente": [10.0]})
        out = planning.add_valuation(merged, prices)
        missing = out[out["Données"] == comparison.FORECAST_MISSING]
        self.assertTrue(missing["Écart CA"].isna().all())

    def test_no_prices_leaves_frame_unchanged(self):
        out = planning.add_valuation(self.merged, None)
        pd.testing.assert_frame_equal(out, self.merged)


class ClassificationTests(unittest.TestCase):
    def row(self, **kw):
        base = {"Statut couverture": planning.STATUS_COVERED, "Écart absolu total": 0,
                "Réel total": 100, "Prévision total": 100}
        base.update(kw)
        return pd.Series(base)

    def test_shortage_is_always_urgent(self):
        row = self.row(**{"Statut couverture": planning.STATUS_SHORTAGE})
        self.assertEqual(planning.classify_priority(row, 50, 80), planning.URGENT)

    def test_priority_follows_gap_thresholds(self):
        self.assertEqual(planning.classify_priority(self.row(**{"Écart absolu total": 90}), 50, 80), planning.HIGH)
        self.assertEqual(planning.classify_priority(self.row(**{"Écart absolu total": 80}), 50, 80), planning.HIGH)
        self.assertEqual(planning.classify_priority(self.row(**{"Écart absolu total": 60}), 50, 80), planning.MEDIUM)
        self.assertEqual(planning.classify_priority(self.row(**{"Écart absolu total": 10}), 50, 80), planning.LOW)

    def test_action_for_shortage(self):
        row = self.row(**{"Statut couverture": planning.STATUS_SHORTAGE})
        self.assertEqual(planning.classify_action(row), planning.ACTION_REPLENISH)

    def test_action_review_forecast_when_overshoot_above_10_percent(self):
        self.assertEqual(planning.classify_action(self.row(**{"Prévision total": 115})), planning.ACTION_REVIEW_FORECAST)
        self.assertEqual(planning.classify_action(self.row(**{"Prévision total": 110})), planning.ACTION_STANDARD)

    def test_action_check_stock_when_not_provided(self):
        row = self.row(**{"Statut couverture": planning.STATUS_NO_STOCK})
        self.assertEqual(planning.classify_action(row), planning.ACTION_CHECK_STOCK)

    def test_zero_actual_does_not_trigger_review(self):
        row = self.row(**{"Réel total": 0, "Prévision total": 50})
        self.assertEqual(planning.classify_action(row), planning.ACTION_STANDARD)

    def test_explain_gap_wording(self):
        base = {"Stock projeté": 12.0, "Action recommandée": "X", "Statut couverture": planning.STATUS_COVERED}
        over = pd.Series({**base, "Réel total": 100, "Prévision total": 130})
        under = pd.Series({**base, "Réel total": 130, "Prévision total": 100})
        equal = pd.Series({**base, "Réel total": 100, "Prévision total": 100})
        self.assertIn("sur-estime le besoin de 30", planning.explain_gap(over))
        self.assertIn("sous-estime le besoin de 30", planning.explain_gap(under))
        self.assertIn("alignés", planning.explain_gap(equal))
        short = pd.Series({**base, "Statut couverture": planning.STATUS_SHORTAGE, "Réel total": 1, "Prévision total": 1})
        self.assertIn("Rupture", planning.explain_gap(short))


class SummarizeAndRecommendTests(unittest.TestCase):
    def setUp(self):
        orders = [("2026-08-03", "A", 120), ("2026-08-10", "A", 140), ("2026-08-17", "A", 130),
                  ("2026-08-03", "B", 80), ("2026-08-10", "B", 75), ("2026-08-17", "B", 90)]
        forecast = [("2026-08-03", "A", 150), ("2026-08-10", "A", 135), ("2026-08-17", "A", 125),
                    ("2026-08-03", "B", 70), ("2026-08-10", "B", 85), ("2026-08-17", "B", 100)]
        merged = planning.project_stock(merged_from(orders, forecast), stock([("A", 1000), ("B", 60)]))
        self.merged = planning.add_valuation(merged, None)
        self.totals = planning.summarize_items(self.merged, True, False, False).set_index("Item")

    def test_totals(self):
        self.assertEqual(self.totals.loc["A", "Réel total"], 390)
        self.assertEqual(self.totals.loc["A", "Prévision total"], 410)
        self.assertEqual(self.totals.loc["A", "Écart absolu total"], 40)

    def test_priority_and_action(self):
        self.assertEqual(self.totals.loc["A", "Statut couverture"], planning.STATUS_COVERED)
        self.assertEqual(self.totals.loc["B", "Priorité"], planning.URGENT)
        self.assertEqual(self.totals.loc["B", "Action recommandée"], planning.ACTION_REPLENISH)

    def test_sorted_by_absolute_gap(self):
        ordered = planning.summarize_items(self.merged, True, False, False)
        self.assertEqual(ordered["Item"].tolist(), ["A", "B"])

    def test_recommended_need_equals_average_actual_with_volume_bias(self):
        totals = planning.summarize_items(self.merged, True, False, False)
        reco = planning.recommend_need(self.merged, totals).set_index("Item")
        self.assertAlmostEqual(reco.loc["A", "Besoin recommandé / période"], 390 / 3, delta=0.5)
        self.assertAlmostEqual(reco.loc["B", "Besoin recommandé / période"], 245 / 3, delta=0.5)

    def test_item_without_measurable_bias_falls_back_to_zero_bias(self):
        merged = planning.project_stock(merged_from([("2026-08-03", "A", 5)], [("2026-08-03", "B", 7)]), None)
        totals = planning.summarize_items(merged, False, False, False)
        reco = planning.recommend_need(merged, totals).set_index("Item")
        self.assertEqual(reco.loc["B", "Biais en volume %"], 0)
        self.assertEqual(reco.loc["B", "Besoin recommandé / période"], 7)


if __name__ == "__main__":
    unittest.main()
