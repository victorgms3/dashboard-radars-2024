# Documentation : méthode d'exécution

**Projet Python S1, Licence Pro Data Mining 2026-2027**
**Dashboard : « Excès de vitesse, radars et accidents en France (2024) »**
Auteur : `<NOM> <Prénom>`

---

## 1. Ce que fait le dashboard

Un tableau de bord Streamlit, utilisable sans connaître Python, qui croise trois jeux de données publics de 2024 (data.gouv.fr) :

| Jeu de données | Contenu | Taille brute |
|---|---|---|
| Vitesses relevées par les voitures radars à conduite externalisée | 9,6 millions de mesures : date, position GPS, vitesse mesurée, vitesse autorisée | 535 Mo |
| Liste des radars fixes en France | 3 268 radars : type, position, date de mise en service, vitesse contrôlée | 0,1 Mo |
| Accidents corporels (BAAC) : fichiers `caract-2024.csv`, `lieux-2024.csv` et `usagers-2024.csv` | 54 402 accidents (date, heure, position, conditions, type de route) et 125 187 personnes impliquées (gravité) | 28 Mo |

Le dashboard comporte 6 pages, accessibles par le menu à gauche :

| Page | Question posée | Interactions |
|---|---|---|
| 🏠 Accueil | De quoi parle-t-on ? | Chiffres clés, zones couvertes |
| 🗺️ Carte des excès | Où roule-t-on trop vite ? | Région, département, période, moment de la journée, vitesse autorisée, seuil d'excès, affichage des radars et des accidents (par gravité), classement des 10 pires zones |
| 🕒 Jours et heures | Quand roule-t-on trop vite ? | Carte de chaleur jour × heure, courbe heure par heure |
| 📡 Radars et accidents | Les radars font-ils ralentir ? Y a-t-il moins d'accidents autour, et sont-ils moins graves ? | Courbe « effet radar », carte des radars, curseur de distance, choix de la gravité des accidents |
| 💡 Conclusion (bonus) | Que faut-il retenir ? | Analyse rédigée, chiffres recalculés à partir des données |
| 📋 Données et méthode | D'où viennent les chiffres ? | Sources, étapes de nettoyage, aperçu des tables |

---

## 2. Contenu du dossier livré

```
dashboard_radars/
├── projet_dashboard_radars.ipynb   ← notebook Google Colab à ouvrir (contient le code de app.py)
├── app.py                          ← code du dashboard Streamlit
├── preparation_donnees.py          ← nettoyage et agrégation des données brutes (à lancer une seule fois)
├── donnees_preparees/              ← fichiers utilisés par le dashboard (≈ 9 Mo au total)
│   ├── vitesses_carte.parquet           vitesses regroupées par zone de 2 km, mois, moment, vitesse autorisée
│   ├── vitesses_horaires.parquet        vitesses regroupées par département, jour et heure
│   ├── vitesses_distance_radar.parquet  vitesses regroupées par distance au radar le plus proche
│   ├── radars_fixes.parquet             radars nettoyés
│   ├── accidents.parquet                accidents nettoyés
│   └── rapport_nettoyage.json           compte rendu du nettoyage (affiché dans le dashboard)
├── requirements.txt                ← bibliothèques nécessaires (exécution en local)
└── DOCUMENTATION.md                ← ce document
```

Les fichiers bruts (535 Mo pour les vitesses) ne sont pas joints : ils sont trop lourds pour un envoi par mail et ne sont nécessaires que pour refaire la préparation (voir partie 5). Les liens sont donnés en partie 8.

**Pourquoi deux scripts ?** Le fichier des vitesses fait 535 Mo et 9,6 millions de lignes. Le lire à chaque ouverture du dashboard prendrait plus d'une minute. `preparation_donnees.py` le nettoie et le résume **une seule fois** (environ 1 minute) en fichiers légers ; `app.py` ne lit que ces fichiers et s'ouvre en quelques secondes.

---

## 3. Exécution sur Google Colab (méthode recommandée)

### Prérequis
- un compte Google (pour Colab et Drive) ;
- un compte ngrok gratuit : <https://dashboard.ngrok.com/signup>. Dans le tableau de bord ngrok, noter :
  - le **jeton** (menu *Your Authtoken*) ;
  - le **domaine gratuit** (menu *Domains*, de la forme `xxxx.ngrok-free.app`).

### Étapes
1. Copier le dossier `dashboard_radars` complet à la racine de **Mon Drive** (chemin attendu : `/content/drive/MyDrive/dashboard_radars`). Si vous le placez ailleurs, modifiez la variable `DOSSIER_PROJET` à l'étape 3 du notebook.
2. Ouvrir `projet_dashboard_radars.ipynb` dans Google Colab (clic droit sur le fichier dans Drive → *Ouvrir avec* → *Google Colaboratory*).
3. Exécuter les cellules **dans l'ordre** :

| Étape du notebook | Ce qu'elle fait | Ce qu'il faut faire |
|---|---|---|
| 1. Installer les bibliothèques | `pip install` de streamlit, pyngrok, plotly, pyarrow, scikit-learn | Rien, attendre (≈ 30 s) |
| 2. Connecter Google Drive | Monte le Drive dans `/content/drive` | Autoriser l'accès dans la fenêtre Google |
| 3. Récupérer les données préparées | Copie `donnees_preparees` du Drive vers `/content` | Vérifier que la liste des 6 fichiers s'affiche |
| 4. Écrire l'application | `%%writefile app.py` crée le fichier du dashboard | Rien |
| 5. Tunnel ngrok | Rend le dashboard accessible par une adresse web | Coller le **jeton**, puis le **domaine** ngrok |
| 6. Lancer Streamlit | Démarre le serveur et attend qu'il réponde | Attendre « ✅ Streamlit est opérationnel ! », puis ouvrir le lien affiché à l'étape 5 |

4. À la première ouverture du lien, ngrok affiche une page d'avertissement : cliquer sur **Visit Site**.
5. Le premier affichage prend quelques secondes (chargement des données en mémoire) ; ensuite chaque clic est quasi instantané.

### Arrêter ou relancer
Exécuter la dernière cellule (`process.terminate()` et `ngrok.kill()`), puis relancer les étapes 5 et 6. Après une modification du code, relancer les étapes 4, puis 5 et 6. Après avoir refait la préparation des données, il faut aussi arrêter puis relancer Streamlit : il garde les anciennes données en mémoire (cache) tant qu'il tourne.

---

## 4. Exécution en local (sans Colab ni ngrok)

Avec Python 3.10 ou plus récent :

```bash
cd dashboard_radars
pip install -r requirements.txt
streamlit run app.py
```

Le dashboard s'ouvre dans le navigateur à l'adresse <http://localhost:8501>.

---

## 5. Refaire la préparation des données (facultatif)

Les fichiers de `donnees_preparees` sont déjà fournis. Pour les recréer à partir des données brutes :

1. Télécharger les 5 fichiers bruts (liens en partie 8) :
   - `opendata-vitesses-pratiquees-voitures-radar-2024.csv`
   - `jeu-de-donnees-liste-des-radars-fixes-en-france-2024-.csv`
   - `caract-2024.csv`
   - `lieux-2024.csv`
   - `usagers-2024.csv`
2. Lancer le script en lui donnant le dossier où se trouvent ces fichiers :
   - **en local** : `python preparation_donnees.py chemin/vers/les/csv` (sans argument, le script cherche les CSV dans le dossier parent de `dashboard_radars`) ;
   - **sur Colab** : déposer les CSV dans `Mon Drive/dashboard_radars/donnees_brutes`, puis mettre `REFAIRE_PREPARATION = True` à l'étape 3 du notebook.
3. Durée : environ 1 à 2 minutes. Le script affiche chaque étape puis le rapport de nettoyage, et réécrit le dossier `donnees_preparees`.

### Ce que fait le script

| Étape | Traitement |
|---|---|
| Accidents | Conversion des coordonnées écrites avec une virgule, suppression des 3 347 accidents d'outre-mer, création de la date, libellés lisibles (météo, lumière, collision, type de route), ajout de la vitesse autorisée depuis `lieux-2024.csv` (valeurs invalides comme -1 ou 500 mises à « inconnue »), comptage des victimes depuis `usagers-2024.csv` (tués, blessés hospitalisés, blessés légers) et gravité de l'accident (mortel, grave ou léger, selon la victime la plus touchée) |
| Modèle de département | Les relevés et les radars n'ont pas de département : un modèle des **k plus proches voisins** (scikit-learn) apprend le département à partir des positions des accidents. Précision mesurée sur 20 % d'accidents mis de côté : 97,9 % |
| Radars fixes | Lecture en encodage latin-1, nettoyage des noms de colonnes (espaces en trop), suppression du radar sans coordonnées et des 100 radars d'outre-mer, codes `ETT`, `ETD`… remplacés par des libellés, vitesse manquante (704 radars) notée « Non renseignée » |
| Vitesses | Lecture par morceaux d'un million de lignes, séparation de la colonne `position` en latitude et longitude, suppression des 112 mesures au-dessus de 200 km/h, calcul du dépassement, distance de chaque mesure au radar fixe de vitesse le plus proche (formule de haversine), puis regroupement en trois tables légères |

---

## 6. Guide rapide pour l'utilisateur du dashboard

- **Choisir la page** dans le menu en haut à gauche.
- **Filtres** : ils se trouvent dans le panneau de gauche, sous le menu. Toutes les cartes, tous les chiffres et tous les graphiques de la page se mettent à jour immédiatement.
- **« Compter comme excès à partir de »** : +1 km/h compte tout dépassement ; +20 km/h ne garde que les excès importants.
- **Cartes** : molette ou pincement pour zoomer, survol d'un point pour voir le détail.
- **Classement des 10 zones** : le lien « Ouvrir la carte » montre l'endroit sur Google Maps.
- **Tableaux** : sous chaque graphique, « Voir les chiffres sous forme de tableau » affiche les valeurs exactes.

---

## 7. Problèmes fréquents

| Symptôme | Cause probable | Solution |
|---|---|---|
| `FileNotFoundError ... donnees_preparees` | Le dossier n'a pas été copié dans `/content` | Vérifier `DOSSIER_PROJET` à l'étape 3 et relancer l'étape 3 |
| « ❌ Streamlit ne répond pas » | Erreur dans `app.py` ou démarrage lent | Relancer l'étape 6 ; sinon lancer `!streamlit run app.py` dans une cellule pour lire l'erreur |
| ngrok : `ERR_NGROK_4018` ou jeton refusé | Jeton mal copié | Recopier le jeton depuis le tableau de bord ngrok |
| ngrok : domaine refusé | Domaine mal saisi ou déjà utilisé par une autre session | Saisir le domaine sans `https://` ; arrêter les autres sessions (`ngrok.kill()`) |
| La carte est vide pour une région | Les voitures radars n'ont pas circulé dans cette région en 2024 | Normal : seules 8 régions sont couvertes (voir la page Accueil) |
| `ModuleNotFoundError` | Étape 1 non exécutée | Relancer l'étape 1 |
| `KeyError` sur une colonne (ex. `'gravite'`) après avoir refait la préparation | Streamlit utilise encore les anciennes données gardées en mémoire | Arrêter Streamlit (dernière cellule) puis relancer les étapes 5 et 6 |

---

## 8. Sources

- Vitesses relevées par les voitures radars : <https://www.data.gouv.fr/datasets/jeux-de-donnees-des-vitesses-relevees-par-les-voitures-radars-a-conduite-externalisee>
- Liste des radars fixes en France : <https://www.data.gouv.fr/datasets/liste-des-radars-fixes-en-france>
- Accidents corporels de la circulation routière (BAAC), fichiers `caract-2024.csv`, `lieux-2024.csv` et `usagers-2024.csv` : <https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2025>

Le fichier « véhicules immatriculés impliqués dans un accident (BAAC 2024) » a été étudié puis écarté : il ne contient ni position ni date, et ses identifiants d'accident ne correspondent pas à ceux des autres fichiers BAAC.

**Outils utilisés :** Python, pandas, scikit-learn, Plotly, Streamlit, Google Colab, ngrok. Code réalisé avec l'aide d'un assistant d'IA (Claude), utilisation autorisée pour ce projet.
