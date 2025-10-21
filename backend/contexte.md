----------------------------------------------------------------
DE FACTO - BAROMÈTRE DE FIABILITÉ
----------------------------------------------------------------
Version : v2025.10.20e
Fichier : CONTEXT.txt
Date : 20 octobre 2025
----------------------------------------------------------------

INSTRUCTIONS POUR L’IA
----------------------------------------------------------------
0) Mode “Créateur de projet inspirant” :
    - Tu t’adresses à Anis comme à un co-créateur passionné : objectif = faire de De Facto un projet à fort impact intellectuel et sociétal.
    - Chaque échange doit donner envie d’avancer : ton ton est positif, motivant et concret.
    - Tu relies les aspects techniques au sens global du projet.
    - Tu restes pro, vivant et engageant.

1) Ce fichier est la SOURCE DE VÉRITÉ du projet De Facto.
2) À chaque nouvelle session, lis ce fichier entièrement avant toute réponse.
3) Considère ce contexte comme prioritaire sur tout autre.
4) Ne jamais proposer de modification automatique du code ou du contexte sans validation explicite d’Anis.
   → Ne jamais écraser l’existant sans demander confirmation.
5) Ce fichier sert de cadre pour proposer des actions concrètes (code, design, stratégie) sans altérer les bases.
6) Si le contexte est ambigu ou incomplet, poser une question courte et ciblée avant d’agir.
7) Lorsqu’une version est stabilisée et validée, tu peux proposer une mise à jour de contexte (nouvelle version).

----------------------------------------------------------------
MISSION DU PROJET
----------------------------------------------------------------
De Facto (ou Rationality Barometer) est une application web d’analyse argumentative.
Sa mission : évaluer la fiabilité et la rigueur logique d’un contenu (article, post, tweet, etc.)
pour promouvoir un discours public plus rationnel et nuancé.

L’outil évalue la qualité du contenu (pas la réputation du média) :
- cohérence du raisonnement,
- solidité des faits,
- neutralité du ton,
- ouverture à la nuance.

----------------------------------------------------------------
MÉTHODOLOGIE D’ANALYSE
----------------------------------------------------------------
Deux axes :

1) FOND
   - JUSTESSE : cohérence factuelle, logique, vérifiabilité.
   - COMPLÉTUDE : diversité des points de vue, contre-arguments, contexte.

2) FORME
   - TON : neutralité lexicale, charge émotionnelle.
   - SOPHISMES : erreurs de raisonnement, généralisations, appels à l’émotion.

Les scores sont sur 100, avec :
- justifications courtes,
- et si possible une citation (<20 mots).

----------------------------------------------------------------
SORTIE DE L’API
----------------------------------------------------------------
Route principale : POST /analyze

Réponse type :

{
  "score_global": 78,
  "sous_scores": {
    "justesse": 80,
    "completude": 72,
    "ton": 75,
    "sophismes": 85
  },
  "commentaire": "Texte cohérent mais peu nuancé.",
  "resume": "Article factuel avec quelques biais émotionnels.",
  "limites": "Analyse IA basée sur un extrait textuel, sans vérification externe."
}

----------------------------------------------------------------
LIMITES DE L’ANALYSE IA
----------------------------------------------------------------
Ces limites concernent l’IA, pas le texte :
- Analyse sur extrait (pas de contexte complet).
- Pas de vérification factuelle externe en temps réel.
- Ambiguïtés ou ironie mal détectées.
- Moins pertinent pour les textes non informatifs.

Objectif : transparence pour inspirer confiance.

----------------------------------------------------------------
ARCHITECTURE TECHNIQUE
----------------------------------------------------------------
Backend :
- Framework : Flask (Python)
- Modèle : OpenAI GPT-4o-mini
- Routes :
  "/" (sert le front uniquement sur Replit)
  "/analyze" (POST)
- Hébergement :
  - Render (prod)
  - Replit (dev)
- Fichier principal : backend/server.py
- Timeout Render : 25 s
- CORS activé
- .env supporté (via python-dotenv)

Frontend :
- HTML / CSS / JavaScript pur
- Élément principal : textarea + bouton "Analyser"
- Résultats : score global + sous-notes + justifications + limites
- Palette : vert / jaune / rouge selon score
- Responsive et partageable
- Dossier : frontend/

----------------------------------------------------------------
ENVIRONNEMENT DE DÉVELOPPEMENT
----------------------------------------------------------------
Replit :
- Fichier .replit : run = "cd backend && python3 server.py"
- Secret : OPENAI_API_KEY (via interface Secrets)
- Flask sert le frontend automatiquement si variable REPL_ID détectée
- Test immédiat : https://<ton-projet>.replit.app

GitHub :
- Repo unique : AnisK5/de-facto
- Structure :
  /backend  → Flask app
  /frontend → HTML app
- Branch principale : main

Render :
- Backend connecté à GitHub (sous-dossier /backend)
- Frontend connecté à GitHub (sous-dossier /frontend)
- Déploiement auto à chaque push sur main

----------------------------------------------------------------
WORKFLOW DE TEST ET PUBLICATION
----------------------------------------------------------------
1️⃣ Développement local / Replit
   - Modifier le code dans /frontend ou /backend
   - Sauvegarder → Replit recharge automatiquement
   - Tester sur l’URL .replit.app

2️⃣ Validation
   - Si tout fonctionne : commit
     git add .
     git commit -m "Message clair"
     git push

3️⃣ Publication
   - Render détecte le push sur main
   - Rebuild + redeploy automatique
   - Vérifier sur :
     https://facto-frontend.onrender.com
     https://facto-backend.onrender.com/analyze

4️⃣ Branche de dev (optionnel)
   - git checkout -b dev
   - git push origin dev
   - Merge vers main pour déclencher Render

5️⃣ Bonnes pratiques
   - Ne pas inclure de clé API dans le code
   - Toujours tester sur Replit avant push
   - Ne jamais écraser le contenu du repo sans confirmation

----------------------------------------------------------------
VISION PRODUIT
----------------------------------------------------------------
Objectif : devenir un outil de lecture critique rapide et visuel,
permettant de comprendre en 3 secondes le degré de rigueur d’un texte.

Valeurs :
- pédagogie,
- nuance,
- transparence,
- viralité des “scorecards De Facto”.

----------------------------------------------------------------
SECTION : BRIEF OPÉRATIONNEL (ÉTAT ACTUEL DU PROJET)
----------------------------------------------------------------
Date : 20 octobre 2025
Version projet : v2025.10.20e

🔹 SITE LIVE
Frontend : https://facto-frontend.onrender.com
Backend : https://facto-backend.onrender.com

🔹 OBJECTIF DU MOMENT
Stabiliser les notes et améliorer la transparence IA :
- lisibilité des sous-scores,
- cohérence des couleurs,
- uniformité du JSON,
- mise à jour automatique sur Render via GitHub.

✅ FAIT
- Back et front fusionnés dans un seul repo (de-facto)
- Replit configuré pour itération rapide
- Détection auto Replit/Render (serve front si REPL_ID)
- CORS + timeout stables
- API fonctionnelle et testée sur GPT-4o-mini

⚙️ À CORRIGER
- Vérifier les notes trop basses sur textes courts
- Améliorer cohérence entre fond / forme
- Ajuster prompt si sur-notation ou sous-notation
- Simplifier la présentation des limites IA vs contenu

🧩 RESTE À FAIRE (MVP+)
- Interface “scorecard v2”
- Historique des analyses
- Export image partageable
- Comparaison de textes
- Explication méthodologique visuelle
- Base de données (SQLite ou Supabase)
- Détection des textes longs (analyse par segments)

💡 PLUS TARD
- API publique (clé + quota)
- Intégration mobile
- Tableau de bord de veille argumentaire

----------------------------------------------------------------
FIN DU FICHIER
----------------------------------------------------------------
