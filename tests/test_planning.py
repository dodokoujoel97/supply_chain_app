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


class ReceiptsTests(unittest.TestCase):
    """Réceptions attendues : le stock projeté = initial + réceptions cumulées − demande cumulée."""

    def setUp(self):
        # Demande réelle de 100 par semaine pendant 3 semaines, stock initial 150.
        self.merged = merged_from(
            [("2026-08-03", "A", 100), ("2026-08-10", "A", 100), ("2026-08-17", "A", 100)],
            [("2026-08-03", "A", 100), ("2026-08-10", "A", 100), ("2026-08-17", "A", 100)],
        )

    def project(self, receipts):
        return planning.project_stock(self.merged, stock([("A", 150)]), frame(receipts) if receipts else None, freq="W-MON")

    def test_without_receipts_nothing_changes(self):
        out = self.project(None)
        self.assertNotIn("Réceptions cumulées", out.columns)
        self.assertEqual(out["Stock projeté"].tolist(), [50, -50, -150])

    def test_receipt_cancels_a_shortage(self):
        out = self.project([("2026-08-10", "A", 200)])  # reçue la semaine 2
        self.assertEqual(out["Réceptions cumulées"].tolist(), [0, 200, 200])
        self.assertEqual(out["Stock projeté"].tolist(), [50, 150, 50])
        self.assertTrue((out["Statut couverture"] == planning.STATUS_COVERED).all())

    def test_receipt_before_first_period_counts_from_the_start(self):
        out = self.project([("2026-07-01", "A", 60)])
        self.assertEqual(out["Réceptions cumulées"].tolist(), [60, 60, 60])

    def test_receipt_in_a_period_without_demand_is_kept_for_later_periods(self):
        merged = merged_from([("2026-08-03", "A", 100), ("2026-08-24", "A", 100)],
                             [("2026-08-03", "A", 100), ("2026-08-24", "A", 100)])
        out = planning.project_stock(merged, stock([("A", 0)]), frame([("2026-08-12", "A", 250)]), freq="W-MON")
        self.assertEqual(out["Réceptions cumulées"].tolist(), [0, 250])
        self.assertEqual(out["Stock projeté"].tolist(), [-100, 50])

    def test_receipts_are_per_item(self):
        merged = merged_from([("2026-08-03", "A", 10), ("2026-08-03", "B", 10)],
                              [("2026-08-03", "A", 10), ("2026-08-03", "B", 10)])
        out = planning.project_stock(merged, stock([("A", 0), ("B", 0)]), frame([("2026-08-03", "B", 50)]), freq="W-MON")
        by_item = out.set_index("Item")["Stock projeté"]
        self.assertEqual(by_item["A"], -10)
        self.assertEqual(by_item["B"], 40)

    def test_receipts_ignored_without_stock_file(self):
        out = planning.project_stock(self.merged, None, frame([("2026-08-10", "A", 200)]), freq="W-MON")
        self.assertTrue((out["Statut couverture"] == planning.STATUS_NO_STOCK).all())

    def test_summary_keeps_the_worst_status_over_the_horizon(self):
        # Rupture en semaine 2 (−50), rattrapée en semaine 3 par une grosse réception :
        # la dernière période est « Couvert », mais l'article a bien eu une rupture.
        out = self.project([("2026-08-17", "A", 500)])
        self.assertEqual(out["Statut couverture"].tolist(),
                         [planning.STATUS_COVERED, planning.STATUS_SHORTAGE, planning.STATUS_COVERED])
        totals = planning.summarize_items(out, True, False, False).iloc[0]
        self.assertEqual(totals["Statut couverture"], planning.STATUS_SHORTAGE)
        self.assertEqual(totals["Priorité"], planning.URGENT)
        self.assertEqual(totals["Stock minimum projeté"], -50)
        self.assertEqual(totals["Stock projeté"], 350)  # fin de période, lui, est positif
        self.assertEqual(totals["Première date à risque"], pd.Timestamp("2026-08-10"))


class SafetyStockAndLeadTimeTests(unittest.TestCase):
    def setUp(self):
        self.merged = merged_from(
            [("2026-08-03", "A", 100), ("2026-08-10", "A", 100), ("2026-08-17", "A", 100)],
            [("2026-08-03", "A", 100), ("2026-08-10", "A", 100), ("2026-08-17", "A", 100)],
        )
        self.stock = stock([("A", 250)])  # stock projeté : 150, 50, -50

    def params(self, lead=None, safety=None):
        data = {"Item": ["A"]}
        if lead is not None:
            data[planning.LEAD_TIME] = [lead]
        if safety is not None:
            data[planning.SAFETY_STOCK] = [safety]
        return pd.DataFrame(data)

    def test_without_safety_stock_threshold_is_zero(self):
        out = planning.project_stock(self.merged, self.stock)
        self.assertEqual(out["Statut couverture"].tolist(),
                         [planning.STATUS_COVERED, planning.STATUS_COVERED, planning.STATUS_SHORTAGE])
        self.assertNotIn(planning.SAFETY_STOCK, out.columns)

    def test_below_safety_stock_status_and_need(self):
        out = planning.project_stock(self.merged, self.stock, params_df=self.params(safety=80))
        self.assertEqual(out["Statut couverture"].tolist(),
                         [planning.STATUS_COVERED, planning.STATUS_BELOW_SAFETY, planning.STATUS_SHORTAGE])
        # besoin = quantité pour revenir au stock de sécurité
        self.assertEqual(out["Besoin net"].tolist(), [0, 30, 130])

    def test_stock_equal_to_safety_stock_is_covered(self):
        out = planning.project_stock(self.merged, self.stock, params_df=self.params(safety=50))
        self.assertEqual(out["Statut couverture"].iloc[1], planning.STATUS_COVERED)

    def test_below_safety_stock_is_high_priority_with_replenish_action(self):
        out = planning.project_stock(self.merged, stock([("A", 400)]), params_df=self.params(safety=80))
        # stock projeté : 300, 200, 100 -> jamais sous 80 : couvert
        self.assertEqual(planning.summarize_items(out, True, False, False).iloc[0]["Statut couverture"],
                         planning.STATUS_COVERED)
        out = planning.project_stock(self.merged, stock([("A", 330)]), params_df=self.params(safety=80))
        # stock projeté : 230, 130, 30 -> sous 80 en dernière période, sans rupture
        row = planning.summarize_items(out, True, False, False).iloc[0]
        self.assertEqual(row["Statut couverture"], planning.STATUS_BELOW_SAFETY)
        self.assertEqual(row["Priorité"], planning.HIGH)
        self.assertEqual(row["Action recommandée"], planning.ACTION_REPLENISH)
        self.assertIn("stock de sécurité", row["Justification"])

    def test_order_deadline_is_first_risk_date_minus_lead_time(self):
        out = planning.project_stock(self.merged, self.stock)
        row = planning.summarize_items(out, True, False, False, self.params(lead=7)).iloc[0]
        self.assertEqual(row["Première date à risque"], pd.Timestamp("2026-08-17"))
        self.assertEqual(row["Date limite de commande"], pd.Timestamp("2026-08-10"))

    def test_deadline_days_left_and_late_order_wording(self):
        out = planning.project_stock(self.merged, self.stock)
        late = planning.summarize_items(out, True, False, False, self.params(lead=7), pd.Timestamp("2026-08-15")).iloc[0]
        self.assertEqual(late["Jours avant date limite"], -5)
        self.assertIn("Délai dépassé de 5 j", late["Justification"])
        self.assertIn("10/08/2026", late["Justification"])
        in_time = planning.summarize_items(out, True, False, False, self.params(lead=7), pd.Timestamp("2026-08-01")).iloc[0]
        self.assertEqual(in_time["Jours avant date limite"], 9)
        self.assertNotIn("dépassé", in_time["Justification"])

    def test_article_without_risk_has_no_deadline(self):
        out = planning.project_stock(self.merged, stock([("A", 5000)]))
        row = planning.summarize_items(out, True, False, False, self.params(lead=7)).iloc[0]
        self.assertTrue(pd.isna(row["Première date à risque"]))
        self.assertTrue(pd.isna(row["Date limite de commande"]))

    def test_article_missing_from_params_has_no_deadline(self):
        out = planning.project_stock(self.merged, self.stock)
        other = pd.DataFrame({"Item": ["Z"], planning.LEAD_TIME: [3]})
        row = planning.summarize_items(out, True, False, False, other).iloc[0]
        self.assertTrue(pd.isna(row["Date limite de commande"]))

    def test_params_without_lead_time_column(self):
        out = planning.project_stock(self.merged, self.stock, params_df=self.params(safety=10))
        row = planning.summarize_items(out, True, False, False, self.params(safety=10)).iloc[0]
        self.assertNotIn("Date limite de commande", row.index)


if __name__ == "__main__":
    unittest.main()
