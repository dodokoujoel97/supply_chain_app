"""Indicateurs d'erreur de prévision (sans dépendance à Streamlit).

Les moyennes de pourcentages par ligne sont instables dès qu'une quantité est petite
(1 prévu contre 3 réels = 67 %, 3 contre 1 = 200 %) et les erreurs de signes opposés
s'annulent. On utilise donc des indicateurs pondérés par les volumes :

- WAPE  = somme des |prévision - réel| / somme du réel      (taille de l'erreur)
- Biais = (somme des prévisions - somme du réel) / somme du réel   (direction de l'erreur)

Convention du projet : écart = prévision - réel. Un biais positif signifie que le système
surestime la demande, un biais négatif qu'il la sous-estime.
"""

import numpy as np


def wape(actual, forecast):
    """Erreur absolue pondérée en % ; NaN si le réel total est nul."""
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    total = actual.sum()
    if total == 0:
        return float("nan")
    return float(np.abs(forecast - actual).sum() / total * 100)


def bias_volume(actual, forecast):
    """Biais en volume en % ; NaN si le réel total est nul."""
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    total = actual.sum()
    if total == 0:
        return float("nan")
    return float((forecast.sum() - total) / total * 100)


def describe_bias(bias_pct, tolerance=2.0):
    """Phrase courte décrivant le sens du biais (tolérance en points de %)."""
    if bias_pct != bias_pct:  # NaN
        return "non calculable"
    if bias_pct > tolerance:
        return "le système surestime la demande"
    if bias_pct < -tolerance:
        return "le système sous-estime la demande"
    return "pas de biais significatif"
