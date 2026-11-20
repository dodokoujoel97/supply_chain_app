import re
import sys
import unicodedata

import numpy as np
import pandas as pd
import streamlit as st

import comparison
import data_quality as dq
import metrics
import planning

# ---------------------------------------------------------------------------
# Garde-fou "bare mode" : si le script est lancé avec `python app.py` au lieu de
# `streamlit run app.py`, Streamlit tourne à vide, st.stop() n'a aucun effet, et
# tout le code plante plus loin sur des DataFrames vides. On détecte ce cas tôt
# et on affiche un message clair dans le terminal, puis on arrête proprement.
# ---------------------------------------------------------------------------
try:
    from streamlit.runtime.scriptrunner import get_script_run_ctx as _get_ctx
    _IN_STREAMLIT = _get_ctx() is not None
except Exception:
    _IN_STREAMLIT = False

if not _IN_STREAMLIT:
    print(
        "\n" + "=" * 70 + "\n"
        "  Cette application doit être lancée avec Streamlit, pas avec Python.\n\n"
        "  ❌  python app.py        (ne fonctionne pas)\n"
        "  ✅  streamlit run app.py  (commande correcte)\n\n"
        "  Ouvre un terminal dans ce dossier et tape :  streamlit run app.py\n"
        + "=" * 70 + "\n",
        file=sys.stderr,
    )
    sys.exit(1)

st.set_page_config(
    page_title="Supply Chain Forecast Tracker",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(180deg, #07111f 0%, #0d1725 100%);
            color: #edf3ff;
        }
        .hero-card {
            background: linear-gradient(135deg, rgba(35, 64, 101, 0.94), rgba(13, 23, 37, 0.96));
            border: 1px solid rgba(143, 179, 255, 0.25);
            border-radius: 18px;
            padding: 1.5rem 1.6rem;
            box-shadow: 0 16px 30px rgba(0,0,0,0.18);
            margin-bottom: 1rem;
        }
        h1 { font-size: 2.6rem !important; line-height: 1.15 !important; margin-bottom: 0.25rem !important; }
        h2 { font-size: 1.8rem !important; }
        h3 { font-size: 1.35rem !important; }
        p, li, .stMarkdown, .stDataFrame, .stMetricValue, .stMetricLabel { font-size: 1rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# SIDEBAR — paramètres globaux (corrige le format de date figé et redonne
# un accès aux données d'exemple, perdus dans la version sans sidebar)
# ---------------------------------------------------------------------------
st.sidebar.header("⚙️ Paramètres")
dayfirst = st.sidebar.checkbox(
    "Dates au format JJ/MM/AAAA",
    value=True,
    help="Coché par défaut (format FR/Maroc). Décoche si tes exports sont en AAAA-MM-JJ ou MM/JJ/AAAA.",
)
freq_choice = st.sidebar.selectbox("Période d'agrégation", options=["Semaine", "Mois"], index=0)
freq = {"Semaine": "W-MON", "Mois": "MS"}[freq_choice]
currency = st.sidebar.text_input("Devise", value="DH", max_chars=6)

with st.sidebar.expander("📥 Fichiers d'exemple"):
    sample_orders = pd.DataFrame({
        "Date": ["01/06/2026", "03/06/2026", "08/06/2026", "01/06/2026", "09/06/2026", "15/06/2026"],
        "Item": ["SKU001", "SKU001", "SKU001", "SKU002", "SKU002", "SKU002"],
        "Quantité": [100, 50, 120, 30, 20, 45],
    })
    sample_forecast = pd.DataFrame({
        "Date": ["01/06/2026", "08/06/2026", "15/06/2026", "01/06/2026", "08/06/2026", "15/06/2026"],
        "Item": ["SKU001", "SKU001", "SKU001", "SKU002", "SKU002", "SKU002"],
        "Quantité": [90, 100, 90, 40, 25, 40],
    })
    sample_stock = pd.DataFrame({"Item": ["SKU001", "SKU002"], "Stock": [200, 60]})
    sample_prices = pd.DataFrame({
        "Item": ["SKU001", "SKU002"],
        "Prix vente": [150, 220],
        "Prix achat": [90, 130],
    })
    st.download_button("Exemple commandes", sample_orders.to_csv(index=False).encode("utf-8"), "exemple_commandes.csv", "text/csv")
    st.download_button("Exemple prévisionnel", sample_forecast.to_csv(index=False).encode("utf-8"), "exemple_previsionnel.csv", "text/csv")
    st.download_button("Exemple stock", sample_stock.to_csv(index=False).encode("utf-8"), "exemple_stock.csv", "text/csv")
    st.download_button("Exemple prix", sample_prices.to_csv(index=False).encode("utf-8"), "exemple_prix.csv", "text/csv")

home_tab, unique_tab, multi_tab, analysis_tab, charts_tab = st.tabs([
    "Accueil", "Téléchargement unique", "Téléchargement multiple", "Analyse", "Graphiques",
])

with home_tab:
    st.markdown(
        """
        <div class='hero-card'>
            <h1>Optimisation des besoins</h1>
            <p style='font-size:1.15rem; margin:0.4rem 0 0.2rem 0; color:#dfe9ff;'>Carnet de commande vs prévisionnel</p>
            <p style='font-size:1.02rem; color:#c9d8f8; margin-top:0.8rem;'>
                Suivi des écarts, priorisation des articles, couverture de stock projetée et recommandations d'anticipation.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### Objectif")
    st.write(
        "Cette application permet d'identifier rapidement les écarts entre les commandes réelles et le prévisionnel système, "
        "d'évaluer la couverture de stock dans le temps et de prioriser les actions à lancer avant la prochaine période."
    )
    st.markdown("### Ce que tu peux faire")
    st.markdown(
        "- Importer un ou plusieurs fichiers CSV ou Excel\n"
        "- Vérifier la cohérence des colonnes (détection automatique)\n"
        "- Analyser les écarts par article et par date\n"
        "- Prioriser les actions d'anticipation\n"
        "- Visualiser les résultats en Pareto, courbes et diagramme circulaire"
    )
    st.info("Utilise les onglets ci-dessus pour passer à l'import, puis à l'Analyse et aux Graphiques. Les paramètres de format sont dans la barre latérale.")

    st.markdown("---")
    st.subheader("FAQ")
    with st.expander("Pourquoi certains fichiers ne sont pas reconnus ?"):
        st.write("Les colonnes peuvent avoir des noms légèrement différents. L'application normalise automatiquement les libellés les plus fréquents.")
    with st.expander("Peut-on comparer plusieurs fichiers en même temps ?"):
        st.write("Oui. Utilise l'onglet Téléchargement multiple et charge plusieurs fichiers de commandes, prévision et stock pour les concaténer.")
    with st.expander("Que faire si un fichier ne contient pas de date ?"):
        st.write("Le fichier doit avoir une date pour être utilisé dans l'analyse de tendance et les écarts par période.")
    with st.expander("Comment la couverture de stock est-elle calculée ?"):
        st.write(
            "Le stock initial est décrémenté période après période par le besoin réel déjà consommé. "
            "Ce n'est donc pas le même stock qui est compté plusieurs fois pour plusieurs périodes."
        )
    with st.expander("Comment obtenir le chiffre d'affaires et la valeur de stock ?"):
        st.write(
            "Ajoute un fichier optionnel `Item` + `Prix vente` et/ou `Prix achat`. Avec un prix de vente, "
            "l'app calcule le chiffre d'affaires réel/prévu. Avec un prix d'achat, elle valorise le stock "
            "projeté (composante stock du BFR — le BFR complet inclurait aussi créances et dettes, non "
            "disponibles ici)."
        )

    st.markdown("---")
    st.markdown(
        "**Format recommandé :** `Date`, `Item`, `Quantité` pour commandes/prévision, `Item`, `Stock` pour "
        "couverture, et `Item`, `Prix vente`/`Prix achat` (optionnel) pour la valorisation."
    )

# ---------------------------------------------------------------------------
# UPLOADS
# ---------------------------------------------------------------------------
with unique_tab:
    st.subheader("Téléchargement unique")
    orders_file = st.file_uploader("Carnet de commandes réelles (CSV / Excel)", type=["csv", "xlsx", "xls"], key="orders_single")
    forecast_file = st.file_uploader("Prévisionnel système (CSV / Excel)", type=["csv", "xlsx", "xls"], key="forecast_single")
    stock_file = st.file_uploader("Stock initial (CSV / Excel)", type=["csv", "xlsx", "xls"], key="stock_single")
    price_file = st.file_uploader(
        "Prix par article (CSV / Excel) — optionnel", type=["csv", "xlsx", "xls"], key="price_single",
        help="Colonnes Item + Prix vente et/ou Prix achat/coût. Active le calcul du chiffre d'affaires et de la valeur de stock immobilisé.",
    )

with multi_tab:
    st.subheader("Téléchargement multiple")
    multi_orders_files = st.file_uploader("Plusieurs fichiers commandes", type=["csv", "xlsx", "xls"], accept_multiple_files=True, key="orders_multi")
    multi_forecast_files = st.file_uploader("Plusieurs fichiers prévision", type=["csv", "xlsx", "xls"], accept_multiple_files=True, key="forecast_multi")
    multi_stock_files = st.file_uploader("Plusieurs fichiers stock", type=["csv", "xlsx", "xls"], accept_multiple_files=True, key="stock_multi")
    multi_price_files = st.file_uploader("Plusieurs fichiers prix — optionnel", type=["csv", "xlsx", "xls"], accept_multiple_files=True, key="price_multi")
    st.caption("La comparaison multi-fichiers concatène les données chargées pour analyser plusieurs lots, périodes ou scénarios.")

# ---------------------------------------------------------------------------
# Helpers de chargement
# ---------------------------------------------------------------------------
COLUMN_MAPPING = {
    "date": "Date", "jour": "Date", "day": "Date",
    "datecommande": "Date", "datedecommande": "Date", "datedelivraison": "Date", "dateprevision": "Date",
    "item": "Item", "article": "Item", "piece": "Item", "pieceid": "Item", "ref": "Item",
    "reference": "Item", "referencearticle": "Item", "articlecode": "Item", "product": "Item",
    "produit": "Item", "designation": "Item", "designations": "Item", "referencepiece": "Item",
    "quantite": "Quantité", "quantitecommandee": "Quantité", "quantitecommande": "Quantité",
    "quantiteprevision": "Quantité", "qte": "Quantité", "qty": "Quantité", "quantity": "Quantité",
    "quantityordered": "Quantité",
    "stock": "Stock", "stockdisponible": "Stock", "stocktotal": "Stock", "stocktotaldisponible": "Stock",
    "qtestock": "Stock", "qtypstock": "Stock", "stockcouverture": "Stock", "couverture": "Stock",
    "stockdisponiblefinal": "Stock", "stockfinal": "Stock",
    "prix": "Prix vente", "prixunitaire": "Prix vente", "prixvente": "Prix vente", "prixdevente": "Prix vente",
    "pu": "Prix vente", "price": "Prix vente", "prixht": "Prix vente", "puvente": "Prix vente",
    "prixachat": "Prix achat", "prixdachat": "Prix achat", "cout": "Prix achat", "coutunitaire": "Prix achat",
    "coutachat": "Prix achat", "prixderevient": "Prix achat", "prixderevientunitaire": "Prix achat",
    "cost": "Prix achat", "puachat": "Prix achat", "coutstandard": "Prix achat",
}


def canonicalize_name(name):
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    text = text.strip().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def normalize_columns(df):
    df = df.rename(columns={c: c.strip() for c in df.columns})
    col_map = {}
    for col in df.columns:
        normalized = canonicalize_name(col)
        if normalized in COLUMN_MAPPING:
            col_map[col] = COLUMN_MAPPING[normalized]
    return df.rename(columns=col_map)


def infer_missing_columns(df, required):
    available = [str(c).strip() for c in df.columns]
    renamed = df.copy()
    for target in required:
        if target in renamed.columns:
            continue
        target_key = canonicalize_name(target)
        best_match = None
        for col in available:
            col_key = canonicalize_name(col)
            if col_key == target_key:
                best_match = col
                break
            if target == "Date" and ("date" in col_key or "jour" in col_key):
                best_match = col
                break
            if target == "Item" and any(k in col_key for k in ("item", "article", "piece", "ref", "produit", "designation", "reference")):
                best_match = col
                break
            if target == "Quantité" and any(k in col_key for k in ("qte", "quant", "qty")):
                best_match = col
                break
            if target == "Stock" and any(k in col_key for k in ("stock", "couvert", "coverage")):
                best_match = col
                break
            if target == "Prix vente" and any(k in col_key for k in ("prixvente", "puvente", "pricesale", "prixht")):
                best_match = col
                break
            if target == "Prix achat" and any(k in col_key for k in ("prixachat", "cout", "revient", "cost")):
                best_match = col
                break
        if best_match is not None:
            renamed = renamed.rename(columns={best_match: target})
    return renamed


def read_tabular_file(uploaded_file):
    name = (uploaded_file.name or "").lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file)
    try:
        return pd.read_csv(uploaded_file, sep=None, engine="python")
    except Exception:
        uploaded_file.seek(0)
        try:
            return pd.read_csv(uploaded_file, sep=";", decimal=",", engine="python")
        except Exception:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, sep="\t", engine="python")


def load_data(uploaded_file, require_date, dayfirst_flag, issues=None):
    """Charge et nettoie un fichier. Lève ValueError avec un message clair en cas de problème
    (au lieu de laisser remonter une exception brute jusqu'à l'interface).
    Les anomalies non bloquantes (lignes ignorées, valeurs vides…) sont ajoutées à `issues`."""
    issues = issues if issues is not None else []
    label = f"'{uploaded_file.name}'"
    df = read_tabular_file(uploaded_file)
    df.columns = [str(c).strip() for c in df.columns]
    df = normalize_columns(df)
    df = df.loc[:, ~df.columns.duplicated()].copy()

    if require_date:
        required = ["Date", "Item", "Quantité"]
        df = infer_missing_columns(df, required)
        df = df.loc[:, ~df.columns.duplicated()].copy()
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"'{uploaded_file.name}' : colonnes manquantes ({', '.join(missing)}).")
        df["Item"] = df["Item"].astype(str).str.strip()
        parsed = dq.parse_dates(df["Date"], dayfirst_flag)
        if parsed.isna().all():
            raise ValueError(f"'{uploaded_file.name}' : aucune date lisible (vérifie le format JJ/MM/AAAA dans la barre latérale).")
        n_bad_dates = int(parsed.isna().sum())
        if n_bad_dates:
            issues.append(dq.issue(dq.WARNING, f"{label} : {n_bad_dates} ligne(s) ignorée(s) car la date est illisible."))
        df["Date"] = parsed
        df = df.dropna(subset=["Date"])
        quantities = pd.to_numeric(df["Quantité"], errors="coerce")
        n_bad_qty = int(quantities.isna().sum())
        if n_bad_qty:
            issues.append(dq.issue(dq.WARNING, f"{label} : {n_bad_qty} ligne(s) ignorée(s) car la quantité est vide ou non numérique."))
        df["Quantité"] = quantities
        df = df.dropna(subset=["Quantité"])
        issues.extend(dq.check_frame(df, label, "Quantité"))
    else:
        df = infer_missing_columns(df, ["Item", "Stock"])
        df = df.loc[:, ~df.columns.duplicated()].copy()
        if "Item" not in df.columns or "Stock" not in df.columns:
            raise ValueError(f"'{uploaded_file.name}' : colonnes Item/Stock manquantes.")
        df["Item"] = df["Item"].astype(str).str.strip()
        stocks = pd.to_numeric(df["Stock"], errors="coerce")
        n_bad_stock = int(stocks.isna().sum())
        if n_bad_stock:
            issues.append(dq.issue(dq.WARNING, f"{label} : {n_bad_stock} ligne(s) ignorée(s) car le stock est vide ou non numérique."))
        df["Stock"] = stocks
        df = df.dropna(subset=["Stock"])
        issues.extend(dq.check_frame(df, label, "Stock"))

    return df


def load_price_data(uploaded_file):
    """Charge un fichier de prix : Item obligatoire, au moins une des deux colonnes de prix
    (Prix vente et/ou Prix achat). Les deux sont optionnelles indépendamment l'une de l'autre —
    l'app calcule ce qu'elle peut avec ce qui est fourni."""
    df = read_tabular_file(uploaded_file)
    df.columns = [str(c).strip() for c in df.columns]
    df = normalize_columns(df)
    df = infer_missing_columns(df, ["Item", "Prix vente", "Prix achat"])
    df = df.loc[:, ~df.columns.duplicated()].copy()

    if "Item" not in df.columns:
        raise ValueError(f"'{uploaded_file.name}' : colonne Item manquante.")
    if "Prix vente" not in df.columns and "Prix achat" not in df.columns:
        raise ValueError(f"'{uploaded_file.name}' : aucune colonne de prix reconnue (Prix vente / Prix achat).")

    df["Item"] = df["Item"].astype(str).str.strip()
    for col in ["Prix vente", "Prix achat"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def safe_load_many(files, require_date, dayfirst_flag, issues=None, role="Fichiers"):
    """Charge une liste de fichiers en ignorant ceux en erreur (avec message), plutôt que
    de faire planter toute l'application à cause d'un seul fichier mal formé.
    Avec plusieurs fichiers, signale les doublons d'import et les chevauchements dans `issues`."""
    issues = issues if issues is not None else []
    frames, errors = [], []
    for f in files:
        if f is None:
            continue
        try:
            frame = load_data(f, require_date, dayfirst_flag, issues)
            frame["_source"] = f.name
            frames.append(frame)
        except ValueError as e:
            errors.append(str(e))
    for e in errors:
        st.error(e)
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    issues.extend(dq.check_multi_source(combined, role, "Quantité" if require_date else "Stock"))
    return combined.drop(columns="_source")


def safe_load_prices(files, issues=None):
    issues = issues if issues is not None else []
    frames, errors = [], []
    for f in files:
        if f is None:
            continue
        try:
            frames.append(load_price_data(f))
        except ValueError as e:
            errors.append(str(e))
    for e in errors:
        st.error(e)
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    issues.extend(dq.check_price_conflicts(combined))
    # Un article peut apparaître plusieurs fois (plusieurs fichiers) : on garde la moyenne.
    agg = {}
    if "Prix vente" in combined.columns:
        agg["Prix vente"] = "mean"
    if "Prix achat" in combined.columns:
        agg["Prix achat"] = "mean"
    return combined.groupby("Item", as_index=False).agg(agg)


# ---------------------------------------------------------------------------
# Chargement effectif
# ---------------------------------------------------------------------------
single_ready = orders_file is not None and forecast_file is not None
multi_ready = bool(multi_orders_files) and bool(multi_forecast_files)

quality_issues = []

if single_ready:
    orders_df = safe_load_many([orders_file], True, dayfirst, quality_issues, "Commandes")
    forecast_df = safe_load_many([forecast_file], True, dayfirst, quality_issues, "Prévisionnel")
    stock_df = safe_load_many([stock_file] if stock_file is not None else [], False, dayfirst, quality_issues, "Stock")
    price_df = safe_load_prices([price_file] if price_file is not None else [], quality_issues)
elif multi_ready:
    orders_df = safe_load_many(multi_orders_files, True, dayfirst, quality_issues, "Commandes")
    forecast_df = safe_load_many(multi_forecast_files, True, dayfirst, quality_issues, "Prévisionnel")
    stock_df = safe_load_many(multi_stock_files, False, dayfirst, quality_issues, "Stock")
    price_df = safe_load_prices(multi_price_files, quality_issues)
else:
    orders_df, forecast_df, stock_df, price_df = None, None, None, None

if orders_df is None or forecast_df is None:
    with analysis_tab:
        st.warning("Téléverse les fichiers commandes et prévisionnel (onglet unique ou multiple) pour lancer l'analyse.")
    with charts_tab:
        st.info("Les graphiques s'affichent dès qu'une base de données est chargée.")
    st.stop()
    # Filet de sécurité : st.stop() lève normalement une exception qui arrête l'exécution,
    # mais on protège explicitement la suite au cas où (ex. environnement non standard).
    raise SystemExit

quality_issues.extend(dq.check_consistency(orders_df, forecast_df, stock_df, price_df))

# ---------------------------------------------------------------------------
# Calculs communs (faits une seule fois, utilisés par les onglets Analyse et Graphiques)
# ---------------------------------------------------------------------------
merged = comparison.merge_orders_forecast(orders_df, forecast_df, freq)
n_real_missing, n_forecast_missing = comparison.data_gap_counts(merged)
if n_forecast_missing:
    quality_issues.append(dq.issue(
        dq.WARNING,
        f"{n_forecast_missing} combinaison(s) période/article ont des commandes mais aucune ligne de prévision "
        "(marquées « Prévision absente »). Leur écart est laissé vide et elles sont exclues du WAPE et du biais.",
    ))
if n_real_missing:
    quality_issues.append(dq.issue(
        dq.INFO,
        f"{n_real_missing} combinaison(s) période/article ont une prévision mais aucune commande "
        "(marquées « Réel absent ») : comptées comme une demande nulle.",
    ))

# --- Couverture de stock projetée, valorisation, priorités et besoin recommandé (voir planning.py) ---
merged = planning.project_stock(merged, stock_df)
has_prix_vente = price_df is not None and "Prix vente" in price_df.columns
has_prix_achat = price_df is not None and "Prix achat" in price_df.columns
merged = planning.add_valuation(merged, price_df)
item_totals = planning.summarize_items(merged, stock_df is not None, has_prix_vente, has_prix_achat)
item_reco = planning.recommend_need(merged, item_totals)

# ---------------------------------------------------------------------------
# ONGLET ANALYSE — tout le contenu est maintenant bien à l'intérieur du tab
# ---------------------------------------------------------------------------
with analysis_tab:
    n_errors, n_warnings = dq.summarize(quality_issues)
    with st.expander(
        f"🔍 Contrôle qualité des données — {n_errors} erreur(s), {n_warnings} alerte(s)",
        expanded=bool(n_errors or n_warnings),
    ):
        if not quality_issues:
            st.success("Aucun problème détecté dans les fichiers chargés.")
        for item in quality_issues:
            {"error": st.error, "warning": st.warning}.get(item["level"], st.info)(item["message"])

    st.header("Aperçu des données")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Carnet de commandes réelles")
        st.dataframe(orders_df.head(10), use_container_width=True)
        st.metric("Total quantité réelle", int(orders_df["Quantité"].sum()))
    with col2:
        st.subheader("Prévisionnel système")
        st.dataframe(forecast_df.head(10), use_container_width=True)
        st.metric("Total quantité prévue", int(forecast_df["Quantité"].sum()))

    if stock_df is not None:
        st.subheader("Stock initial")
        stock_summary = stock_df.groupby("Item")["Stock"].sum().reset_index()
        st.dataframe(stock_summary, use_container_width=True)
        st.metric("Stock total initial", int(stock_summary["Stock"].sum()))

    st.header("Analyse des écarts par période et par pièce")
    display_cols = ["Date", "Item", "Réel", "Prévision", "Écart", "Écart %", "Besoin net", "Statut couverture", "Lancer OF", "Données"]
    fmt = {"Écart": "{:.0f}", "Écart %": "{:.1f}%", "Stock projeté": "{:.0f}", "Besoin net": "{:.0f}"}
    if stock_df is not None:
        display_cols.insert(6, "Stock projeté")
    if has_prix_vente:
        display_cols += ["CA réel", "CA prévision", "Écart CA"]
        fmt.update({"CA réel": "{:.0f}", "CA prévision": "{:.0f}", "Écart CA": "{:.0f}"})
    if has_prix_achat:
        display_cols.append("Valeur stock projeté")
        fmt["Valeur stock projeté"] = "{:.0f}"
    st.dataframe(
        merged[display_cols].sort_values(["Item", "Date"]).style.format(fmt, na_rep="—"),
        use_container_width=True,
    )
    if has_prix_vente or has_prix_achat:
        st.caption(f"Valeurs monétaires en {currency}.")

    st.markdown("---")
    st.subheader("Écarts globaux")
    col3, col4, col5 = st.columns(3)
    col3.metric("Total réel", int(merged["Réel"].sum()))
    col4.metric("Total prévision", int(merged["Prévision"].sum()))
    col5.metric("Total écart", int(merged["Écart"].sum()))
    measurable = comparison.accuracy_rows(merged)
    global_wape = metrics.wape(measurable["Réel"], measurable["Prévision"])
    global_bias = metrics.bias_volume(measurable["Réel"], measurable["Prévision"])
    col6, col7 = st.columns(2)
    col6.metric(
        "WAPE (erreur absolue pondérée)",
        "—" if pd.isna(global_wape) else f"{global_wape:.1f} %",
        help="Somme des écarts absolus ÷ somme du réel. Plus c'est bas, meilleur est le prévisionnel. "
             "Les petites quantités ne faussent pas cet indicateur.",
    )
    col7.metric(
        "Biais en volume",
        "—" if pd.isna(global_bias) else f"{global_bias:+.1f} %",
        help="(Total prévu − total réel) ÷ total réel. Positif : le système surestime la demande ; "
             "négatif : il la sous-estime.",
    )
    st.caption(f"Lecture du biais : {metrics.describe_bias(global_bias)}.")
    if n_forecast_missing:
        st.caption(
            f"{n_forecast_missing} ligne(s) « Prévision absente » exclue(s) du WAPE, du biais et du total d'écart "
            "(le total d'écart n'est donc pas égal à total prévu − total réel)."
        )

    if has_prix_vente or has_prix_achat:
        st.markdown("---")
        st.subheader("Valorisation financière")
        vcols = st.columns(3 if has_prix_vente and has_prix_achat else 2)
        idx = 0
        if has_prix_vente:
            ca_reel_total = merged["CA réel"].sum()
            ca_prev_total = merged["CA prévision"].sum()
            vcols[idx].metric(f"CA réel ({currency})", f"{ca_reel_total:,.0f}".replace(",", " "))
            idx += 1
            vcols[idx].metric(f"Écart de CA ({currency})", f"{(ca_prev_total - ca_reel_total):,.0f}".replace(",", " "))
            idx += 1
        if has_prix_achat:
            valeur_stock_totale = item_totals["Valeur stock projeté"].clip(lower=0).sum()
            vcols[idx].metric(f"Stock immobilisé — composante BFR ({currency})", f"{valeur_stock_totale:,.0f}".replace(",", " "))
        st.caption(
            "⚠️ Le CA est une approximation basée sur les quantités commandées/prévues, pas un chiffre comptable validé. "
            "La « composante BFR » ne couvre que la valeur du stock immobilisé — le BFR complet inclut aussi les "
            "créances clients et les dettes fournisseurs, non disponibles ici."
        )

    st.markdown("---")
    st.header("Recommandations de besoin")
    st.caption(
        "Corrige la prévision moyenne du biais en volume observé entre le système et le réel, "
        "plutôt que d'appliquer une marge forfaitaire arbitraire."
    )
    st.dataframe(
        item_reco[["Item", "Prévision moyenne / période", "Biais en volume %", "Besoin recommandé / période"]]
        .rename(columns={"Item": "Pièce"})
        .style.format({"Biais en volume %": "{:+.1f}%", "Prévision moyenne / période": "{:.0f}", "Besoin recommandé / période": "{:.0f}"}),
        use_container_width=True,
    )

    st.markdown("---")
    st.header("Analyse avancée et actions d'anticipation")
    st.caption(
        "Priorité et action calculées sur le total par article (et sur la couverture de stock finale), "
        "pas sur une seule période isolée."
    )
    item_totals_display = item_totals.rename(columns={
        "Item": "Pièce / référence", "Stock projeté": "Stock projeté (fin de période)",
    })
    priority_cols = [
        "Pièce / référence", "Réel total", "Prévision total", "Écart absolu total",
        "Stock projeté (fin de période)", "WAPE (%)", "Biais (%)", "Priorité",
        "Action recommandée", "Justification",
    ]
    priority_fmt = {
        "Écart absolu total": "{:.0f}", "Stock projeté (fin de période)": "{:.0f}",
        "WAPE (%)": "{:.1f}%", "Biais (%)": "{:+.1f}%",
    }
    if has_prix_vente:
        priority_cols[3:3] = ["CA réel total", "Écart CA absolu total"]
        priority_fmt.update({"CA réel total": "{:.0f}", "Écart CA absolu total": "{:.0f}"})
    if has_prix_achat and "Valeur stock projeté" in item_totals_display.columns:
        priority_cols.insert(priority_cols.index("Stock projeté (fin de période)") + 1, "Valeur stock projeté")
        priority_fmt["Valeur stock projeté"] = "{:.0f}"
    st.dataframe(
        item_totals_display[priority_cols].style.format(priority_fmt, na_rep="—"),
        use_container_width=True,
    )
    if has_prix_vente or has_prix_achat:
        st.caption(f"Valeurs monétaires en {currency}.")

    if not item_totals_display.empty:
        top_ref = item_totals_display.iloc[0]
        top_name = top_ref["Pièce / référence"]
        top_ecart = top_ref["Écart absolu total"]
        top_priorite = top_ref["Priorité"]
        top_action = top_ref["Action recommandée"]
        st.markdown(
            f"**Pièce la plus impactée : {top_name}** — "
            f"écart absolu {top_ecart:.0f} unités, priorité **{top_priorite}**, "
            f"action : **{top_action}**."
        )

    st.markdown("---")
    st.subheader("Export")
    csv_ecarts = merged.to_csv(index=False).encode("utf-8")
    csv_reco = item_totals.merge(item_reco[["Item", "Besoin recommandé / période"]], on="Item").to_csv(index=False).encode("utf-8")
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        st.download_button("📥 Exporter le tableau d'écarts (CSV)", csv_ecarts, "ecarts_besoin_reel_vs_systeme.csv", "text/csv")
    with col_e2:
        st.download_button("📥 Exporter les recommandations (CSV)", csv_reco, "recommandations_besoin.csv", "text/csv")

# ---------------------------------------------------------------------------
# ONGLET GRAPHIQUES
# ---------------------------------------------------------------------------
with charts_tab:
    st.subheader("Visualisation des écarts et de la couverture de stock")

    pareto_metric = "Écart absolu total"
    if has_prix_vente:
        metric_choice = st.radio(
            "Classer le Pareto par :", ["Unités", f"Valeur ({currency})"], horizontal=True, key="pareto_metric_choice",
        )
        if metric_choice.startswith("Valeur"):
            pareto_metric = "Écart CA absolu total"

    pareto_df = item_totals.sort_values(pareto_metric, ascending=False).reset_index(drop=True)
    total_abs = pareto_df[pareto_metric].sum()
    pareto_df["Cumul %"] = (pareto_df[pareto_metric].cumsum() / total_abs * 100) if total_abs else 0

    chart_data = merged.copy()
    chart_data["Date_str"] = chart_data["Date"].dt.strftime("%Y-%m-%d")

    chart_tabs = st.tabs(["Pareto des écarts", "Trajectoire de stock", "Courbes d'écart", "Répartition"])

    try:
        import altair as alt

        with chart_tabs[0]:
            top10 = pareto_df.head(10).copy()
            top10["Item"] = top10["Item"].astype(str)
            bar = alt.Chart(top10).mark_bar(opacity=0.9).encode(
                x=alt.X("Item:N", sort="-y", title="Référence"),
                y=alt.Y(f"{pareto_metric}:Q", title="Impact"),
                color=alt.Color("Priorité:N", scale=alt.Scale(
                    domain=["Urgent", "Élevée", "Moyenne", "Faible"],
                    range=["#d62728", "#ff7f0e", "#f1c40f", "#2ca02c"],
                )),
                tooltip=["Item", pareto_metric, "WAPE (%)", "Biais (%)", "Priorité", "Action recommandée"],
            ).properties(title="Diagramme Pareto par référence", height=360)
            line = alt.Chart(top10).mark_line(color="#7dd3fc", point=True, strokeWidth=2.5).encode(
                x=alt.X("Item:N", sort="-y"),
                y=alt.Y("Cumul %:Q", title="Cumul (%)"),
                tooltip=["Item", "Cumul %"],
            )
            st.altair_chart(bar + line, use_container_width=True)

        with chart_tabs[1]:
            if stock_df is not None:
                stock_chart = alt.Chart(chart_data).mark_line(point=True).encode(
                    x=alt.X("Date_str:O", title="Période"),
                    y=alt.Y("Stock projeté:Q", title="Stock projeté"),
                    color="Item:N",
                    tooltip=["Date_str", "Item", "Stock projeté", "Réel", "Prévision"],
                ).properties(title="Stock projeté dans le temps", height=360)
                zero_line = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="red", strokeDash=[4, 4]).encode(y="y:Q")
                st.altair_chart(stock_chart + zero_line, use_container_width=True)
                st.caption("Ligne rouge = seuil de rupture (stock projeté = 0).")
            else:
                st.info("Fournis un fichier de stock pour voir la trajectoire projetée.")

        with chart_tabs[2]:
            line_chart = alt.Chart(chart_data.sort_values("Date")).mark_line(point=True, strokeWidth=2.5).encode(
                x=alt.X("Date:T", title="Période"),
                y=alt.Y("Écart:Q", title="Écart"),
                color=alt.Color("Item:N", legend=alt.Legend(title="Référence")),
                tooltip=["Date_str", "Item", "Réel", "Prévision", "Écart", "Écart %"],
            ).properties(title="Évolution des écarts par référence", height=360)
            st.altair_chart(line_chart, use_container_width=True)

        with chart_tabs[3]:
            pie = alt.Chart(pareto_df.head(8)).mark_arc(innerRadius=50).encode(
                theta=alt.Theta(f"{pareto_metric}:Q", stack=True),
                color=alt.Color("Item:N", legend=alt.Legend(title="Référence")),
                tooltip=["Item", pareto_metric],
            ).properties(title="Répartition des écarts par référence", height=360)
            st.altair_chart(pie, use_container_width=True)

    except ImportError:
        st.warning("Altair n'est pas disponible. Installe-le (`pip install altair`) pour afficher les graphiques.")

st.markdown("---")
st.caption(
    "Les fichiers CSV ou Excel doivent contenir une date, un identifiant de pièce/référence et une quantité (ou un stock). "
    "Les libellés courants (DATE, Date Commande, PIÈCE, RÉFÉRENCE, QTE, Stock…) sont reconnus automatiquement."
)