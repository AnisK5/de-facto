DE FACTO - BAROMÈTRE DE FIABILITÉ
Version : v2025.10.27a
Fichier : CONTEXT.txt
Date : 27 octobre 2025
INSTRUCTIONS POUR L’IA

Tu es le copilote créatif et technique du projet De Facto.
Ton rôle est de transformer un prototype prometteur en une application claire, inspirante et virale.

À chaque échange :

Adopte un ton motivant, professionnel et stimulant.

Relie la technique au sens : chaque évolution sert la mission du projet.

Sois force de proposition sur le fond (UX, design, stratégie).

Tes réponses doivent donner envie d’agir immédiatement.

Règles principales :

Ce fichier est la source de vérité du projet.

Ne pas modifier sans validation explicite ("mets à jour le contexte").

Les propositions de changement doivent être motivées par une amélioration mesurable (UX, clarté, cohérence, impact).

MISSION DU PROJET

De Facto est une application web qui évalue la fiabilité et la rigueur argumentative d’un contenu médiatique (article, post, extrait).
Elle cherche à éclairer le lecteur, pas à juger : révéler la cohérence, la nuance et la neutralité d’un texte.

"Faire la lumière sur l’information, pas sur les opinions."

Elle ne note pas le média, mais la qualité du raisonnement à l’intérieur du texte.

Axes principaux :

cohérence logique et factualité

ouverture à la pluralité

neutralité du ton

absence de manipulation émotionnelle

MÉTHODOLOGIE D’ANALYSE

Deux axes : Fond et Forme.
Chaque axe contient deux critères notés sur 100, avec justification et citation courte.

FOND

VRAI (Justesse) : fidélité des faits, cohérence logique, vérifiabilité.

COMPLET (Complétude) : diversité des points de vue, prise en compte de contre-arguments, contextualisation.

FORME

NEUTRE (Ton) : objectivité, sobriété lexicale, absence d’emphase émotionnelle.

CLAIR (Sophismes) : structure argumentative solide, absence de raccourcis ou généralisations.

Les quatre sous-scores sont combinés en un score global /100, accompagné d’une confiance IA (%).

LIMITES DE L’ANALYSE

Le modèle n’a pas accès à des vérifications factuelles externes.

L’analyse se base uniquement sur le texte fourni (pas de métadonnées).

Ironie, sous-entendus et hyperboles peuvent être mal interprétés.

Pertinence maximale pour les contenus à visée informative.

SORTIE DE L’API

POST /analyze → JSON

Exemple :
{
"score_global": 78,
"axes": {
"fond": {
"justesse": { "note": 80, "couleur": "🟢", "justification": "...", "citation": "..." },
"completude": { "note": 72, "couleur": "🟡", "justification": "...", "citation": "..." }
},
"forme": {
"ton": { "note": 75, "couleur": "🟢", "justification": "...", "citation": "..." },
"sophismes": { "note": 85, "couleur": "🟢", "justification": "...", "citation": "..." }
}
},
"resume": "Article factuel avec quelques biais émotionnels.",
"confiance_analyse": 82
}

ARCHITECTURE TECHNIQUE

Backend :

Framework : Flask (Python)

Modèle : GPT-4o-mini

Routes :
/analyze (POST) — analyse IA
/ (optionnel) — front minimal

CORS activé

Déploiement : Render (prod), Replit (dev)

Auto-détection environnement :
const isLocal = window.location.hostname === "localhost" || window.location.hostname.includes("replit");
const API = isLocal ? "/analyze" : "https://de-facto-backend.onrender.com/analyze
";

Frontend :

Technologies : HTML, CSS, JavaScript (Chart.js)

Structure :

textarea pour le texte à analyser

bouton “Analyser”

affichage résultats (score + radar + cartes)

Affichage :

Score global avec barre de progression et couleur

Radar Chart épuré (4 axes)

Cartes de sous-scores : justification + citation + code couleur

Transitions fluides et animations d’apparition

Loader fixe (centré bas, non intrusif)

Suppression du bloc “Limites IA” visible par défaut

Design inspiré de Perplexity : centré, minimal, lumineux, responsive.

IDENTITÉ VISUELLE

Concept visuel : “La lumière de la raison”
Symbolique : éclairer l’information, dissiper les zones d’ombre.
Logo : lampe moderne orientée vers la droite, projetant une lumière claire.
Style : vectoriel plat, lumière douce et bleu-turquoise, fond transparent.

Couleurs principales :

Bleu clair #0a4a9a

Turquoise #2bb6d0

Blanc #ffffff

Typographie : sans-serif fine et aérée, évoquant la clarté et la transparence.

De Facto devient une marque sobre, crédible et lumineuse.

VISION PRODUIT

Objectif :
Faire de De Facto un outil viral de lecture critique, simple, esthétique et partageable.

Le produit doit provoquer un effet “aha” :
"En 10 secondes, je comprends si un article est fiable — et pourquoi."

Axes de différenciation :

Clarté immédiate (aucun jargon)

Transparence (montrer les critères)

Crédibilité visuelle (design propre, neutre, rassurant)

Partageabilité (scorecards attractives)

Prochaine étape UX :

Phrase d’introduction plus claire :
"Collez un article, De Facto vous montre s’il éclaire ou s’il déforme la réalité."

Placeholder dans la zone de texte :
"Exemple : https://www.lemonde.fr/article12345…
"

ROADMAP SIMPLIFIÉE

FAIT :

Backend stable (GPT-4o-mini, Flask)

Front responsive avec radar, cartes, loader fixe

Rebranding UX (Vrai / Complet / Neutre / Clair)

EN COURS :

Intégration du logo lumineux

Ajustement des contrastes

Optimisation mobile

Animation fluide de l’apparition du résultat

A VENIR :

Export image des scorecards (partage réseaux)

Mode comparaison de deux textes

Historique local des analyses

Bandeau "mode dev / mode public"

Intégration Cursor ou Replit Studio selon workflow préféré

FIN DU FICHIER