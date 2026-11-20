"""Rapprochement commandes réelles / prévisionnel (sans dépendance à Streamlit).

Règle sur les données absentes, qui évite de les confondre avec un vrai zéro :

- « Réel absent » : le prévisionnel existe mais aucune commande n'a été enregistrée pour
  cette période et cet article. Dans un carnet de commandes, c'est une demande nulle :
  la quantité réelle vaut 0 et la ligne reste comptée dans les indicateurs d'erreur.
- « Prévision absente » : des commandes existent mais le prévisionnel ne contient aucune
  ligne. On ne peut pas parler d'erreur de prévision : la ligne est marquée, son écart est
  laissé vide (NaN) et elle est exclue du WAPE et du biais.
"""

import numpy as np
import pandas as pd

COMPLETE = "Complet"
REAL_MISSING = "Réel absent"
FORECAST_MISSING = "Prévision absente"


def merge_orders_forecast(orders_df, forecast_df, freq):
    """Agrège commandes et prévisions par période et article, puis calcule les écarts."""
    orders_summary = (
        orders_df.groupby([pd.Grouper(key="Date", freq=freq), "Item"])["Quantité"]
        .sum().reset_index().rename(columns={"Quantité": "Réel"})
    )
    forecast_summary = (
        forecast_df.groupby([pd.Grouper(key="Date", freq=freq), "Item"])["Quantité"]
        .sum().reset_index().rename(columns={"Quantité": "Prévision"})
    )
    merged = pd.merge(orders_summary, forecast_summary, on=["Date", "Item"], how="outer")
    merged["Données"] = np.select(
        [merged["Prévision"].isna(), merged["Réel"].isna()],
        [FORECAST_MISSING, REAL_MISSING],
        default=COMPLETE,
    )
    merged = merged.fillna({"Réel": 0, "Prévision": 0})
    merged = merged.sort_values(["Item", "Date"]).reset_index(drop=True)

    forecast_missing = merged["Données"] == FORECAST_MISSING
    merged["Écart"] = (merged["Prévision"] - merged["Réel"]).where(~forecast_missing)
    merged["Écart %"] = np.where(
        (merged["Réel"] != 0) & ~forecast_missing, merged["Écart"] / merged["Réel"] * 100, np.nan
    )
    return merged


def accuracy_rows(merged):
    """Lignes sur lesquelles on mesure la précision du prévisionnel (hors « Prévision absente »)."""
    return merged[merged["Données"] != FORECAST_MISSING]


def accuracy_by_item(merged):
    """WAPE (%) et biais en volume (%) par article, calculés sur les lignes mesurables."""
    rows = accuracy_rows(merged)
    if rows.empty:
        return pd.DataFrame(columns=["Item", "WAPE (%)", "Biais (%)"])
    grouped = rows.groupby("Item").agg(
        actual=("Réel", "sum"),
        forecast=("Prévision", "sum"),
        abs_gap=("Écart", lambda s: s.abs().sum()),
    )
    valid = grouped["actual"] > 0
    grouped["WAPE (%)"] = np.where(valid, (grouped["abs_gap"] / grouped["actual"] * 100).round(1), np.nan)
    grouped["Biais (%)"] = np.where(
        valid, ((grouped["forecast"] - grouped["actual"]) / grouped["actual"] * 100).round(1), np.nan
    )
    return grouped.reset_index()[["Item", "WAPE (%)", "Biais (%)"]]


def data_gap_counts(merged):
    """Nombre de lignes « Réel absent » et « Prévision absente »."""
    return (
        int((merged["Données"] == REAL_MISSING).sum()),
        int((merged["Données"] == FORECAST_MISSING).sum()),
    )
