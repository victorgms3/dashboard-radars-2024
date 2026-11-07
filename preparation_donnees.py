# -*- coding: utf-8 -*-
"""
preparation_donnees.py
======================
Nettoyage et préparation des données du dashboard « Excès de vitesse, radars et accidents (2024) ».

Ce script est lancé UNE SEULE FOIS (environ 1 à 2 minutes). Il lit les fichiers bruts
téléchargés sur data.gouv.fr, les nettoie, puis écrit des fichiers légers dans le dossier
« donnees_preparees ». Le dashboard (app.py) ne lit QUE ces fichiers légers : il démarre
donc vite, même sur Google Colab.

Fichiers bruts attendus dans DOSSIER_BRUT :
  - opendata-vitesses-pratiquees-voitures-radar-2024.csv      (535 Mo, 9,6 millions de lignes)
  - jeu-de-donnees-liste-des-radars-fixes-en-france-2024-.csv  (radars fixes)
  - caract-2024.csv                                            (accidents : date, lieu, conditions)
  - lieux-2024.csv                                             (accidents : type de route, vitesse autorisée)
  - usagers-2024.csv                                           (accidents : victimes et gravité)

Utilisation :
  python preparation_donnees.py                      -> fichiers bruts dans le dossier parent
  python preparation_donnees.py /chemin/des/csv      -> fichiers bruts ailleurs (ex. Google Drive)
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.neighbors import BallTree, KNeighborsClassifier

# ---------------------------------------------------------------------------
# 0. PARAMÈTRES
# ---------------------------------------------------------------------------
DOSSIER_SCRIPT = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) > 1:
    DOSSIER_BRUT = sys.argv[1]
else:
    DOSSIER_BRUT = os.path.dirname(DOSSIER_SCRIPT)  # dossier parent (là où sont les CSV)

DOSSIER_SORTIE = os.path.join(DOSSIER_SCRIPT, "donnees_preparees")

FICHIER_VITESSES = "opendata-vitesses-pratiquees-voitures-radar-2024.csv"
FICHIER_RADARS = "jeu-de-donnees-liste-des-radars-fixes-en-france-2024-.csv"
FICHIER_CARACT = "caract-2024.csv"
FICHIER_LIEUX = "lieux-2024.csv"
FICHIER_USAGERS = "usagers-2024.csv"

# Rectangle qui contient la France métropolitaine (Corse comprise)
LAT_MIN, LAT_MAX = 41.0, 51.5
LON_MIN, LON_MAX = -5.5, 10.0

# Taille d'un « carreau » de la carte : 0,02 degré, soit environ 2 km x 1,5 km
TAILLE_CARREAU = 0.02

# Au-delà de cette vitesse, on considère la mesure comme une erreur
VITESSE_MAX_CREDIBLE = 200

# Seuils de dépassement (en km/h) proposés dans le dashboard
SEUILS_EXCES = [1, 5, 10, 20, 30, 50]

# Types de radars qui contrôlent la vitesse (on exclut feux rouges et passages à niveau)
TYPES_RADARS_VITESSE = ["ETF", "ETD", "ETT", "ETVM", "ETU"]

LIBELLES_RADARS = {
    "ETF": "Radar fixe classique",
    "ETD": "Radar discriminant (voitures / poids lourds)",
    "ETT": "Radar tourelle (nouvelle génération)",
    "ETVM": "Radar tronçon (vitesse moyenne)",
    "ETU": "Radar urbain",
    "ETFR": "Radar feu rouge",
    "ETPN": "Radar passage à niveau",
}

# Tranches horaires : (nom affiché, heure de début, heure de fin exclue)
TRANCHES_HORAIRES = {
    "Nuit (22h-6h)": [22, 23, 0, 1, 2, 3, 4, 5],
    "Matin (6h-10h)": [6, 7, 8, 9],
    "Journée (10h-16h)": [10, 11, 12, 13, 14, 15],
    "Soir (16h-22h)": [16, 17, 18, 19, 20, 21],
}

DEPARTEMENTS = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence", "05": "Hautes-Alpes",
    "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes", "09": "Ariège", "10": "Aube",
    "11": "Aude", "12": "Aveyron", "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal",
    "16": "Charente", "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud",
    "2B": "Haute-Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse", "24": "Dordogne",
    "25": "Doubs", "26": "Drôme", "27": "Eure", "28": "Eure-et-Loir", "29": "Finistère",
    "30": "Gard", "31": "Haute-Garonne", "32": "Gers", "33": "Gironde", "34": "Hérault",
    "35": "Ille-et-Vilaine", "36": "Indre", "37": "Indre-et-Loire", "38": "Isère", "39": "Jura",
    "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire", "44": "Loire-Atlantique",
    "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère", "49": "Maine-et-Loire",
    "50": "Manche", "51": "Marne", "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle",
    "55": "Meuse", "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord",
    "60": "Oise", "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques",
    "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône",
    "70": "Haute-Saône", "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie",
    "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres",
    "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse",
    "85": "Vendée", "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne",
    "90": "Territoire de Belfort", "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis",
    "94": "Val-de-Marne", "95": "Val-d'Oise",
}

REGIONS = {
    "Auvergne-Rhône-Alpes": ["01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"],
    "Bourgogne-Franche-Comté": ["21", "25", "39", "58", "70", "71", "89", "90"],
    "Bretagne": ["22", "29", "35", "56"],
    "Centre-Val de Loire": ["18", "28", "36", "37", "41", "45"],
    "Corse": ["2A", "2B"],
    "Grand Est": ["08", "10", "51", "52", "54", "55", "57", "67", "68", "88"],
    "Hauts-de-France": ["02", "59", "60", "62", "80"],
    "Île-de-France": ["75", "77", "78", "91", "92", "93", "94", "95"],
    "Normandie": ["14", "27", "50", "61", "76"],
    "Nouvelle-Aquitaine": ["16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87"],
    "Occitanie": ["09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"],
    "Pays de la Loire": ["44", "49", "53", "72", "85"],
    "Provence-Alpes-Côte d'Azur": ["04", "05", "06", "13", "83", "84"],
}
# Dictionnaire inverse : département -> région
REGION_DU_DEPARTEMENT = {dep: region for region, deps in REGIONS.items() for dep in deps}

# Libellés lisibles des codes du fichier accidents (guide BAAC)
LIBELLES_LUMIERE = {1: "Plein jour", 2: "Crépuscule ou aube", 3: "Nuit sans éclairage",
                    4: "Nuit, éclairage éteint", 5: "Nuit avec éclairage"}
LIBELLES_METEO = {1: "Normale", 2: "Pluie légère", 3: "Pluie forte", 4: "Neige / grêle",
                  5: "Brouillard / fumée", 6: "Vent fort / tempête", 7: "Temps éblouissant",
                  8: "Temps couvert", 9: "Autre"}
LIBELLES_COLLISION = {1: "Frontale (deux véhicules)", 2: "Par l'arrière (deux véhicules)",
                      3: "Par le côté (deux véhicules)", 4: "En chaîne (3 véhicules ou +)",
                      5: "Collisions multiples (3 véhicules ou +)", 6: "Autre collision",
                      7: "Sans collision"}
LIBELLES_ROUTE = {1: "Autoroute", 2: "Route nationale", 3: "Route départementale",
                  4: "Voie communale", 5: "Hors réseau public", 6: "Parking",
                  7: "Route de métropole urbaine", 9: "Autre"}
JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# Ce dictionnaire garde une trace de chaque étape de nettoyage (affiché dans le dashboard)
rapport = {}


def dans_la_metropole(lat, lon):
    """Renvoie un masque True/False : le point est-il dans le rectangle de la métropole ?"""
    return lat.between(LAT_MIN, LAT_MAX) & lon.between(LON_MIN, LON_MAX)


def distance_au_plus_proche(points_lat, points_lon, cibles_lat, cibles_lon):
    """Distance (en mètres) entre chaque point et la cible la plus proche.

    On utilise un BallTree (scikit-learn) avec la formule de haversine, qui calcule
    la distance « à vol d'oiseau » sur la sphère terrestre. Bien plus rapide que de
    comparer chaque point à chaque radar un par un.
    """
    rayon_terre_m = 6_371_000
    arbre = BallTree(np.radians(np.column_stack([cibles_lat, cibles_lon])), metric="haversine")
    distances, _ = arbre.query(np.radians(np.column_stack([points_lat, points_lon])), k=1)
    return distances[:, 0] * rayon_terre_m


def ajouter_noms(df):
    """Ajoute les colonnes « region » et « departement » (ex. '33 - Gironde') à partir du code."""
    df["region"] = df["dep"].map(REGION_DU_DEPARTEMENT)
    df["departement"] = df["dep"] + " - " + df["dep"].map(DEPARTEMENTS)
    return df


# ---------------------------------------------------------------------------
# 1. ACCIDENTS (fichiers BAAC caract + lieux)
# ---------------------------------------------------------------------------
def preparer_accidents():
    print("\n[1/4] Accidents BAAC 2024")
    caract = pd.read_csv(os.path.join(DOSSIER_BRUT, FICHIER_CARACT), sep=";", dtype=str, encoding="utf-8")
    lieux = pd.read_csv(os.path.join(DOSSIER_BRUT, FICHIER_LIEUX), sep=";", dtype=str, encoding="utf-8")
    nb_depart = len(caract)

    # Les coordonnées sont écrites à la française ("47,56277000") et parfois précédées d'un espace
    caract["lat"] = pd.to_numeric(caract["lat"].str.strip().str.replace(",", "."), errors="coerce")
    caract["lon"] = pd.to_numeric(caract["long"].str.strip().str.replace(",", "."), errors="coerce")

    # On ne garde que la métropole : les voitures radars n'existent pas dans les DOM-TOM
    acc = caract[dans_la_metropole(caract["lat"], caract["lon"])].copy()
    rapport["accidents_hors_metropole_retires"] = int(nb_depart - len(acc))

    # Date et heure
    acc["date"] = pd.to_datetime(acc["an"] + "-" + acc["mois"] + "-" + acc["jour"], format="%Y-%m-%d")
    acc["heure"] = acc["hrmn"].str[:2].astype(int)
    acc["mois"] = acc["date"].dt.month
    acc["jour_semaine"] = acc["date"].dt.day_of_week  # 0 = lundi

    # Codes -> libellés lisibles
    for colonne in ["lum", "atm", "col", "agg"]:
        acc[colonne] = pd.to_numeric(acc[colonne].str.strip(), errors="coerce")
    acc["lumiere"] = acc["lum"].map(LIBELLES_LUMIERE).fillna("Non renseigné")
    acc["meteo"] = acc["atm"].map(LIBELLES_METEO).fillna("Non renseigné")
    acc["collision"] = acc["col"].map(LIBELLES_COLLISION).fillna("Non renseigné")
    acc["agglomeration"] = acc["agg"].map({1: "Hors agglomération", 2: "En agglomération"})

    # Fichier lieux : un accident peut concerner plusieurs routes -> on garde la 1re ligne
    lieux = lieux.drop_duplicates(subset="Num_Acc", keep="first")
    lieux["vma"] = pd.to_numeric(lieux["vma"].str.strip(), errors="coerce")
    lieux["catr"] = pd.to_numeric(lieux["catr"].str.strip(), errors="coerce")
    # Vitesse autorisée valide = multiple de 10 entre 10 et 130 (on écarte -1, 500, 1, 2, 15...)
    vma_valide = lieux["vma"].between(10, 130) & (lieux["vma"] % 10 == 0)
    rapport["accidents_vitesse_autorisee_invalide"] = int((~vma_valide).sum())
    lieux.loc[~vma_valide, "vma"] = np.nan
    lieux["type_route"] = lieux["catr"].map(LIBELLES_ROUTE).fillna("Non renseigné")
    acc = acc.merge(lieux[["Num_Acc", "vma", "type_route"]], on="Num_Acc", how="left")

    # Fichier usagers : une ligne par personne impliquée, avec sa gravité (colonne grav)
    # Codes BAAC : 1 = indemne, 2 = tué (dans les 30 jours), 3 = blessé hospitalisé (+ de 24 h), 4 = blessé léger
    usagers = pd.read_csv(os.path.join(DOSSIER_BRUT, FICHIER_USAGERS), sep=";", dtype=str, encoding="utf-8")
    usagers["grav"] = pd.to_numeric(usagers["grav"].str.strip(), errors="coerce")
    rapport["usagers_lignes_brutes"] = int(len(usagers))
    rapport["usagers_gravite_non_renseignee"] = int((~usagers["grav"].isin([1, 2, 3, 4])).sum())
    usagers["tue"] = usagers["grav"] == 2
    usagers["blesse_hospitalise"] = usagers["grav"] == 3
    usagers["blesse_leger"] = usagers["grav"] == 4
    # Comme True vaut 1, la somme compte les victimes de chaque accident
    victimes = usagers.groupby("Num_Acc").agg(
        nb_tues=("tue", "sum"),
        nb_blesses_hospitalises=("blesse_hospitalise", "sum"),
        nb_blesses_legers=("blesse_leger", "sum"),
    ).reset_index()
    acc = acc.merge(victimes, on="Num_Acc", how="left")
    for colonne in ["nb_tues", "nb_blesses_hospitalises", "nb_blesses_legers"]:
        acc[colonne] = acc[colonne].fillna(0).astype(int)

    # Gravité de l'accident = celle de la victime la plus touchée (on teste les conditions dans l'ordre)
    acc["gravite"] = np.select(
        [acc["nb_tues"] > 0, acc["nb_blesses_hospitalises"] > 0, acc["nb_blesses_legers"] > 0],
        ["Mortel", "Grave", "Léger"],
        default="Sans blessé",
    )

    acc["dep"] = acc["dep"].str.strip()
    acc = ajouter_noms(acc)

    rapport["accidents_lignes_brutes"] = int(nb_depart)
    rapport["accidents_conserves"] = int(len(acc))
    print(f"   {nb_depart} accidents lus, {len(acc)} gardés (métropole)")
    return acc


# ---------------------------------------------------------------------------
# 2. MODÈLE « quel département ? » (k plus proches voisins)
# ---------------------------------------------------------------------------
def entrainer_modele_departement(acc):
    """Les relevés de vitesse et les radars n'ont que des coordonnées GPS, pas de département.

    Les accidents, eux, ont des coordonnées ET un département. On entraîne donc un modèle
    de classification (k plus proches voisins, vu en module 5 : apprentissage supervisé)
    qui apprend à deviner le département à partir de la position.
    """
    print("\n[2/4] Modèle de département (k plus proches voisins)")
    X = acc[["lat", "lon"]].to_numpy()
    y = acc["dep"].to_numpy()
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    modele = KNeighborsClassifier(n_neighbors=5)
    modele.fit(X_train, y_train)
    precision = modele.score(X_test, y_test)
    rapport["precision_modele_departement"] = round(float(precision), 4)
    print(f"   Précision sur des accidents jamais vus : {precision:.1%}")
    # On réentraîne sur tous les accidents pour la version finale
    modele.fit(X, y)
    return modele


# ---------------------------------------------------------------------------
# 3. RADARS FIXES
# ---------------------------------------------------------------------------
def preparer_radars(modele_dep):
    print("\n[3/4] Radars fixes")
    radars = pd.read_csv(os.path.join(DOSSIER_BRUT, FICHIER_RADARS), sep=";", encoding="latin-1", dtype=str)
    nb_depart = len(radars)

    # Noms de colonnes : on enlève les espaces en trop et on simplifie
    radars.columns = [c.strip() for c in radars.columns]
    radars = radars.rename(columns={
        "Numéro de radar": "numero", "Type de radar": "type_code",
        "Date de mise-en-service": "mise_en_service", "Latitude": "lat", "Longitude": "lon", "VMA": "vma",
    })
    for colonne in ["numero", "type_code"]:
        radars[colonne] = radars[colonne].str.strip()
    radars["lat"] = pd.to_numeric(radars["lat"], errors="coerce")
    radars["lon"] = pd.to_numeric(radars["lon"], errors="coerce")
    radars["vma"] = pd.to_numeric(radars["vma"], errors="coerce")
    radars["mise_en_service"] = pd.to_datetime(radars["mise_en_service"], errors="coerce")
    radars["annee_mise_en_service"] = radars["mise_en_service"].dt.year

    sans_coord = radars["lat"].isna() | radars["lon"].isna()
    rapport["radars_sans_coordonnees_retires"] = int(sans_coord.sum())
    radars = radars[~sans_coord]
    hors_metro = ~dans_la_metropole(radars["lat"], radars["lon"])
    rapport["radars_hors_metropole_retires"] = int(hors_metro.sum())
    radars = radars[~hors_metro].copy()

    radars["type"] = radars["type_code"].map(LIBELLES_RADARS).fillna("Autre")
    radars["controle_vitesse"] = radars["type_code"].isin(TYPES_RADARS_VITESSE)
    rapport["radars_vitesse_maximale_manquante"] = int(radars["vma"].isna().sum())
    radars["vma_texte"] = radars["vma"].map(lambda v: "Non renseignée" if pd.isna(v) else f"{v:.0f} km/h")

    radars["dep"] = modele_dep.predict(radars[["lat", "lon"]].to_numpy())
    radars = ajouter_noms(radars)

    rapport["radars_lignes_brutes"] = int(nb_depart)
    rapport["radars_conserves"] = int(len(radars))
    print(f"   {nb_depart} radars lus, {len(radars)} gardés (métropole, coordonnées valides)")
    return radars


# ---------------------------------------------------------------------------
# 4. VITESSES RELEVÉES PAR LES VOITURES RADARS
# ---------------------------------------------------------------------------
def lire_vitesses():
    """Lecture du gros fichier (535 Mo) par morceaux de 1 million de lignes, pour ne pas saturer la mémoire."""
    morceaux = []
    nb_lus = 0
    nb_aberrants = 0
    nb_hors_metro = 0
    chemin = os.path.join(DOSSIER_BRUT, FICHIER_VITESSES)
    for morceau in pd.read_csv(chemin, chunksize=1_000_000, dtype={"date": str, "position": str}):
        nb_lus += len(morceau)

        # "48.4748 -0.1163" -> deux colonnes numériques lat et lon
        position = morceau["position"].str.split(" ", n=1, expand=True)
        morceau["lat"] = pd.to_numeric(position[0], errors="coerce")
        morceau["lon"] = pd.to_numeric(position[1], errors="coerce")
        morceau["date"] = pd.to_datetime(morceau["date"], format="%Y-%m-%d %H:%M", errors="coerce")
        morceau = morceau.dropna(subset=["lat", "lon", "date", "mesure", "limite"])

        # Valeurs aberrantes
        aberrant = morceau["mesure"] > VITESSE_MAX_CREDIBLE
        nb_aberrants += int(aberrant.sum())
        morceau = morceau[~aberrant]
        dedans = dans_la_metropole(morceau["lat"], morceau["lon"])
        nb_hors_metro += int((~dedans).sum())
        morceau = morceau[dedans]

        # On ne garde que l'utile, dans des types légers (moins de mémoire)
        morceaux.append(pd.DataFrame({
            "lat": morceau["lat"].astype("float32"),
            "lon": morceau["lon"].astype("float32"),
            "mois": morceau["date"].dt.month.astype("int8"),
            "jour_semaine": morceau["date"].dt.day_of_week.astype("int8"),
            "heure": morceau["date"].dt.hour.astype("int8"),
            "mesure": morceau["mesure"].astype("int16"),
            "limite": morceau["limite"].astype("int16"),
        }))
        print(f"   {nb_lus:>10,} lignes lues".replace(",", " "), flush=True)

    vitesses = pd.concat(morceaux, ignore_index=True)
    rapport["vitesses_lignes_brutes"] = int(nb_lus)
    rapport["vitesses_aberrantes_retirees"] = nb_aberrants
    rapport["vitesses_hors_metropole_retirees"] = nb_hors_metro
    rapport["vitesses_conservees"] = int(len(vitesses))
    return vitesses


def compter(df, colonnes):
    """Agrège les relevés : pour chaque groupe, nombre de relevés et nombre d'excès par seuil."""
    agregations = {
        "nb_releves": ("mesure", "size"),
        "somme_mesure": ("mesure", "sum"),
        "somme_depassement": ("depassement_positif", "sum"),
    }
    for seuil in SEUILS_EXCES:
        agregations[f"exces_{seuil}"] = (f"exces_{seuil}", "sum")
    resultat = df.groupby(colonnes, observed=True).agg(**agregations).reset_index()
    # Types entiers légers pour des fichiers plus petits
    for colonne in ["nb_releves", "somme_mesure", "somme_depassement"] + [f"exces_{s}" for s in SEUILS_EXCES]:
        resultat[colonne] = resultat[colonne].astype("int32")
    return resultat


def preparer_vitesses(modele_dep, radars):
    print("\n[4/4] Vitesses relevées par les voitures radars (fichier de 535 Mo)")
    debut = time.time()
    v = lire_vitesses()
    print(f"   Lecture terminée en {time.time() - debut:.0f} s")

    # Dépassement en km/h (négatif = sous la limite)
    depassement = v["mesure"] - v["limite"]
    v["depassement_positif"] = depassement.clip(lower=0).astype("int16")
    for seuil in SEUILS_EXCES:
        v[f"exces_{seuil}"] = depassement >= seuil

    # Tranche horaire
    heure_vers_tranche = {h: nom for nom, heures in TRANCHES_HORAIRES.items() for h in heures}
    v["tranche"] = v["heure"].map(heure_vers_tranche)

    # Carreau de la carte : on arrondit la position à la grille de 0,02°
    v["lat_c"] = (np.round(v["lat"] / TAILLE_CARREAU) * TAILLE_CARREAU).round(2).astype("float32")
    v["lon_c"] = (np.round(v["lon"] / TAILLE_CARREAU) * TAILLE_CARREAU).round(2).astype("float32")

    # Département de chaque carreau (modèle k-voisins)
    carreaux = v[["lat_c", "lon_c"]].drop_duplicates().reset_index(drop=True)
    carreaux["dep"] = modele_dep.predict(carreaux[["lat_c", "lon_c"]].to_numpy())
    v = v.merge(carreaux, on=["lat_c", "lon_c"], how="left")
    print(f"   {len(carreaux)} carreaux de 2 km, département attribué")

    # Distance de chaque relevé au radar fixe de vitesse le plus proche
    radars_vitesse = radars[radars["controle_vitesse"]]
    v["distance_radar_m"] = distance_au_plus_proche(
        v["lat"].to_numpy(), v["lon"].to_numpy(),
        radars_vitesse["lat"].to_numpy(), radars_vitesse["lon"].to_numpy(),
    )
    # Tranches de 100 m, plafonnées à 5 km (50 = « 5 km ou plus »)
    v["distance_radar_100m"] = np.minimum(v["distance_radar_m"] // 100, 50).astype("int8")
    print(f"   Distance au radar le plus proche calculée ({time.time() - debut:.0f} s)")

    # Table 1 : carte (carreau x mois x tranche horaire x limite)
    carte = compter(v, ["lat_c", "lon_c", "dep", "mois", "tranche", "limite"])
    carte = ajouter_noms(carte)

    # Table 2 : profil horaire (département x limite x jour x heure)
    horaire = compter(v, ["dep", "limite", "jour_semaine", "heure"])
    horaire = ajouter_noms(horaire)

    # Table 3 : effet de la distance au radar fixe (département x limite x tranche de 100 m)
    distance = compter(v, ["dep", "limite", "distance_radar_100m"])
    distance = ajouter_noms(distance)

    print(f"   Tables agrégées : carte {len(carte)} lignes, horaire {len(horaire)}, distance {len(distance)}")
    return carte, horaire, distance


# ---------------------------------------------------------------------------
# PROGRAMME PRINCIPAL
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    debut_total = time.time()
    os.makedirs(DOSSIER_SORTIE, exist_ok=True)
    print("Fichiers bruts lus dans :", DOSSIER_BRUT)

    accidents = preparer_accidents()
    modele_departement = entrainer_modele_departement(accidents)
    radars = preparer_radars(modele_departement)

    # Distance de chaque accident au radar fixe de vitesse le plus proche
    radars_vitesse = radars[radars["controle_vitesse"]]
    accidents["distance_radar_m"] = distance_au_plus_proche(
        accidents["lat"].to_numpy(), accidents["lon"].to_numpy(),
        radars_vitesse["lat"].to_numpy(), radars_vitesse["lon"].to_numpy(),
    ).round(0)

    carte, horaire, distance = preparer_vitesses(modele_departement, radars)

    # Un département est « couvert » s'il a au moins 10 000 relevés de voitures radars dans l'année
    releves_par_dep = carte.groupby("dep")["nb_releves"].sum()
    deps_couverts = sorted(releves_par_dep[releves_par_dep >= 10_000].index)
    rapport["departements_couverts"] = deps_couverts
    accidents["dep_couvert_voitures_radars"] = accidents["dep"].isin(deps_couverts)

    # Écriture des fichiers légers
    colonnes_accidents = [
        "Num_Acc", "date", "mois", "jour_semaine", "heure", "lat", "lon", "dep", "departement", "region",
        "agglomeration", "lumiere", "meteo", "collision", "type_route", "vma", "distance_radar_m",
        "dep_couvert_voitures_radars", "gravite", "nb_tues", "nb_blesses_hospitalises", "nb_blesses_legers",
    ]
    colonnes_radars = [
        "numero", "type_code", "type", "controle_vitesse", "mise_en_service", "annee_mise_en_service",
        "vma", "vma_texte", "lat", "lon", "dep", "departement", "region",
    ]
    accidents[colonnes_accidents].to_parquet(os.path.join(DOSSIER_SORTIE, "accidents.parquet"), index=False)
    radars[colonnes_radars].to_parquet(os.path.join(DOSSIER_SORTIE, "radars_fixes.parquet"), index=False)
    carte.to_parquet(os.path.join(DOSSIER_SORTIE, "vitesses_carte.parquet"), index=False)
    horaire.to_parquet(os.path.join(DOSSIER_SORTIE, "vitesses_horaires.parquet"), index=False)
    distance.to_parquet(os.path.join(DOSSIER_SORTIE, "vitesses_distance_radar.parquet"), index=False)
    with open(os.path.join(DOSSIER_SORTIE, "rapport_nettoyage.json"), "w", encoding="utf-8") as f:
        json.dump(rapport, f, ensure_ascii=False, indent=2)

    print("\nRapport de nettoyage :")
    for cle, valeur in rapport.items():
        print(f"   {cle} : {valeur}")
    print(f"\nTerminé en {time.time() - debut_total:.0f} s. Fichiers écrits dans : {DOSSIER_SORTIE}")
    for nom in sorted(os.listdir(DOSSIER_SORTIE)):
        taille = os.path.getsize(os.path.join(DOSSIER_SORTIE, nom)) / 1e6
        print(f"   {nom:<35} {taille:6.2f} Mo")
