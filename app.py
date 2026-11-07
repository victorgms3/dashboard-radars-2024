# -*- coding: utf-8 -*-
"""
app.py : Dashboard « Excès de vitesse, radars et accidents en France (2024) »
==============================================================================
Lancement :  streamlit run app.py

Le dashboard lit les fichiers légers du dossier « donnees_preparees »
(créés une seule fois par preparation_donnees.py).

Pages :
  1. Accueil                  : présentation et chiffres clés
  2. Carte des excès          : où roule-t-on trop vite ? (carte interactive + filtres)
  3. Jours et heures          : quand roule-t-on trop vite ?
  4. Radars et accidents      : effet des radars fixes, accidents près des radars
  5. Conclusion               : mon analyse (bonus)
  6. Données et méthode       : sources, nettoyage, limites
"""

import json
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Excès de vitesse et radars 2024", page_icon="🚗", layout="wide")

# ---------------------------------------------------------------------------
# CONSTANTES
# ---------------------------------------------------------------------------
DOSSIER_DONNEES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "donnees_preparees")

# Couleurs (palette testée pour les daltoniens) et échelle « chaleur » pour les taux d'excès
BLEU = "#2a78d6"
ORANGE = "#eb6834"
VERT_EAU = "#1baf7a"
GRIS = "#898781"
ENCRE = "#0b0b0b"
ECHELLE_EXCES = "YlOrRd"  # jaune clair (peu d'excès) -> rouge foncé (beaucoup d'excès)

MOIS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
        "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
TRANCHES = ["Nuit (22h-6h)", "Matin (6h-10h)", "Journée (10h-16h)", "Soir (16h-22h)"]
LIMITES = [50, 70, 80, 90, 110, 130]
SEUILS = [1, 5, 10, 20, 30, 50]
GRAVITES = ["Mortel", "Grave", "Léger"]  # gravité de la victime la plus touchée
# Gravité = ordre croissant : du bleu clair (léger) au bleu foncé (mortel)
COULEUR_GRAVITE = {"Léger": "#86b6ef", "Grave": "#2a78d6", "Mortel": "#184f95"}
COLONNES_COMPTEURS = ["nb_releves", "somme_mesure", "somme_depassement"] + [f"exces_{s}" for s in SEUILS]

TOUTES_REGIONS = "Toutes les régions"
TOUS_DEPARTEMENTS = "Tous les départements"

MIN_RELEVES_CARREAU = 20   # en dessous, un carreau n'est pas coloré (pas assez de mesures)
MIN_RELEVES_CLASSEMENT = 200  # minimum pour entrer dans le classement des zones

# Regroupement des 7 types de radars en 3 familles (3 couleurs maximum sur une carte)
FAMILLE_RADAR = {
    "ETF": "Radar de vitesse", "ETD": "Radar de vitesse", "ETT": "Radar de vitesse",
    "ETVM": "Radar de vitesse", "ETU": "Radar de vitesse",
    "ETFR": "Radar feu rouge", "ETPN": "Radar passage à niveau",
}
COULEUR_FAMILLE = {"Radar de vitesse": BLEU, "Radar feu rouge": ORANGE, "Radar passage à niveau": VERT_EAU}


# ---------------------------------------------------------------------------
# CHARGEMENT DES DONNÉES (une seule fois grâce au cache)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Chargement des données…")
def charger_donnees():
    """Lit les fichiers préparés. Le cache évite de les relire à chaque clic.

    st.cache_resource garde UNE copie en mémoire, partagée : on ne modifie donc
    jamais ces tables directement, on travaille toujours sur des copies filtrées.
    """
    def lire(nom):
        return pd.read_parquet(os.path.join(DOSSIER_DONNEES, nom))

    carte = lire("vitesses_carte.parquet")
    horaire = lire("vitesses_horaires.parquet")
    distance = lire("vitesses_distance_radar.parquet")
    for table in [carte, horaire, distance]:
        # Les compteurs sont stockés en int32 (fichiers plus légers) : on passe en int64
        # pour que les grandes sommes ne débordent jamais.
        table[COLONNES_COMPTEURS] = table[COLONNES_COMPTEURS].astype("int64")
        for colonne in ["dep", "region", "departement"]:
            table[colonne] = table[colonne].astype("category")
    carte["tranche"] = carte["tranche"].astype("category")
    # Stockée en int8 (de -128 à 127) : multipliée par 100, elle déborderait. On l'agrandit.
    distance["distance_radar_100m"] = distance["distance_radar_100m"].astype("int64")

    accidents = lire("accidents.parquet")
    radars = lire("radars_fixes.parquet")
    radars["famille"] = radars["type_code"].map(FAMILLE_RADAR)
    with open(os.path.join(DOSSIER_DONNEES, "rapport_nettoyage.json"), encoding="utf-8") as f:
        rapport = json.load(f)

    # Régions et départements où les voitures radars ont vraiment circulé
    deps_couverts = rapport["departements_couverts"]
    lieux_couverts = (carte[carte["dep"].isin(deps_couverts)][["region", "departement"]]
                      .drop_duplicates().sort_values(["region", "departement"]))
    return {
        "carte": carte, "horaire": horaire, "distance": distance,
        "accidents": accidents, "radars": radars, "rapport": rapport,
        "lieux_couverts": lieux_couverts,
    }


# ---------------------------------------------------------------------------
# PETITS OUTILS RÉUTILISÉS PAR TOUTES LES PAGES
# ---------------------------------------------------------------------------
def fr(nombre, decimales=0):
    """Écrit un nombre à la française : 1234567.8 -> '1 234 567,8'."""
    texte = f"{nombre:,.{decimales}f}"
    return texte.replace(",", " ").replace(".", ",")


def pourcentage(partie, total):
    return 100 * partie / total if total else 0.0


def totaux(df, seuil):
    """Indicateurs globaux d'un tableau de compteurs (déjà filtré)."""
    somme = df[COLONNES_COMPTEURS].sum()
    n = somme["nb_releves"]
    return {
        "releves": n,
        "taux_exces": pourcentage(somme[f"exces_{seuil}"], n),
        "vitesse_moyenne": somme["somme_mesure"] / n if n else 0,
        # « Quand un conducteur dépasse, il dépasse en moyenne de… »
        "depassement_moyen": somme["somme_depassement"] / somme["exces_1"] if somme["exces_1"] else 0,
    }


def agreger(df, colonnes, seuil):
    """Additionne les compteurs par groupe, puis calcule le taux d'excès et la vitesse moyenne."""
    res = df.groupby(colonnes, observed=True)[COLONNES_COMPTEURS].sum().reset_index()
    res["nb_exces"] = res[f"exces_{seuil}"]
    res["taux_exces"] = 100 * res["nb_exces"] / res["nb_releves"]
    res["vitesse_moyenne"] = res["somme_mesure"] / res["nb_releves"]
    return res


def filtrer_lieu(df, region, departement):
    """Garde les lignes de la région ou du département choisi."""
    if departement != TOUS_DEPARTEMENTS:
        return df[df["departement"] == departement]
    if region != TOUTES_REGIONS:
        return df[df["region"] == region]
    return df


def choisir_lieu(cle, lieux):
    """Deux menus déroulants liés : la liste des départements dépend de la région choisie."""
    regions = sorted(lieux["region"].unique())
    region = st.selectbox("Région", [TOUTES_REGIONS] + regions, key=f"region_{cle}")
    if region == TOUTES_REGIONS:
        departements = sorted(lieux["departement"].unique())
    else:
        departements = sorted(lieux.loc[lieux["region"] == region, "departement"].unique())
    departement = st.selectbox("Département", [TOUS_DEPARTEMENTS] + departements, key=f"dep_{cle}")
    return region, departement


def choisir_seuil(cle):
    return st.select_slider(
        "Compter comme excès à partir de",
        options=SEUILS, value=1, key=f"seuil_{cle}",
        format_func=lambda s: f"+{s} km/h",
        help="+1 km/h = toute vitesse au-dessus de la limite. "
             "Monter le seuil permet de ne garder que les gros excès.",
    )


def choisir_limites(cle):
    return st.pills(
        "Vitesse autorisée sur la route", LIMITES, selection_mode="multi", default=LIMITES,
        key=f"limites_{cle}", format_func=lambda v: f"{v} km/h",
    )


def nom_du_lieu(region, departement, sans_filtre="zones couvertes par les voitures radars"):
    if departement != TOUS_DEPARTEMENTS:
        return departement
    if region != TOUTES_REGIONS:
        return region
    return sans_filtre


def zoom_et_centre(lat, lon, region, departement):
    """Choisit le niveau de zoom de la carte selon le lieu sélectionné."""
    if len(lat) == 0:
        return 4.8, {"lat": 46.6, "lon": 2.4}
    centre = {"lat": float(lat.mean()), "lon": float(lon.mean())}
    if departement != TOUS_DEPARTEMENTS:
        return 7.8, centre
    if region != TOUTES_REGIONS:
        return 6.3, centre
    return 4.8, {"lat": 46.6, "lon": 2.4}


def mettre_en_forme(fig, hauteur=380):
    """Réglages communs à tous les graphiques : séparateurs français, marges, légende."""
    fig.update_layout(
        separators=", ",  # virgule décimale, espace pour les milliers
        height=hauteur,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title_text=""),
        hoverlabel=dict(font_size=13),
    )
    return fig


def message_vide(texte):
    st.info(f"ℹ️ {texte}")


def texte_survol_accidents(acc):
    """Textes affichés au survol d'un accident : date, route, lieu, gravité, victimes."""
    victimes = ("Tués : " + acc["nb_tues"].astype(str)
                + " · Blessés hospitalisés : " + acc["nb_blesses_hospitalises"].astype(str)
                + " · Blessés légers : " + acc["nb_blesses_legers"].astype(str))
    return pd.DataFrame({
        "date": acc["date"].dt.strftime("%d/%m/%Y"),
        "route": acc["type_route"].astype(str),
        "lieu": acc["agglomeration"].astype(str),
        "gravite": acc["gravite"].str.lower(),
        "victimes": victimes,
    }).to_numpy()


# ---------------------------------------------------------------------------
# CALCULS RÉUTILISÉS (page Radars et page Conclusion)
# ---------------------------------------------------------------------------
def courbe_effet_radar(distance_df, seuil):
    """Taux d'excès selon la distance au radar fixe le plus proche (tranches de 100 m)."""
    courbe = agreger(distance_df, ["distance_radar_100m"], seuil)
    loin = courbe[courbe["distance_radar_100m"] >= 20]  # 2 km et plus = « loin d'un radar »
    taux_loin = pourcentage(loin["nb_exces"].sum(), loin["nb_releves"].sum())
    proche = courbe[courbe["distance_radar_100m"] < 50].copy()  # on trace de 0 à 5 km
    proche["distance_km"] = (proche["distance_radar_100m"] * 100 + 50) / 1000  # milieu de la tranche
    return proche, taux_loin


def graphique_effet_radar(courbe, taux_loin, seuil):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=courbe["distance_km"], y=courbe["taux_exces"], mode="lines+markers",
        line=dict(color=BLEU, width=2), marker=dict(size=6, color=BLEU),
        customdata=courbe[["nb_releves"]],
        hovertemplate="Entre %{x:.2f} km du radar<br><b>%{y:.1f} %</b> des véhicules en excès"
                      "<br>%{customdata[0]:,} relevés<extra></extra>",
        name="Part des véhicules en excès",
    ))
    fig.add_hline(y=taux_loin, line=dict(color=GRIS, width=1),
                  annotation_text=f"Loin des radars (2 km et +) : {fr(taux_loin, 1)} %",
                  annotation_position="bottom right")
    fig.update_xaxes(title="Distance au radar fixe le plus proche (km)", range=[0, 5])
    fig.update_yaxes(title=f"% de véhicules à +{seuil} km/h ou plus", rangemode="tozero")
    return mettre_en_forme(fig, 400)


def distance_de_retour(courbe, taux_loin):
    """Distance à partir de laquelle le taux d'excès revient à 90 % de son niveau « loin des radars »."""
    revenu = courbe[courbe["taux_exces"] >= 0.9 * taux_loin]
    return float(revenu["distance_km"].iloc[0]) if len(revenu) else None


# ---------------------------------------------------------------------------
# PAGE 1 : ACCUEIL
# ---------------------------------------------------------------------------
def page_accueil():
    d = charger_donnees()
    st.title("🚗 Excès de vitesse, radars et accidents en France (2024)")
    st.markdown(
        "Ce tableau de bord permet d'explorer **9,6 millions de vitesses** relevées en 2024 par les "
        "voitures radars banalisées, de les comparer à l'emplacement des **radars fixes** et des "
        "**accidents de la route**. Aucune connaissance technique n'est nécessaire : il suffit "
        "d'utiliser les filtres dans le panneau de gauche."
    )

    t = totaux(d["carte"], 1)
    t10 = totaux(d["carte"], 10)
    nb_radars_vitesse = int(d["radars"]["controle_vitesse"].sum())
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Vitesses relevées", fr(t["releves"]), border=True)
    col2.metric("Au-dessus de la limite", f"{fr(t['taux_exces'], 1)} %", border=True,
                help=f"Dont {fr(t10['taux_exces'], 1)} % à +10 km/h ou plus.")
    col3.metric("Radars fixes de vitesse", fr(nb_radars_vitesse), border=True,
                help="France métropolitaine, hors radars feux rouges et passages à niveau.")
    col4.metric("Accidents corporels", fr(len(d["accidents"])), border=True,
                help=f"France métropolitaine, année 2024. Dont {fr((d['accidents']['gravite'] == 'Mortel').sum())} "
                     f"accidents mortels ({fr(d['accidents']['nb_tues'].sum())} personnes tuées).")

    st.subheader("Comment utiliser ce tableau de bord ?")
    st.markdown(
        "- **🗺️ Carte des excès** : où les conducteurs dépassent-ils le plus la limite ? "
        "Choisissez une région, une période, un type de route.\n"
        "- **🕒 Jours et heures** : à quels moments de la semaine roule-t-on trop vite ?\n"
        "- **📡 Radars et accidents** : les conducteurs ralentissent-ils près des radars fixes ? "
        "Y a-t-il moins d'accidents autour ?\n"
        "- **💡 Conclusion** : ce qu'il faut retenir de l'analyse.\n"
        "- **📋 Données et méthode** : d'où viennent les chiffres et comment ils ont été nettoyés."
    )

    st.subheader("Où les voitures radars ont-elles roulé ?")
    par_region = agreger(d["carte"], ["region"], 1).sort_values("nb_releves")
    par_region = par_region[par_region["nb_releves"] >= 10_000]
    fig = px.bar(par_region, x="nb_releves", y="region", orientation="h",
                 color_discrete_sequence=[BLEU], text="nb_releves")
    fig.update_traces(texttemplate="%{text:,}", textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}<br>%{x:,} relevés<extra></extra>")
    fig.update_xaxes(title="Nombre de vitesses relevées en 2024")
    fig.update_yaxes(title="")
    st.plotly_chart(mettre_en_forme(fig, 360))
    st.caption(
        "En 2024, les voitures radars à conduite externalisée ne circulaient que dans 8 régions. "
        "L'Île-de-France, Auvergne-Rhône-Alpes, l'Occitanie, Provence-Alpes-Côte d'Azur et la Corse "
        "ne sont pas couvertes : les cartes de vitesse y sont donc vides."
    )


# ---------------------------------------------------------------------------
# PAGE 2 : CARTE DES EXCÈS DE VITESSE (graphique dynamique principal)
# ---------------------------------------------------------------------------
def page_carte():
    d = charger_donnees()
    st.title("🗺️ Où roule-t-on trop vite ?")
    st.caption("Chaque point coloré représente une zone d'environ 2 km sur 2 km. "
               "Plus il est rouge, plus la part de conducteurs au-dessus de la limite est forte.")

    with st.sidebar:
        st.header("Filtres")
        region, departement = choisir_lieu("carte", d["lieux_couverts"])
        mois_debut, mois_fin = st.select_slider("Période", options=MOIS, value=(MOIS[0], MOIS[-1]))
        tranches = st.pills("Moment de la journée", TRANCHES, selection_mode="multi", default=TRANCHES)
        limites = choisir_limites("carte")
        seuil = choisir_seuil("carte")
        st.divider()
        indicateur = st.radio("Couleur de la carte", ["Part de conducteurs en excès", "Nombre d'excès"])
        voir_radars = st.checkbox("Afficher les radars fixes de vitesse", value=True)
        voir_accidents = st.checkbox("Afficher les accidents", value=False)
        gravites = GRAVITES
        if voir_accidents:
            gravites = st.pills("Gravité des accidents", GRAVITES, selection_mode="multi", default=GRAVITES,
                                help="Mortel : au moins une personne tuée. Grave : au moins un blessé "
                                     "hospitalisé plus de 24 h. Léger : uniquement des blessés légers.")

    if not tranches or not limites:
        message_vide("Sélectionnez au moins un moment de la journée et une vitesse autorisée.")
        return

    numeros_mois = list(range(MOIS.index(mois_debut) + 1, MOIS.index(mois_fin) + 2))
    carte = d["carte"]
    selection = carte[
        carte["mois"].isin(numeros_mois)
        & carte["tranche"].isin(tranches)
        & carte["limite"].isin(limites)
    ]
    selection = filtrer_lieu(selection, region, departement)
    if selection.empty:
        message_vide("Aucune vitesse relevée avec ces filtres. Élargissez la période ou la zone.")
        return

    # --- Indicateurs en haut de page
    t = totaux(selection, seuil)
    reference = totaux(carte[carte["mois"].isin(numeros_mois) & carte["tranche"].isin(tranches)
                             & carte["limite"].isin(limites)], seuil)
    ecart = None
    if region != TOUTES_REGIONS or departement != TOUS_DEPARTEMENTS:
        ecart = f"{t['taux_exces'] - reference['taux_exces']:+.1f} pts vs ensemble".replace(".", ",")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Vitesses relevées", fr(t["releves"]), border=True)
    col2.metric(f"Conducteurs à +{seuil} km/h ou plus", f"{fr(t['taux_exces'], 1)} %", delta=ecart,
                delta_color="inverse", border=True,
                help="Comparé à l'ensemble des zones couvertes, avec les mêmes filtres.")
    col3.metric("Vitesse moyenne", f"{fr(t['vitesse_moyenne'])} km/h", border=True)
    col4.metric("Dépassement moyen", f"+{fr(t['depassement_moyen'], 1)} km/h", border=True,
                help="Quand un conducteur est au-dessus de la limite, il la dépasse en moyenne de…")

    # --- Carte
    zones = agreger(selection, ["lat_c", "lon_c", "departement"], seuil)
    if indicateur == "Part de conducteurs en excès":
        zones = zones[zones["nb_releves"] >= MIN_RELEVES_CARREAU]
        colonne_couleur, titre_couleur = "taux_exces", "% en excès"
    else:
        colonne_couleur, titre_couleur = "nb_exces", "Nombre d'excès"
    # Échelle de couleurs du 5e au 95e centile : quelques zones extrêmes n'écrasent pas les autres
    if len(zones):
        bornes = (zones[colonne_couleur].quantile(0.05), max(zones[colonne_couleur].quantile(0.95), 1))
    else:
        bornes = (0, 1)

    zoom, centre = zoom_et_centre(zones["lat_c"], zones["lon_c"], region, departement)
    taille_point = {4.8: 4, 6.3: 7, 7.8: 11}[zoom]
    fig = px.scatter_map(
        zones, lat="lat_c", lon="lon_c", color=colonne_couleur,
        color_continuous_scale=ECHELLE_EXCES, range_color=bornes,
        custom_data=["departement", "nb_releves", "taux_exces", "vitesse_moyenne"],
        zoom=zoom, center=centre, map_style="carto-positron",
    )
    fig.update_traces(
        marker=dict(size=taille_point, opacity=0.85),
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:,} vitesses relevées"
                      f"<br><b>%{{customdata[2]:.1f}} %</b> à +{seuil} km/h ou plus"
                      "<br>Vitesse moyenne : %{customdata[3]:.0f} km/h<extra></extra>",
        name="Zones",
    )
    if voir_radars:
        radars = d["radars"]
        # Uniquement les radars de vitesse situés dans les départements parcourus par les voitures radars
        radars = radars[radars["controle_vitesse"] & radars["dep"].isin(d["rapport"]["departements_couverts"])]
        radars = filtrer_lieu(radars, region, departement)
        fig.add_trace(go.Scattermap(
            lat=radars["lat"], lon=radars["lon"], mode="markers", name="Radar fixe de vitesse",
            marker=dict(size=3 if zoom < 6 else taille_point + 3, color=ENCRE, opacity=0.8),
            customdata=radars[["type", "vma_texte"]],
            hovertemplate="<b>%{customdata[0]}</b><br>Limite contrôlée : %{customdata[1]}<extra></extra>",
        ))
    if voir_accidents:
        acc = d["accidents"]
        acc = acc[acc["mois"].isin(numeros_mois) & acc["dep_couvert_voitures_radars"]
                  & acc["gravite"].isin(gravites or [])]
        acc = filtrer_lieu(acc, region, departement)
        fig.add_trace(go.Scattermap(
            lat=acc["lat"], lon=acc["lon"], mode="markers", name="Accident corporel",
            marker=dict(size=max(3, taille_point - 2), color=BLEU, opacity=0.7),
            customdata=texte_survol_accidents(acc),
            hovertemplate="<b>Accident %{customdata[3]} du %{customdata[0]}</b><br>%{customdata[1]}"
                          "<br>%{customdata[2]}<br>%{customdata[4]}<extra></extra>",
        ))
    fig.update_layout(
        height=620, margin=dict(l=0, r=0, t=0, b=0),
        coloraxis_colorbar=dict(title=titre_couleur, thickness=12),
        legend=dict(orientation="h", yanchor="bottom", y=0.01, xanchor="left", x=0.01,
                    bgcolor="rgba(255,255,255,0.85)"),
        separators=", ",
    )
    st.plotly_chart(fig, config={"scrollZoom": True})
    if indicateur == "Part de conducteurs en excès":
        st.caption(f"Seules les zones avec au moins {MIN_RELEVES_CARREAU} vitesses relevées sont colorées, "
                   "pour qu'un seul conducteur ne fasse pas passer une zone à 100 %. "
                   "Molette ou pincement pour zoomer, survol pour le détail.")

    # --- Classement des zones les plus problématiques
    st.subheader("🔟 Les 10 zones où l'on dépasse le plus souvent")
    classement = zones_classement(selection, seuil)
    if classement.empty:
        message_vide(f"Pas assez de mesures pour établir un classement (il faut {MIN_RELEVES_CLASSEMENT} "
                     "relevés par zone). Élargissez la période ou la zone.")
    else:
        st.dataframe(
            classement, hide_index=True,
            column_config={
                "Part en excès": st.column_config.ProgressColumn(
                    f"À +{seuil} km/h ou plus", format="%.1f %%", min_value=0, max_value=100),
                "Relevés": st.column_config.NumberColumn(format="localized"),
                "Vitesse moyenne": st.column_config.NumberColumn(format="%d km/h"),
                "Voir": st.column_config.LinkColumn("Voir l'endroit", display_text="Ouvrir la carte ↗"),
            },
        )

    # --- Deux graphiques complémentaires
    gauche, droite = st.columns(2)
    with gauche:
        st.subheader("Mois par mois")
        par_mois = agreger(selection, ["mois"], seuil)
        par_mois["nom_mois"] = par_mois["mois"].map(lambda m: MOIS[m - 1])
        fig = px.line(par_mois, x="nom_mois", y="taux_exces", markers=True, color_discrete_sequence=[BLEU])
        fig.update_traces(line_width=2, marker_size=8, customdata=par_mois[["nb_releves"]],
                          hovertemplate="%{x}<br><b>%{y:.1f} %</b> en excès<br>"
                                        "%{customdata[0]:,} relevés<extra></extra>")
        fig.update_xaxes(title="")
        fig.update_yaxes(title=f"% à +{seuil} km/h ou plus", rangemode="tozero")
        st.plotly_chart(mettre_en_forme(fig))
    with droite:
        st.subheader("Selon la vitesse autorisée")
        par_limite = agreger(selection, ["limite"], seuil)
        par_limite["route"] = par_limite["limite"].map(lambda v: f"{v} km/h")
        fig = px.bar(par_limite, x="route", y="taux_exces", text="taux_exces", color_discrete_sequence=[BLEU])
        fig.update_traces(texttemplate="%{text:.1f} %", textposition="outside", cliponaxis=False,
                          customdata=par_limite[["nb_releves"]],
                          hovertemplate="Routes à %{x}<br><b>%{y:.1f} %</b> en excès<br>"
                                        "%{customdata[0]:,} relevés<extra></extra>")
        fig.update_xaxes(title="")
        fig.update_yaxes(title=f"% à +{seuil} km/h ou plus", rangemode="tozero")
        st.plotly_chart(mettre_en_forme(fig))

    with st.expander("📄 Voir les chiffres sous forme de tableau"):
        tableau = par_limite[["route", "nb_releves", "taux_exces", "vitesse_moyenne"]].rename(columns={
            "route": "Vitesse autorisée", "nb_releves": "Relevés",
            "taux_exces": f"% à +{seuil} km/h ou plus", "vitesse_moyenne": "Vitesse moyenne (km/h)"})
        st.dataframe(tableau.round(1), hide_index=True)


def zones_classement(selection, seuil):
    """Les 10 zones (avec assez de mesures) où la part d'excès est la plus forte."""
    zones = agreger(selection, ["lat_c", "lon_c", "departement"], seuil)
    zones = zones[zones["nb_releves"] >= MIN_RELEVES_CLASSEMENT]
    zones = zones.sort_values("taux_exces", ascending=False).head(10)
    return pd.DataFrame({
        "Département": zones["departement"].astype(str),
        "Relevés": zones["nb_releves"],
        "Part en excès": zones["taux_exces"].round(1),
        "Vitesse moyenne": zones["vitesse_moyenne"].round(0),
        "Voir": [f"https://www.google.com/maps/search/?api=1&query={lat:.4f},{lon:.4f}"
                 for lat, lon in zip(zones["lat_c"], zones["lon_c"])],
    })


# ---------------------------------------------------------------------------
# PAGE 3 : JOURS ET HEURES
# ---------------------------------------------------------------------------
def page_horaires():
    d = charger_donnees()
    st.title("🕒 Quand roule-t-on trop vite ?")
    st.caption("Part des conducteurs au-dessus de la limite selon le jour de la semaine et l'heure.")

    with st.sidebar:
        st.header("Filtres")
        region, departement = choisir_lieu("horaires", d["lieux_couverts"])
        limites = choisir_limites("horaires")
        seuil = choisir_seuil("horaires")

    if not limites:
        message_vide("Sélectionnez au moins une vitesse autorisée.")
        return
    selection = filtrer_lieu(d["horaire"][d["horaire"]["limite"].isin(limites)], region, departement)
    if selection.empty:
        message_vide("Aucune vitesse relevée avec ces filtres.")
        return

    grille = agreger(selection, ["jour_semaine", "heure"], seuil)
    # Moins de 30 mesures dans une case : pas fiable, on la laisse vide
    grille.loc[grille["nb_releves"] < 30, "taux_exces"] = None
    taux = grille.pivot(index="jour_semaine", columns="heure", values="taux_exces").reindex(
        index=range(7), columns=range(24))
    nombre = grille.pivot(index="jour_semaine", columns="heure", values="nb_releves").reindex(
        index=range(7), columns=range(24)).fillna(0)

    # Indicateurs : moment le plus et le moins « à risque »
    # (on exige 200 mesures pour ne pas désigner un créneau sur la foi de quelques voitures)
    fiables = grille[grille["nb_releves"] >= 200]
    if fiables.empty:
        fiables = grille.dropna(subset=["taux_exces"])
    if fiables.empty:
        message_vide("Pas assez de mesures dans cette zone pour comparer les jours et les heures.")
        return
    pire =fiables.loc[fiables["taux_exces"].idxmax()]
    meilleur = fiables.loc[fiables["taux_exces"].idxmin()]
    semaine = totaux(selection[selection["jour_semaine"] < 5], seuil)["taux_exces"]
    week_end = totaux(selection[selection["jour_semaine"] >= 5], seuil)["taux_exces"]
    col1, col2, col3 = st.columns(3)
    col1.metric("Moment où l'on dépasse le plus",
                f"{JOURS[int(pire['jour_semaine'])]} {int(pire['heure'])}h", border=True,
                help=f"{fr(pire['taux_exces'], 1)} % de conducteurs à +{seuil} km/h ou plus.")
    col2.metric("Moment où l'on dépasse le moins",
                f"{JOURS[int(meilleur['jour_semaine'])]} {int(meilleur['heure'])}h", border=True,
                help=f"{fr(meilleur['taux_exces'], 1)} % de conducteurs à +{seuil} km/h ou plus.")
    col3.metric("Week-end comparé à la semaine", f"{fr(week_end, 1)} %",
                delta=f"{week_end - semaine:+.1f} pts".replace(".", ","), delta_color="inverse", border=True,
                help=f"En semaine : {fr(semaine, 1)} %.")

    fig = go.Figure(go.Heatmap(
        z=taux.to_numpy(), x=[f"{h}h" for h in range(24)], y=JOURS,
        customdata=nombre.to_numpy(), colorscale=ECHELLE_EXCES, xgap=2, ygap=2,
        colorbar=dict(title="% en excès", thickness=12),
        hovertemplate="%{y} à %{x}<br><b>%{z:.1f} %</b> en excès<br>%{customdata:,} relevés<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(mettre_en_forme(fig, 420))
    st.caption("Les cases vides correspondent à moins de 30 mesures (surtout entre 2h et 5h du matin : "
               "les voitures radars roulent peu la nuit).")

    st.subheader("Heure par heure")
    par_heure = agreger(selection, ["heure"], seuil)
    par_heure = par_heure[par_heure["nb_releves"] >= 30]
    fig = px.line(par_heure, x="heure", y="taux_exces", markers=True, color_discrete_sequence=[BLEU])
    fig.update_traces(line_width=2, marker_size=8, customdata=par_heure[["nb_releves"]],
                      hovertemplate="%{x}h<br><b>%{y:.1f} %</b> en excès<br>"
                                    "%{customdata[0]:,} relevés<extra></extra>")
    fig.update_xaxes(title="Heure de la journée", dtick=2, ticksuffix="h")
    fig.update_yaxes(title=f"% à +{seuil} km/h ou plus", rangemode="tozero")
    st.plotly_chart(mettre_en_forme(fig))

    with st.expander("📄 Voir les chiffres sous forme de tableau"):
        tableau = taux.round(1)
        tableau.index = JOURS
        tableau.columns = [f"{h}h" for h in range(24)]
        st.dataframe(tableau)


# ---------------------------------------------------------------------------
# PAGE 4 : RADARS ET ACCIDENTS
# ---------------------------------------------------------------------------
def page_radars():
    d = charger_donnees()
    st.title("📡 Les radars fixes font-ils ralentir ? Et les accidents ?")

    with st.sidebar:
        st.header("Filtres")
        region, departement = choisir_lieu("radars", d["lieux_couverts"])
        limites = choisir_limites("radars")
        seuil = choisir_seuil("radars")

    if not limites:
        message_vide("Sélectionnez au moins une vitesse autorisée.")
        return
    lieu = nom_du_lieu(region, departement)

    # --- 1. L'effet radar
    st.subheader("1. Les conducteurs ralentissent… mais seulement autour du radar")
    distance_sel = filtrer_lieu(d["distance"][d["distance"]["limite"].isin(limites)], region, departement)
    if distance_sel.empty:
        message_vide("Aucune vitesse relevée avec ces filtres.")
        return
    courbe, taux_loin = courbe_effet_radar(distance_sel, seuil)
    tout_pres = courbe[courbe["distance_radar_100m"] == 0]
    taux_pres = float(tout_pres["taux_exces"].iloc[0]) if len(tout_pres) else 0.0
    retour = distance_de_retour(courbe, taux_loin)
    col1, col2, col3 = st.columns(3)
    col1.metric("À moins de 100 m d'un radar", f"{fr(taux_pres, 1)} %", border=True,
                help=f"Part des conducteurs à +{seuil} km/h ou plus.")
    col2.metric("À plus de 2 km d'un radar", f"{fr(taux_loin, 1)} %", border=True)
    col3.metric("L'effet disparaît après", f"≈ {fr(retour, 1)} km" if retour else "non mesurable", border=True,
                help="Distance à partir de laquelle on retrouve 90 % du niveau d'excès « loin des radars ».")
    st.plotly_chart(graphique_effet_radar(courbe, taux_loin, seuil))
    st.caption("Lecture : chaque point regroupe les vitesses relevées dans une tranche de 100 m autour "
               "du radar fixe le plus proche (dans les deux sens de circulation, à vol d'oiseau).")

    # --- 2. Carte des radars et des accidents
    st.subheader("2. Où sont les radars fixes ?")
    familles = st.pills("Types de radars à afficher", list(COULEUR_FAMILLE), selection_mode="multi",
                        default=list(COULEUR_FAMILLE))
    voir_accidents = st.checkbox("Afficher aussi les accidents de 2024", value=False)
    radars = filtrer_lieu(d["radars"], region, departement)
    radars = radars[radars["famille"].isin(familles or [])]
    zoom, centre = zoom_et_centre(radars["lat"], radars["lon"], region, departement)
    fig = go.Figure()
    if voir_accidents:
        acc = filtrer_lieu(d["accidents"], region, departement)
        fig.add_trace(go.Scattermap(
            lat=acc["lat"], lon=acc["lon"], mode="markers", name="Accident corporel",
            marker=dict(size=4, color=GRIS, opacity=0.5),
            customdata=texte_survol_accidents(acc),
            hovertemplate="Accident %{customdata[3]} du %{customdata[0]}<br>%{customdata[1]}"
                          "<br>%{customdata[4]}<extra></extra>",
        ))
    for famille in familles or []:
        groupe = radars[radars["famille"] == famille]
        fig.add_trace(go.Scattermap(
            lat=groupe["lat"], lon=groupe["lon"], mode="markers", name=famille,
            marker=dict(size=8, color=COULEUR_FAMILLE[famille]),
            customdata=groupe[["type", "vma_texte", "annee_mise_en_service", "departement"]].astype(str),
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[3]}<br>Limite : %{customdata[1]}"
                          "<br>En service depuis %{customdata[2]}<extra></extra>",
        ))
    fig.update_layout(
        map=dict(style="carto-positron", zoom=zoom, center=centre), height=560,
        margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=0.01, xanchor="left", x=0.01,
                    bgcolor="rgba(255,255,255,0.85)"),
    )
    st.plotly_chart(fig, config={"scrollZoom": True})

    gauche, droite = st.columns(2)
    with gauche:
        par_type = radars.groupby("type").size().reset_index(name="nombre").sort_values("nombre")
        fig = px.bar(par_type, x="nombre", y="type", orientation="h", text="nombre",
                     color_discrete_sequence=[BLEU],
                     title=f"Radars par type ({nom_du_lieu(region, departement, 'France métropolitaine')})")
        fig.update_traces(textposition="outside", cliponaxis=False,
                          hovertemplate="%{y}<br>%{x} radars<extra></extra>")
        fig.update_xaxes(title="")
        fig.update_yaxes(title="")
        st.plotly_chart(mettre_en_forme(fig, 340))
    with droite:
        par_annee = radars.groupby("annee_mise_en_service").size().reset_index(name="nombre")
        fig = px.bar(par_annee, x="annee_mise_en_service", y="nombre", color_discrete_sequence=[BLEU],
                     title="Année de mise en service des radars encore en place")
        fig.update_traces(hovertemplate="%{x} : %{y} radars<extra></extra>")
        fig.update_xaxes(title="", dtick=2)
        fig.update_yaxes(title="")
        st.plotly_chart(mettre_en_forme(fig, 340))

    # --- 3. Les accidents sont-ils moins nombreux près des radars ?
    st.subheader("3. Y a-t-il moins d'accidents près des radars ?")
    st.markdown(
        "Compter les accidents près des radars ne suffit pas : il faut comparer avec la quantité de "
        "circulation à ces endroits. Faute de mieux, on utilise les **vitesses relevées par les "
        "voitures radars** comme indicateur de circulation : si 7 % des relevés sont faits à moins "
        "de 1 km d'un radar, on « attend » environ 7 % des accidents à moins de 1 km d'un radar."
    )
    gauche, droite = st.columns(2)
    rayon = gauche.slider("Distance autour des radars de vitesse (km)", 0.2, 3.0, 1.0, 0.1)
    choix_gravite = droite.radio("Accidents pris en compte", ["Tous", "Graves ou mortels", "Mortels"],
                                 horizontal=True)
    tous_acc = d["accidents"]
    tous_acc = tous_acc[tous_acc["dep_couvert_voitures_radars"] & (tous_acc["agglomeration"] == "Hors agglomération")]
    tous_acc = filtrer_lieu(tous_acc, region, departement)
    gravites_retenues = {"Tous": GRAVITES, "Graves ou mortels": ["Mortel", "Grave"], "Mortels": ["Mortel"]}
    acc = tous_acc[tous_acc["gravite"].isin(gravites_retenues[choix_gravite])]
    if acc.empty:
        message_vide("Aucun accident de ce type hors agglomération dans cette zone.")
        return
    part_releves = pourcentage(distance_sel.loc[distance_sel["distance_radar_100m"] < rayon * 10, "nb_releves"].sum(),
                               distance_sel["nb_releves"].sum())
    part_accidents = pourcentage((acc["distance_radar_m"] < rayon * 1000).sum(), len(acc))
    nom_accidents = "Accidents hors agglomération" if choix_gravite == "Tous" else \
        f"Accidents {choix_gravite.lower()} hors agglomération"
    col1, col2 = st.columns(2)
    col1.metric(f"Relevés de vitesse à moins de {fr(rayon, 1)} km", f"{fr(part_releves, 1)} %", border=True,
                help="Indicateur de la circulation près des radars.")
    col2.metric(f"{nom_accidents} à moins de {fr(rayon, 1)} km", f"{fr(part_accidents, 1)} %",
                delta=f"{part_accidents - part_releves:+.1f} pts".replace(".", ","), delta_color="inverse",
                border=True, help=f"Calculé sur {fr(len(acc))} accidents ({lieu}).")

    rayons = [r / 10 for r in range(1, 31)]
    comparaison = pd.DataFrame({
        "rayon": rayons * 2,
        "part": [pourcentage(distance_sel.loc[distance_sel["distance_radar_100m"] < r * 10, "nb_releves"].sum(),
                             distance_sel["nb_releves"].sum()) for r in rayons]
                + [pourcentage((acc["distance_radar_m"] < r * 1000).sum(), len(acc)) for r in rayons],
        "serie": ["Relevés de vitesse (circulation)"] * len(rayons) + [nom_accidents] * len(rayons),
    })
    fig = px.line(comparaison, x="rayon", y="part", color="serie", markers=True,
                  color_discrete_map={"Relevés de vitesse (circulation)": BLEU, nom_accidents: ORANGE})
    fig.update_traces(line_width=2, marker_size=6,
                      hovertemplate="À moins de %{x:.1f} km : <b>%{y:.1f} %</b><extra></extra>")
    fig.add_vline(x=rayon, line=dict(color=GRIS, width=1))
    fig.update_xaxes(title="Distance au radar de vitesse le plus proche (km)")
    fig.update_yaxes(title="Part cumulée (%)", rangemode="tozero")
    st.plotly_chart(mettre_en_forme(fig, 400))
    st.caption(
        "Si la courbe orange est sous la bleue, il y a moins d'accidents près des radars que ce que la "
        "circulation laisserait attendre. Attention : les radars sont souvent installés là où il y a eu "
        "des accidents, et les voitures radars ne représentent pas tout le trafic. Ce graphique montre "
        "une association, pas une preuve que le radar évite les accidents."
    )

    # --- 4. Les accidents sont-ils moins graves près des radars ?
    st.subheader("4. Les accidents sont-ils moins graves près des radars ?")
    proche = tous_acc["distance_radar_m"] < rayon * 1000
    groupes = {f"À moins de {fr(rayon, 1)} km d'un radar": tous_acc[proche],
               f"À plus de {fr(rayon, 1)} km": tous_acc[~proche]}
    if min(len(g) for g in groupes.values()) < 30:
        message_vide("Pas assez d'accidents dans cette zone pour comparer leur gravité (30 au minimum de "
                     "chaque côté). Élargissez la zone ou la distance.")
        return
    repartition = pd.DataFrame([
        {"groupe": nom, "gravite": gravite, "part": pourcentage((g["gravite"] == gravite).sum(), len(g)),
         "nombre": int((g["gravite"] == gravite).sum())}
        for nom, g in groupes.items() for gravite in GRAVITES
    ])
    graves_proche, graves_loin = [
        pourcentage(g["gravite"].isin(["Mortel", "Grave"]).sum(), len(g)) for g in groupes.values()]
    col1, col2 = st.columns(2)
    col1.metric(f"Accidents graves ou mortels, à moins de {fr(rayon, 1)} km", f"{fr(graves_proche, 1)} %",
                delta=f"{graves_proche - graves_loin:+.1f} pts".replace(".", ","), delta_color="inverse",
                border=True, help=f"Sur {fr(len(groupes[list(groupes)[0]]))} accidents hors agglomération.")
    col2.metric(f"Accidents graves ou mortels, à plus de {fr(rayon, 1)} km", f"{fr(graves_loin, 1)} %",
                border=True, help=f"Sur {fr(len(groupes[list(groupes)[1]]))} accidents hors agglomération.")
    fig = px.bar(repartition, x="part", y="groupe", color="gravite", orientation="h", text="part",
                 category_orders={"gravite": ["Mortel", "Grave", "Léger"]},
                 color_discrete_map=COULEUR_GRAVITE, custom_data=["nombre"])
    fig.update_traces(texttemplate="%{text:.0f} %", textposition="inside", insidetextanchor="middle",
                      marker_line_width=0,
                      hovertemplate="%{y}<br>%{fullData.name} : <b>%{x:.1f} %</b> (%{customdata[0]:,} accidents)"
                                    "<extra></extra>", textfont_color="white")
    fig.update_traces(selector=dict(name="Léger"), textfont_color=ENCRE)  # texte foncé sur fond clair
    fig.update_xaxes(title="Part des accidents (%)", range=[0, 100])
    fig.update_yaxes(title="", autorange="reversed")  # « À moins de … » en haut
    # Un pourcentage qui ne tient pas dans son segment est masqué (il reste lisible au survol)
    fig.update_layout(bargap=0.35, legend_traceorder="normal", uniformtext_minsize=11, uniformtext_mode="hide")
    st.plotly_chart(mettre_en_forme(fig, 260))
    st.caption(
        "Mortel : au moins une personne tuée (dans les 30 jours). Grave : au moins un blessé hospitalisé plus de "
        "24 h. Léger : uniquement des blessés légers. Près des radars, on roule moins vite, ce qui est cohérent "
        "avec des accidents moins graves. Mais d'autres explications sont possibles : les radars sont souvent "
        "placés à l'entrée des villages ou près des carrefours, où les accidents sont plus fréquents mais se "
        "produisent à vitesse plus faible."
    )


# ---------------------------------------------------------------------------
# PAGE 5 : CONCLUSION (bonus)
# ---------------------------------------------------------------------------
def page_conclusion():
    d = charger_donnees()
    carte, horaire, distance, accidents = d["carte"], d["horaire"], d["distance"], d["accidents"]
    st.title("💡 Conclusion : ce que disent les données")
    st.caption("Toutes les valeurs de cette page sont recalculées à partir des données (année 2024, "
               "zones couvertes par les voitures radars).")

    # Les chiffres utilisés dans le texte
    t1, t10, t30 = totaux(carte, 1), totaux(carte, 10), totaux(carte, 30)
    par_limite = agreger(carte, ["limite"], 1).set_index("limite")
    par_tranche = agreger(carte, ["tranche"], 30).set_index("tranche")
    nuit_gros = par_tranche.loc["Nuit (22h-6h)", "taux_exces"]
    jour_gros = par_tranche.loc["Journée (10h-16h)", "taux_exces"]
    par_tranche1 = agreger(carte, ["tranche"], 1).set_index("tranche")
    semaine = totaux(horaire[horaire["jour_semaine"] < 5], 1)["taux_exces"]
    week_end = totaux(horaire[horaire["jour_semaine"] >= 5], 1)["taux_exces"]
    courbe, taux_loin = courbe_effet_radar(distance, 1)
    taux_pres = float(courbe.loc[courbe["distance_radar_100m"] == 0, "taux_exces"].iloc[0])
    retour = distance_de_retour(courbe, taux_loin)
    par_region = agreger(carte[carte["dep"].isin(d["rapport"]["departements_couverts"])], ["region"], 1)
    pire_region = par_region.loc[par_region["taux_exces"].idxmax()]
    meilleure_region = par_region.loc[par_region["taux_exces"].idxmin()]
    acc = accidents[accidents["dep_couvert_voitures_radars"] & (accidents["agglomeration"] == "Hors agglomération")]
    part_acc_1km = pourcentage((acc["distance_radar_m"] < 1000).sum(), len(acc))
    part_rel_1km = pourcentage(distance.loc[distance["distance_radar_100m"] < 10, "nb_releves"].sum(),
                               distance["nb_releves"].sum())
    # Gravité des accidents selon la distance au radar, et selon le lieu (en ou hors agglomération)
    graves = acc["gravite"].isin(["Mortel", "Grave"])
    pres_1km = acc["distance_radar_m"] < 1000
    part_graves_pres = pourcentage((graves & pres_1km).sum(), pres_1km.sum())
    part_graves_loin = pourcentage((graves & ~pres_1km).sum(), (~pres_1km).sum())
    mortels = accidents["gravite"] == "Mortel"
    hors_agglo = accidents["agglomeration"] == "Hors agglomération"
    part_mortels_hors = pourcentage((mortels & hors_agglo).sum(), hors_agglo.sum())
    part_mortels_agglo = pourcentage((mortels & ~hors_agglo).sum(), (~hors_agglo).sum())
    part_tues_hors = pourcentage(accidents.loc[hors_agglo, "nb_tues"].sum(), accidents["nb_tues"].sum())

    st.header("1. Dépasser la limite est courant, mais souvent de peu")
    col1, col2, col3 = st.columns(3)
    col1.metric("Au-dessus de la limite", f"{fr(t1['taux_exces'], 1)} %", border=True)
    col2.metric("À +10 km/h ou plus", f"{fr(t10['taux_exces'], 1)} %", border=True)
    col3.metric("À +30 km/h ou plus", f"{fr(t30['taux_exces'], 1)} %", border=True)
    st.markdown(
        f"Plus d'un conducteur sur trois ({fr(t1['taux_exces'])} %) roule au-dessus de la limite, mais "
        f"dans la plupart des cas l'excès est léger : en moyenne **+{fr(t1['depassement_moyen'], 1)} km/h**. "
        f"Les gros excès (+30 km/h et plus) restent rares : {fr(t30['taux_exces'], 1)} % des relevés. "
        "Attention : « au-dessus de la limite » ne veut pas dire « flashé », une marge technique "
        "est appliquée avant toute amende."
    )

    st.header("2. Les traversées de villages à 50 km/h sont le point noir")
    st.markdown(
        f"Sur les routes limitées à **50 km/h**, **{fr(par_limite.loc[50, 'taux_exces'])} %** des "
        f"conducteurs dépassent la limite, contre {fr(par_limite.loc[80, 'taux_exces'])} % sur les routes "
        f"à 80 km/h et {fr(par_limite.loc[90, 'taux_exces'])} % sur celles à 90 km/h. Les voitures radars "
        "roulent surtout hors des villes : ces routes à 50 km/h sont donc probablement en majorité des "
        "traversées de villages, où la vitesse est pourtant la plus dangereuse pour les piétons et les cyclistes."
    )
    par_limite_g = par_limite.reset_index()
    par_limite_g["route"] = par_limite_g["limite"].map(lambda v: f"{v} km/h")
    fig = px.bar(par_limite_g, x="route", y="taux_exces", text="taux_exces", color_discrete_sequence=[BLEU])
    fig.update_traces(texttemplate="%{text:.1f} %", textposition="outside", cliponaxis=False,
                      hovertemplate="Routes à %{x}<br><b>%{y:.1f} %</b> en excès<extra></extra>")
    fig.update_xaxes(title="Vitesse autorisée")
    fig.update_yaxes(title="% au-dessus de la limite", rangemode="tozero")
    st.plotly_chart(mettre_en_forme(fig, 320))

    st.header("3. La nuit et le week-end, on roule plus vite")
    st.markdown(
        f"La nuit (22h-6h), {fr(par_tranche1.loc['Nuit (22h-6h)', 'taux_exces'])} % des conducteurs "
        f"dépassent la limite contre {fr(par_tranche1.loc['Journée (10h-16h)', 'taux_exces'])} % en journée. "
        f"Surtout, les **gros excès** (+30 km/h) y sont **{fr(nuit_gros / jour_gros, 1)} fois plus "
        f"fréquents** ({fr(nuit_gros, 1)} % contre {fr(jour_gros, 1)} %). Le week-end aussi est plus "
        f"rapide : {fr(week_end, 1)} % d'excès contre {fr(semaine, 1)} % en semaine."
    )

    st.header("4. Un radar fixe fait ralentir… sur environ un kilomètre")
    st.markdown(
        f"À moins de 100 m d'un radar fixe, seuls **{fr(taux_pres, 1)} %** des conducteurs dépassent la "
        f"limite. À plus de 2 km, ils sont **{fr(taux_loin, 1)} %**. Mais l'effet est très local : "
        f"dès **{fr(retour, 1)} km** environ, on retrouve presque le niveau habituel. C'est « l'effet "
        "kangourou » : on freine devant le radar, puis on réaccélère."
    )
    st.plotly_chart(graphique_effet_radar(courbe, taux_loin, 1))

    st.header("5. Hors des villes, les accidents sont plus souvent mortels")
    col1, col2, col3 = st.columns(3)
    col1.metric("Accidents mortels hors agglomération", f"{fr(part_mortels_hors, 1)} %", border=True)
    col2.metric("Accidents mortels en agglomération", f"{fr(part_mortels_agglo, 1)} %", border=True)
    col3.metric("Part des tués hors agglomération", f"{fr(part_tues_hors)} %", border=True,
                help=f"Sur {fr(accidents['nb_tues'].sum())} personnes tuées en 2024 (France métropolitaine).")
    st.markdown(
        f"Hors agglomération, **{fr(part_mortels_hors, 1)} %** des accidents sont mortels, contre "
        f"{fr(part_mortels_agglo, 1)} % en ville : il y a moins d'accidents sur les routes de campagne, mais "
        f"ils sont bien plus graves, car on y roule plus vite. Au total, **{fr(part_tues_hors)} % des personnes "
        "tuées** l'ont été hors agglomération, c'est-à-dire précisément sur les routes où circulent les "
        "voitures radars."
    )

    st.header("6. Pas moins d'accidents près des radars, mais des accidents moins graves")
    st.markdown(
        f"Hors agglomération, {fr(part_acc_1km, 1)} % des accidents ont lieu à moins de 1 km d'un radar de "
        f"vitesse, pour {fr(part_rel_1km, 1)} % des relevés de vitesse. Les deux parts sont "
        f"{'très proches' if abs(part_acc_1km - part_rel_1km) < 1.5 else 'différentes'} : on ne peut pas "
        "affirmer qu'il y a **moins** d'accidents autour des radars.\n\n"
        f"En revanche, ils y sont **moins graves** : à moins de 1 km d'un radar, **{fr(part_graves_pres)} %** "
        f"des accidents sont graves ou mortels, contre **{fr(part_graves_loin)} %** plus loin. C'est cohérent "
        "avec le point 4 : près du radar, on roule moins vite, et un choc à plus faible vitesse fait moins de "
        "dégâts. Mais ce n'est pas une preuve : les radars sont aussi souvent placés à l'entrée des villages "
        "ou près des carrefours, où les accidents se produisent à vitesse plus faible de toute façon."
    )

    st.header("7. Des différences entre régions")
    st.markdown(
        f"Région où l'on dépasse le plus souvent : **{pire_region['region']}** "
        f"({fr(pire_region['taux_exces'], 1)} % des conducteurs). Région où l'on dépasse le moins : "
        f"**{meilleure_region['region']}** ({fr(meilleure_region['taux_exces'], 1)} %). Ces écarts "
        "dépendent aussi des routes que les voitures radars ont parcourues dans chaque région."
    )

    st.header("Ce que j'en retiens")
    st.success(
        "- Les **radars fixes** ont un effet réel mais **limité à leurs abords** : on y roule moins vite et "
        "les accidents y sont moins graves, mais seulement sur environ un kilomètre. Pour faire baisser la "
        "vitesse sur toute une route, les contrôles mobiles (voitures radars) et les radars tronçons, "
        "qui mesurent sur plusieurs kilomètres, semblent plus adaptés.\n"
        "- Les efforts de prévention devraient viser en priorité les **routes hors agglomération** (où "
        "meurent la majorité des victimes), les **traversées de villages** et les **nuits et week-ends**, "
        "là où les excès sont les plus fréquents et les plus importants.\n"
        "- Pour mesurer l'effet des radars sur les accidents, il faudrait comparer les accidents **avant "
        "et après** l'installation de chaque radar, sur plusieurs années."
    )

    st.header("Limites de l'analyse")
    st.warning(
        "- Les voitures radars ne couvrent que **8 régions** et surtout les routes hors agglomération : "
        "les résultats ne valent pas pour toute la France ni pour les villes.\n"
        "- Une voiture radar ne mesure que les véhicules qui passent à sa portée sur son trajet : ce n'est pas un comptage "
        "complet de la circulation.\n"
        "- La distance au radar est calculée à vol d'oiseau : un relevé peut être proche d'un radar "
        "situé sur une autre route.\n"
        "- Le département des relevés est estimé par un modèle (k plus proches voisins) fiable à "
        f"{fr(d['rapport']['precision_modele_departement'] * 100, 1)} % : quelques points en bordure "
        "peuvent être attribués au département voisin.\n"
        "- La gravité d'un accident est celle de la victime la plus touchée ; « tué » signifie décédé dans "
        "les 30 jours qui suivent l'accident (définition officielle du fichier BAAC)."
    )


# ---------------------------------------------------------------------------
# PAGE 6 : DONNÉES ET MÉTHODE
# ---------------------------------------------------------------------------
def page_donnees():
    d = charger_donnees()
    r = d["rapport"]
    st.title("📋 Données et méthode")

    st.header("Sources (data.gouv.fr, année 2024)")
    st.markdown(
        "- [Vitesses relevées par les voitures radars à conduite externalisée]"
        "(https://www.data.gouv.fr/datasets/jeux-de-donnees-des-vitesses-relevees-par-les-voitures-radars-a-conduite-externalisee) : "
        "une ligne par véhicule contrôlé (date, position GPS, vitesse mesurée, vitesse autorisée).\n"
        "- [Liste des radars fixes en France](https://www.data.gouv.fr/datasets/liste-des-radars-fixes-en-france) : "
        "type, position, date de mise en service, vitesse contrôlée.\n"
        "- [Accidents corporels de la circulation (fichiers BAAC)]"
        "(https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2025) : "
        "fichiers « caractéristiques » (date, lieu, conditions), « lieux » (type de route, vitesse autorisée) "
        "et « usagers » (une ligne par personne impliquée, avec sa gravité)."
    )

    st.header("Nettoyage effectué")
    etapes = pd.DataFrame([
        ("Vitesses", "Lignes dans le fichier d'origine", r["vitesses_lignes_brutes"]),
        ("Vitesses", f"Mesures supérieures à 200 km/h retirées (erreurs probables)", r["vitesses_aberrantes_retirees"]),
        ("Vitesses", "Positions hors de la France métropolitaine retirées", r["vitesses_hors_metropole_retirees"]),
        ("Vitesses", "Relevés conservés", r["vitesses_conservees"]),
        ("Radars fixes", "Lignes dans le fichier d'origine", r["radars_lignes_brutes"]),
        ("Radars fixes", "Radars sans coordonnées retirés", r["radars_sans_coordonnees_retires"]),
        ("Radars fixes", "Radars d'outre-mer retirés (pas de voitures radars là-bas)", r["radars_hors_metropole_retires"]),
        ("Radars fixes", "Radars sans vitesse contrôlée renseignée (gardés, notés « Non renseignée »)",
         r["radars_vitesse_maximale_manquante"]),
        ("Radars fixes", "Radars conservés", r["radars_conserves"]),
        ("Accidents", "Accidents dans le fichier d'origine", r["accidents_lignes_brutes"]),
        ("Accidents", "Accidents d'outre-mer retirés", r["accidents_hors_metropole_retires"]),
        ("Accidents", "Vitesses autorisées invalides (-1, 500…) remplacées par « inconnue »",
         r["accidents_vitesse_autorisee_invalide"]),
        ("Accidents", "Accidents conservés", r["accidents_conserves"]),
        ("Usagers (victimes)", "Personnes impliquées dans le fichier d'origine", r["usagers_lignes_brutes"]),
        ("Usagers (victimes)", "Personnes sans gravité renseignée", r["usagers_gravite_non_renseignee"]),
    ], columns=["Fichier", "Étape", "Nombre de lignes"])
    st.dataframe(etapes, hide_index=True,
                 column_config={"Nombre de lignes": st.column_config.NumberColumn(format="localized")})

    st.markdown(
        "**Autres transformations :**\n"
        "- la colonne `position` (« latitude longitude » dans un seul texte) a été séparée en deux "
        "nombres ;\n"
        "- les coordonnées des accidents, écrites avec une virgule (« 47,56 »), ont été converties ;\n"
        "- les codes des fichiers (types de radars `ETT`, `ETD`… et codes BAAC de météo, lumière, "
        "type de route) ont été remplacés par des libellés lisibles ;\n"
        "- les 9,6 millions de relevés ont été **regroupés** par zone de 2 km, mois, moment de la "
        "journée et vitesse autorisée : on passe de 535 Mo à quelques Mo, sans perdre d'information "
        "utile pour les graphiques ;\n"
        "- les relevés et les radars n'ayant pas de département, celui-ci a été **estimé** avec un modèle "
        "des k plus proches voisins entraîné sur les positions des accidents (qui, elles, ont un "
        f"département) : précision de {fr(r['precision_modele_departement'] * 100, 1)} % sur des accidents "
        "mis de côté pour le test ;\n"
        "- la distance de chaque relevé et de chaque accident au radar fixe de vitesse le plus proche a "
        "été calculée (formule de haversine) ;\n"
        "- pour chaque accident, les victimes du fichier « usagers » ont été comptées (tués, blessés "
        "hospitalisés, blessés légers) et la **gravité de l'accident** est celle de la victime la plus touchée."
    )
    st.markdown(
        "**Fichier non utilisé :** « véhicules immatriculés impliqués dans un accident (BAAC 2024) ». Il "
        "ne contient ni position, ni date, et ses identifiants d'accident (« 67 230 442 ») ne "
        "correspondent pas à ceux des autres fichiers BAAC (« 202400000001 ») : impossible de le placer "
        "sur une carte ou de le relier aux accidents."
    )

    st.header("Petit lexique")
    st.markdown(
        "- **Voiture radar** : voiture banalisée, conduite par une société privée, qui mesure la vitesse "
        "des véhicules autour d'elle pendant son trajet.\n"
        "- **Excès** : vitesse mesurée supérieure à la vitesse autorisée. Ce n'est pas forcément une "
        "infraction sanctionnée (une marge technique s'applique).\n"
        "- **Radar de vitesse** : radar fixe classique, discriminant, tourelle, tronçon ou urbain "
        "(les radars feu rouge et passage à niveau ne contrôlent pas la vitesse).\n"
        "- **Accident corporel** : accident ayant fait au moins une victime (blessé ou tué).\n"
        "- **Accident mortel** : au moins une personne tuée, c'est-à-dire décédée dans les 30 jours.\n"
        "- **Accident grave** : au moins un blessé hospitalisé plus de 24 heures, sans tué.\n"
        "- **Accident léger** : uniquement des blessés légers (soignés sans hospitalisation de plus de 24 heures)."
    )

    st.header("Aperçu des données préparées")
    onglets = st.tabs(["Vitesses (carte)", "Radars fixes", "Accidents"])
    with onglets[0]:
        st.dataframe(d["carte"].head(200), hide_index=True)
    with onglets[1]:
        st.dataframe(d["radars"].head(200), hide_index=True)
    with onglets[2]:
        st.dataframe(d["accidents"].head(200), hide_index=True)


# ---------------------------------------------------------------------------
# NAVIGATION ENTRE LES PAGES
# ---------------------------------------------------------------------------
pages = [
    st.Page(page_accueil, title="Accueil", icon="🏠", url_path="accueil", default=True),
    st.Page(page_carte, title="Carte des excès", icon="🗺️", url_path="carte"),
    st.Page(page_horaires, title="Jours et heures", icon="🕒", url_path="horaires"),
    st.Page(page_radars, title="Radars et accidents", icon="📡", url_path="radars"),
    st.Page(page_conclusion, title="Conclusion", icon="💡", url_path="conclusion"),
    st.Page(page_donnees, title="Données et méthode", icon="📋", url_path="donnees"),
]
page_choisie = st.navigation(pages)
st.sidebar.caption("Données : data.gouv.fr, année 2024.")
page_choisie.run()
