"""Contrôles de qualité des données d'entrée.

Module volontairement indépendant de Streamlit : il ne fait que produire une liste
d'anomalies (``issue``) que l'interface se charge d'afficher. Aucune donnée n'est
modifiée ici : on signale, on ne corrige pas en silence.
"""

import pandas as pd

ERROR = "error"
WARNING = "warning"
INFO = "info"

_EMPTY_ITEMS = {"", "nan", "none", "null"}


def parse_dates(series, dayfirst=True):
    """Convertit une colonne en dates sans confondre jour et mois.

    `pd.to_datetime(..., dayfirst=True)` lit à tort « 2026-08-01 » comme le 8 janvier et
    rejette « 2026-08-15 ». Les dates ISO (AAAA-MM-JJ) sont donc toujours lues comme telles ;
    `dayfirst` ne s'applique qu'aux autres formats (ex. 15/08/2026).
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    text = series.astype(str).str.strip()
    is_iso = text.str.match(r"^\d{4}-\d{1,2}-\d{1,2}")
    iso_part = pd.to_datetime(text.where(is_iso), errors="coerce", format="mixed", dayfirst=False)
    other_part = pd.to_datetime(text.where(~is_iso), errors="coerce", format="mixed", dayfirst=dayfirst)
    return iso_part.fillna(other_part)


def issue(level, message):
    return {"level": level, "message": message}


def _examples(items, limit=5):
    items = sorted(str(i) for i in items)
    text = ", ".join(items[:limit])
    return text + (f" … (+{len(items) - limit})" if len(items) > limit else "")


def check_frame(df, label, qty_col="Quantité"):
    """Contrôles sur un fichier déjà chargé : négatifs, doublons, articles vides."""
    issues = []
    if df is None or df.empty:
        return issues

    if qty_col in df.columns:
        negatives = int((df[qty_col] < 0).sum())
        if negatives:
            issues.append(issue(
                WARNING,
                f"{label} : {negatives} ligne(s) avec une quantité négative (retours ?). "
                "Elles sont comptées telles quelles dans les totaux.",
            ))

    if "Date" in df.columns:
        subset = [c for c in ("Date", "Item", qty_col) if c in df.columns]
        duplicates = int(df.duplicated(subset=subset).sum())
        if duplicates:
            issues.append(issue(
                WARNING,
                f"{label} : {duplicates} ligne(s) strictement identiques (même date, article et quantité). "
                "Doublon d'import possible : elles sont comptées plusieurs fois.",
            ))
    elif "Item" in df.columns:
        duplicated_items = df.loc[df.duplicated(subset=["Item"], keep=False), "Item"].unique()
        if len(duplicated_items):
            issues.append(issue(
                WARNING,
                f"{label} : {len(duplicated_items)} article(s) présents sur plusieurs lignes "
                f"({_examples(duplicated_items)}). Les valeurs sont additionnées.",
            ))

    if "Item" in df.columns:
        empty = int(df["Item"].astype(str).str.strip().str.lower().isin(_EMPTY_ITEMS).sum())
        if empty:
            issues.append(issue(WARNING, f"{label} : {empty} ligne(s) sans identifiant d'article."))

    return issues


def check_multi_source(df, role, qty_col, source_col="_source"):
    """Contrôles sur des fichiers concaténés : même contenu importé deux fois, chevauchements.

    `df` doit contenir une colonne `source_col` avec le nom du fichier d'origine de chaque ligne.
    """
    issues = []
    if df is None or df.empty or source_col not in df.columns or df[source_col].nunique() < 2:
        return issues

    key = [c for c in ("Date", "Item") if c in df.columns]
    cols = key + [qty_col]

    signatures = {}
    for source, part in df.groupby(source_col):
        ordered = part[cols].sort_values(cols).reset_index(drop=True)
        signature = (len(ordered), int(pd.util.hash_pandas_object(ordered, index=False).sum()))
        signatures.setdefault(signature, []).append(str(source))
    identical_groups = [set(names) for names in signatures.values() if len(names) > 1]
    for names in identical_groups:
        issues.append(issue(
            WARNING,
            f"{role} : les fichiers {', '.join(sorted(names))} ont un contenu identique. "
            "Doublon d'import probable : les valeurs sont comptées plusieurs fois.",
        ))

    sources_per_key = df.groupby(key)[source_col].agg(lambda s: frozenset(map(str, s)))
    overlapping = sources_per_key[sources_per_key.map(len) > 1]
    overlapping = overlapping[~overlapping.map(lambda s: any(s <= g for g in identical_groups))]
    if len(overlapping):
        files = sorted(set().union(*overlapping.tolist()))
        what = "date/article" if "Date" in key else "article"
        issues.append(issue(
            WARNING,
            f"{role} : {len(overlapping)} combinaison(s) {what} présentes dans plusieurs fichiers "
            f"({_examples(files)}). Les valeurs sont additionnées : vérifie qu'il ne s'agit pas "
            "du même lot importé deux fois.",
        ))
    return issues


def check_price_conflicts(df):
    """Articles dont le prix diffère selon les lignes ou les fichiers (la moyenne sera utilisée)."""
    issues = []
    if df is None or df.empty:
        return issues
    for col in ("Prix vente", "Prix achat"):
        if col not in df.columns:
            continue
        distinct = df.groupby("Item")[col].nunique(dropna=True)
        conflicts = distinct[distinct > 1].index
        if len(conflicts):
            issues.append(issue(
                WARNING,
                f"Prix : {len(conflicts)} article(s) ont un « {col} » différent selon les lignes ou les "
                f"fichiers ({_examples(conflicts)}). C'est la moyenne qui est utilisée.",
            ))
    return issues


def _unmatched(source_items, other_items):
    """Articles de `source_items` absents de `other_items`, avec un indice si seule la casse diffère."""
    missing = set(source_items) - set(other_items)
    other_folded = {str(i).strip().casefold() for i in other_items}
    case_only = {i for i in missing if str(i).strip().casefold() in other_folded}
    return missing, case_only


def _compare(issues, level, name_a, items_a, name_b, items_b, consequence):
    missing, case_only = _unmatched(items_a, items_b)
    if not missing:
        return
    message = f"{len(missing)} article(s) présents dans {name_a} mais absents {name_b} ({_examples(missing)}). {consequence}"
    if case_only:
        message += f" Différence de casse ou d'espaces probable pour : {_examples(case_only)}."
    issues.append(issue(level, message))


def check_consistency(orders, forecast, stock=None, prices=None, receipts=None, params=None):
    """Contrôles croisés entre commandes, prévisionnel, stock, prix, réceptions et paramètres."""
    issues = []
    if orders is None or forecast is None or orders.empty or forecast.empty:
        return issues

    order_items = set(orders["Item"])
    forecast_items = set(forecast["Item"])

    _compare(issues, WARNING, "les commandes", order_items, "du prévisionnel", forecast_items,
             "Leur prévision est comptée à 0.")
    _compare(issues, WARNING, "le prévisionnel", forecast_items, "des commandes", order_items,
             "Leur réel est compté à 0.")

    if stock is not None and not stock.empty:
        _compare(issues, WARNING, "les commandes", order_items, "du fichier de stock", set(stock["Item"]),
                 "Leur stock est compté à 0 : ruptures artificielles possibles.")

    if prices is not None and not prices.empty:
        _compare(issues, WARNING, "les commandes", order_items, "du fichier de prix", set(prices["Item"]),
                 "Leur chiffre d'affaires et leur valeur de stock sont sous-estimés.")

    demand_items = order_items | forecast_items
    if receipts is not None and not receipts.empty:
        receipt_items = set(receipts["Item"])
        if stock is not None and not stock.empty:
            # Seuls les articles qui ont une demande comptent : les autres sont signalés plus bas comme ignorés.
            _compare(issues, WARNING, "les réceptions", receipt_items & demand_items, "du fichier de stock",
                     set(stock["Item"]), "Leur stock initial est compté à 0.")
        _compare(issues, INFO, "les réceptions", receipt_items, "des commandes et du prévisionnel", demand_items,
                 "Ces réceptions sont ignorées (aucune demande à couvrir).")
    if params is not None and not params.empty:
        _compare(issues, INFO, "le fichier de paramètres", set(params["Item"]), "des commandes et du prévisionnel",
                 demand_items, "Ces paramètres sont ignorés.")

    order_dates, forecast_dates = orders["Date"], forecast["Date"]
    if order_dates.max() < forecast_dates.min() or forecast_dates.max() < order_dates.min():
        issues.append(issue(
            ERROR,
            "Les commandes et le prévisionnel n'ont aucune période en commun "
            f"(commandes : {order_dates.min():%d/%m/%Y} → {order_dates.max():%d/%m/%Y}, "
            f"prévisionnel : {forecast_dates.min():%d/%m/%Y} → {forecast_dates.max():%d/%m/%Y}). "
            "Vérifie le format de date dans la barre latérale.",
        ))

    return issues


def summarize(issues):
    """Retourne (nb erreurs, nb alertes)."""
    errors = sum(1 for i in issues if i["level"] == ERROR)
    warnings = sum(1 for i in issues if i["level"] == WARNING)
    return errors, warnings
