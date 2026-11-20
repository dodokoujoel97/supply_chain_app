# Supply Chain Forecast Tracker

Application Streamlit de comparaison entre les commandes réelles et le prévisionnel, avec analyse des écarts, couverture du stock et recommandations.

## Emplacement du projet

Le dossier de référence est :

```text
C:\Users\DELL\supply_chain_app
```

Garde ce dossier comme emplacement de travail. Le code principal est `app.py` à la racine. Modifie ce fichier pour faire évoluer l'application; évite d'en créer des copies comme `app_final.py` ou `app_v2.py`.

Dans VS Code, ouvre le dossier complet avec **Fichier > Ouvrir le dossier**. L'interpréteur Python du projet est configuré dans `.vscode/settings.json` et pointe vers `.venv`.

## Fichiers importants

- `app.py` : interface Streamlit (chargement des fichiers, affichage des onglets).
- `data_quality.py` : lecture des dates et contrôles de qualité des données.
- `comparison.py` : rapprochement commandes / prévisionnel, gestion des données absentes.
- `metrics.py` : indicateurs d'erreur (WAPE, biais en volume).
- `planning.py` : stock projeté, valorisation, priorités, actions et besoin recommandé.
- `tests/` : tests unitaires des modules de calcul (ils ne dépendent pas de Streamlit).
- `requirements.txt` : bibliothèques Python nécessaires.
- `sample_data_orders.csv`, `sample_data_forecast.csv`, `sample_data_stock.csv` : fichiers d'exemple.
- `.vscode/backup.ps1` : crée une archive de sauvegarde horodatée à côté du dossier projet.
- `.venv/` : environnement Python local, généré sur cet ordinateur; il ne faut pas le déplacer ni le sauvegarder.

## Installation et lancement

Ouvre PowerShell dans le dossier projet, puis exécute :

```powershell
cd C:\Users\DELL\supply_chain_app
```

Si `.venv` n'existe pas encore, crée-le et installe les dépendances :

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Pour lancer l'application :

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

L'adresse locale affichée sera généralement `http://localhost:8501`. Pour ajouter une bibliothèque, ajoute-la aussi à `requirements.txt`.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
```

Toute modification de la logique de calcul (`comparison.py`, `metrics.py`, `planning.py`, `data_quality.py`) doit passer ces tests. Ajoute un test pour chaque nouvelle règle.

## Sauvegarde

Avant une modification importante, crée une archive du projet :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.vscode\backup.ps1
```

L'archive datée est enregistrée dans `C:\Users\DELL`, à côté du dossier du projet. Elle exclut `.venv`, les caches Python et les fichiers secrets. Pour restaurer une sauvegarde, extrais son contenu dans un nouveau dossier, puis réinstalle les dépendances avec la commande ci-dessus.

## Format des données

Les fichiers de commandes et de prévision doivent contenir une date, un article et une quantité. Les noms les plus courants sont reconnus automatiquement.

```csv
Date,Item,Quantité
2026-08-01,Produit A,120
2026-08-01,Produit B,80
```

Le fichier de stock utilise `Item` et `Stock`. Le fichier facultatif des prix utilise `Item` avec `Prix vente`, `Prix achat`, ou les deux. Les formats CSV et Excel sont acceptés.

### Réceptions, délais et stock de sécurité (facultatifs, nécessitent le fichier de stock)

```csv
Date,Item,Quantité            # réceptions attendues (commandes fournisseurs, OF lancés)
2026-08-17,Produit A,150
```

```csv
Item,Délai (jours),Stock sécurité
Produit A,7,80
```

- Les réceptions sont ajoutées au stock projeté à partir de leur période : `stock projeté = stock initial + réceptions cumulées − demande réelle cumulée`.
- Sous le **stock de sécurité**, l'article passe « Sous stock de sécurité » (priorité Élevée, action « Lancer OF / réapprovisionner ») avant d'atteindre la rupture. Le besoin net est la quantité nécessaire pour revenir au stock de sécurité.
- Le **statut d'un article** est le pire statut rencontré sur tout l'horizon, même si une réception rétablit le stock plus tard.
- La **date limite de commande** est la première date à risque moins le délai d'approvisionnement. Elle est comparée à la « Date de référence » de la barre latérale (aujourd'hui par défaut) pour signaler un délai déjà dépassé.
- Les stocks sont évalués en fin de période : une rupture ou une réception à l'intérieur d'une même période n'est pas distinguée.

## Utilisation

1. Téléverse le carnet de commandes réelles.
2. Téléverse le prévisionnel système.
3. Ajoute, si nécessaire, les fichiers de stock et de prix.
4. Consulte les onglets Analyse et Graphiques, puis utilise les boutons d'export CSV.
