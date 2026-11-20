"""Couverture de stock, valorisation, priorités et besoin recommandé (sans dépendance à Streamlit).

Les fonctions prennent le tableau `merged` produit par `comparison.merge_orders_forecast`
et retournent de nouveaux tableaux : aucune ne modifie son entrée.
"""

import numpy as np
import pandas as pd

import comparison

URGENT, HIGH, MEDIUM, LOW = "Urgent", "Élevée", "Moyenne", "Faible"
STATUS_COVERED = "Couvert"
STATUS_SHORTAGE = "Rupture prévue"
STATUS_NO_STOCK = "Stock non fourni"

ACTION_REPLENISH = "Lancer OF / réapprovisionner"
ACTION_REVIEW_FORECAST = "Réviser prévision / ajuster plan"
ACTION_CHECK_STOCK = "Vérifier le stock disponible"
ACTION_STANDARD = "Suivi standard"

# Au-delà de ce ratio prévision / réel, on recommande de réviser la prévision.
FORECAST_OVERSHOOT_RATIO = 1.1


def project_stock(merged, stock_df):
    """Projette le stock période après période : stock initial − demande réelle cumulée.

    Sans fichier de stock, le besoin net est la demande réelle de la période et la décision
    de lancer un OF repose sur la comparaison réel / prévision.
    """
    merged = merged.copy()
    if stock_df is not None:
        stock_initial = stock_df.groupby("Item")["Stock"].sum().reset_index().rename(columns={"Stock": "Stock initial"})
        merged = pd.merge(merged, stock_initial, on="Item", how="left").fillna({"Stock initial": 0})
        merged["Réel cumulé"] = merged.groupby("Item")["Réel"].cumsum()
        merged["Stock projeté"] = merged["Stock initial"] - merged["Réel cumulé"]
        merged["Besoin net"] = (-merged["Stock projeté"]).clip(lower=0)
        merged["Statut couverture"] = np.where(merged["Stock projeté"] >= 0, STATUS_COVERED, STATUS_SHORTAGE)
        merged["Lancer OF"] = np.where(merged["Besoin net"] > 0, "Oui", "Non")
    else:
        merged["Stock projeté"] = np.nan
        merged["Besoin net"] = merged["Réel"]
        merged["Statut couverture"] = STATUS_NO_STOCK
        merged["Lancer OF"] = np.where(merged["Réel"] > merged["Prévision"], "Oui", "Non")
    return merged


def add_valuation(merged, price_df):
    """Ajoute chiffre d'affaires et valeur de stock immobilisé si des prix sont fournis."""
    has_prix_vente = price_df is not None and "Prix vente" in price_df.columns
    has_prix_achat = price_df is not None and "Prix achat" in price_df.columns
    merged = merged.copy()

    if price_df is not None:
        merged = pd.merge(merged, price_df, on="Item", how="left")

    if has_prix_vente:
        merged["CA réel"] = merged["Réel"] * merged["Prix vente"]
        merged["CA prévision"] = merged["Prévision"] * merged["Prix vente"]
        # Sans ligne de prévision, l'écart de CA n'a pas de sens : on le laisse vide (comme l'écart en unités).
        merged["Écart CA"] = (merged["CA prévision"] - merged["CA réel"]).where(
            merged["Données"] != comparison.FORECAST_MISSING
        )

    if has_prix_achat:
        # Une rupture (stock projeté négatif) n'est pas un actif négatif : on plafonne à 0 pour la
        # valorisation, seule la partie de stock réellement immobilisée compte.
        merged["Valeur stock projeté"] = merged["Stock projeté"].clip(lower=0) * merged["Prix achat"]
        merged["Besoin net valorisé"] = merged["Besoin net"] * merged["Prix achat"]
    return merged


def classify_priority(row, q50, q75):
    if row["Statut couverture"] == STATUS_SHORTAGE:
        return URGENT
    if row["Écart absolu total"] >= q75:
        return HIGH
    if row["Écart absolu total"] >= q50:
        return MEDIUM
    return LOW


def classify_action(row):
    if row["Statut couverture"] == STATUS_SHORTAGE:
        return ACTION_REPLENISH
    if row["Réel total"] != 0 and row["Prévision total"] > row["Réel total"] * FORECAST_OVERSHOOT_RATIO:
        return ACTION_REVIEW_FORECAST
    if row["Statut couverture"] == STATUS_NO_STOCK:
        return ACTION_CHECK_STOCK
    return ACTION_STANDARD


def explain_gap(row):
    delta = row["Réel total"] - row["Prévision total"]
    cover = "non fournie" if pd.isna(row["Stock projeté"]) else f'{row["Stock projeté"]:.0f} unités projetées'
    action = row["Action recommandée"]
    if row["Statut couverture"] == STATUS_SHORTAGE:
        return (
            f"Rupture de stock projetée : la demande réelle cumulée dépasse le stock disponible "
            f"(couverture : {cover}). Action : {action}."
        )
    if row["Prévision total"] > row["Réel total"]:
        return (
            f"Le système sur-estime le besoin de {abs(delta):.0f} unités sur la période. "
            f"Couverture : {cover}. Action : {action}."
        )
    if row["Réel total"] > row["Prévision total"]:
        return (
            f"Le système sous-estime le besoin de {abs(delta):.0f} unités sur la période. "
            f"Couverture : {cover}. Action : {action}."
        )
    return f"Réel et prévision alignés sur la période. Couverture : {cover}. Action : {action}."


def summarize_items(merged, has_stock, has_prix_vente, has_prix_achat):
    """Totaux, précision, priorité et action par article (calculés sur les totaux, pas par période)."""
    item_totals = merged.groupby("Item", as_index=False).agg(
        **{
            "Réel total": ("Réel", "sum"),
            "Prévision total": ("Prévision", "sum"),
            "Écart absolu total": ("Écart", lambda s: s.abs().sum()),
        }
    )
    if has_stock:
        latest_cols = ["Item", "Stock projeté", "Statut couverture"]
        if has_prix_achat:
            latest_cols.append("Valeur stock projeté")
        latest_stock = merged.sort_values("Date").groupby("Item").tail(1)[latest_cols]
        item_totals = pd.merge(item_totals, latest_stock, on="Item", how="left")
    else:
        item_totals["Stock projeté"] = np.nan
        item_totals["Statut couverture"] = STATUS_NO_STOCK

    if has_prix_vente:
        ca_totals = merged.groupby("Item", as_index=False).agg(**{
            "CA réel total": ("CA réel", "sum"),
            "CA prévision total": ("CA prévision", "sum"),
            "Écart CA absolu total": ("Écart CA", lambda s: s.abs().sum()),
        })
        item_totals = pd.merge(item_totals, ca_totals, on="Item", how="left")

    # WAPE et biais en volume, calculés hors lignes « Prévision absente ».
    item_totals = pd.merge(item_totals, comparison.accuracy_by_item(merged), on="Item", how="left")

    q75 = item_totals["Écart absolu total"].quantile(0.75)
    q50 = item_totals["Écart absolu total"].quantile(0.50)
    item_totals["Priorité"] = item_totals.apply(lambda row: classify_priority(row, q50, q75), axis=1)
    item_totals["Action recommandée"] = item_totals.apply(classify_action, axis=1)
    item_totals["Justification"] = item_totals.apply(explain_gap, axis=1)
    return item_totals.sort_values("Écart absolu total", ascending=False).reset_index(drop=True)


def recommend_need(merged, item_totals):
    """Prévision moyenne par période corrigée du biais en volume du système."""
    n_periods = merged.groupby("Item")["Date"].nunique().reset_index().rename(columns={"Date": "Nb périodes"})
    item_reco = pd.merge(item_totals[["Item", "Prévision total", "Biais (%)"]], n_periods, on="Item", how="left")
    item_reco = item_reco.rename(columns={"Biais (%)": "Biais en volume %"})
    item_reco["Biais en volume %"] = item_reco["Biais en volume %"].fillna(0)
    item_reco["Prévision moyenne / période"] = (
        item_reco["Prévision total"] / item_reco["Nb périodes"].replace(0, np.nan)
    ).fillna(0)
    item_reco["Besoin recommandé / période"] = np.where(
        (1 + item_reco["Biais en volume %"] / 100) > 0,
        item_reco["Prévision moyenne / période"] / (1 + item_reco["Biais en volume %"] / 100),
        item_reco["Prévision moyenne / période"],
    ).round(0)
    return item_reco
