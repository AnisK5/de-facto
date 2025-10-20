----------------------------------------------------------------
DE FACTO - BAROMÈTRE DE FIABILITÉ
----------------------------------------------------------------
Version : Base contextuelle IA
Fichier : CONTEXT.txt
Date : (à compléter par Anis)
----------------------------------------------------------------

INSTRUCTIONS POUR L’IA
----------------------------------------------------------------
1) Ce fichier est la SOURCE DE VÉRITÉ du projet De Facto.
2) À chaque nouvelle session, lis ce fichier entièrement avant toute réponse.
3) Considère ce contexte comme prioritaire sur tout autre.
4) Si l’utilisateur (Anis) décrit une évolution du projet (fonctionnalité, méthode, architecture, UX, vision) :
   - intègre ces informations à ta mémoire de travail,
   - renvoie automatiquement une nouvelle version complète et cohérente du fichier CONTEXT.txt.
5) Si des contradictions apparaissent avec le présent fichier, pose d’abord une question courte avant de le modifier.
6) Quand tu renvoies une nouvelle version du fichier, fais-le :
   - en un seul bloc de texte brut, sans caractères spéciaux,
   - sans ligne de conversation ni contenu hors fichier,
   - et indique clairement les sections modifiées (exemple : "Mise à jour : Méthodologie / Justesse").

----------------------------------------------------------------
MISSION DU PROJET
----------------------------------------------------------------
De Facto (ou Rationality Barometer) est une application web d’analyse argumentative.
Sa mission est d’évaluer la fiabilité et la rigueur logique d’un contenu (article, post, tweet, etc.)
afin de promouvoir un discours public plus rationnel et nuancé.

L’outil n’évalue pas la réputation du média, mais la qualité du contenu lui-même :
- cohérence du raisonnement
- solidité des faits
- neutralité du ton
- ouverture à la nuance.

----------------------------------------------------------------
MÉTHODOLOGIE D’ANALYSE
----------------------------------------------------------------
Deux axes d’évaluation :

1) FOND
   - JUSTESSE : solidité et cohérence des faits, vérifiabilité, logique argumentative.
   - COMPLÉTUDE : diversité des points de vue, prise en compte de contre-arguments, contextualisation.

2) FORME
   - TON : neutralité lexicale, charge émotionnelle, objectivité.
   - SOPHISMES : détection d’erreurs de raisonnement, d’appels à l’émotion, de généralisations abusives.

Les scores sont exprimés sur 100.
Chaque sous-score doit être accompagné :
- d’une justification courte
- et si possible d’une citation issue du texte (moins de 20 mots).

Pertinence maximale pour des textes à visée informative.

----------------------------------------------------------------
SORTIE DE L’API
----------------------------------------------------------------
L’API Flask expose la route POST /analyze.

Exemple de réponse JSON :

{
  "score_global": 78,
  "sous_scores": {
    "justesse": 80,
    "completude": 72,
    "ton": 75,
    "sophismes": 85
  },
  "commentaire": "Le texte est cohérent mais manque de pluralité de points de vue.",
  "resume": "Article factuel décrivant un événement avec quelques biais émotionnels.",
  "limites": "Analyse IA basée sur un extrait textuel, sans vérification externe."
}

----------------------------------------------------------------
LIMITES DE L’ANALYSE IA
----------------------------------------------------------------
Ces limites concernent l’IA, pas le texte analysé :
- Texte incomplet ou tronqué : contexte partiel.
- Pas de vérification factuelle externe en temps réel.
- Ambiguïtés ou ironie mal détectées.
- Pertinence limitée pour les textes non informatifs.

Objectif : transparence pour renforcer la confiance utilisateur.

----------------------------------------------------------------
ARCHITECTURE TECHNIQUE
----------------------------------------------------------------
Backend :
- Framework : Flask (Python)
- Modèle IA : OpenAI GPT-4o-mini
- Routes principales :
  "/" (optionnel) pour le front
  "/analyze" (POST) pour l’analyse
- CORS activé
- Hébergement : Render (production), Replit (développement)
- Fichier principal : server.py

Frontend :
- Technologies : HTML, CSS, JavaScript
- Éléments :
  - textarea pour le texte à analyser
  - bouton “Analyser”
  - div résultat pour l’affichage
- Fonction :
  - envoie une requête POST vers /analyze
  - affiche le JSON sous forme de scorecard UX.

----------------------------------------------------------------
PRINCIPES UX
----------------------------------------------------------------
- Lecture rapide : score global + code couleur (vert, jaune, rouge).
- Détails facultatifs : justifications, citations, résumé, limites.
- Transparence sur les capacités et limites de l’IA.
- Design pensé pour le partage (scorecard synthétique).

----------------------------------------------------------------
VISION PRODUIT
----------------------------------------------------------------
Objectifs :
- Expliquer pourquoi un texte paraît fiable ou non.
- Offrir un outil de lecture critique rapide.
- Promouvoir une culture de rigueur et de nuance.
- Devenir un format visuel viral : “scorecards De Facto”.

----------------------------------------------------------------
ROADMAP
----------------------------------------------------------------
1) Stabilisation des notes (moyenne sur plusieurs passes IA).
2) Analyse par URL (extraction de contenu d’un lien).
3) Vérification contextuelle automatisée (recherche web contrôlée).
4) Couleurs par sous-score.
5) Section “Méthode d’analyse” visible dans le front.
6) Scorecards partageables sur les réseaux sociaux.
7) Historique et comparaison de textes.

----------------------------------------------------------------
STACK TECHNIQUE
----------------------------------------------------------------
Backend : Flask (Python)
Frontend : HTML, CSS, JavaScript
IA : OpenAI GPT-4o-mini
Hébergement : Render
Développement : Replit
Versionnement : GitHub

----------------------------------------------------------------
FICHIERS CLÉS
----------------------------------------------------------------
server.py          - API Flask et intégration OpenAI
index.html         - Frontend avec zone de texte et scorecard
requirements.txt   - Dépendances Python
CONTEXT.txt        - Ce document, référence du projet
.replit (optionnel) - Configuration Replit

----------------------------------------------------------------
VARIABLES D’ENVIRONNEMENT
----------------------------------------------------------------
OPENAI_API_KEY : clé OpenAI à définir dans Render ou Replit

----------------------------------------------------------------
BONNES PRATIQUES
----------------------------------------------------------------
- Tester d’abord sur Replit avant le déploiement Render.
- Garder les prompts IA clairs et structurés.
- Ne jamais supprimer les champs JSON existants.
- Ajouter des commentaires explicatifs dans le code.
- Ne pousser sur GitHub que des versions stables.

----------------------------------------------------------------
SYNTHÈSE
----------------------------------------------------------------
De Facto est une application d’analyse argumentative.
Elle évalue la rigueur et la fiabilité d’un texte à partir de critères objectifs.
Le système produit un score global, des sous-scores et des commentaires explicatifs,
dans un format visuel clair et partageable.
Sa valeur ajoutée repose sur la transparence, la pédagogie et la fiabilité perçue.
----------------------------------------------------------------
FIN DU FICHIER
----------------------------------------------------------------
