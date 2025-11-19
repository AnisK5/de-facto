# =============================================================
# 🟦 De Facto — Backend pédagogique V2 (avec logs détaillés)
# =============================================================
# Objectif : que n'importe qui puisse suivre CE QUI SE PASSE
# étape par étape dans la console.
#
# 🔁 Pipeline :
# 1) Message global
# 2) Résumé + faits + opinions
# 3) Entités clés
# 4) Recherche web (sources fiables)
# 5) Comparaison texte vs sources
# 6) Évaluation des 4 axes
# 7) Synthèse globale
# 8) Score final
# =============================================================

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, json, re, requests, time
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing import Dict, Any

# -------------------------------------------------------------
# 🔵 0) CONFIG GLOBALE & MODE DEBUG
# -------------------------------------------------------------

# ⚙️ Activer / désactiver les logs pédagogiques ici
DEBUG = True

# 🎨 Couleurs ANSI pour la console (juste pour le confort visuel)
C_RESET = "\033[0m"
C_BLUE = "\033[94m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_MAGENTA = "\033[95m"
C_CYAN = "\033[96m"
C_BOLD = "\033[1m"

def log(title: str, message: str = "", color: str = C_CYAN, indent: int = 0):
    """Petit utilitaire pour afficher un message de log coloré et indenté."""
    if not DEBUG:
        return
    prefix = " " * indent
    if message:
        print(f"{prefix}{color}{title}{C_RESET} {message}")
    else:
        print(f"{prefix}{color}{title}{C_RESET}")

def log_data(label: str, value: Any, indent: int = 4, color: str = C_YELLOW, max_len: int = 220):
    """Affiche une donnée intermédiaire (tronquée si elle est trop longue)."""
    if not DEBUG:
        return
    text = str(value)
    if len(text) > max_len:
        text = text[:max_len] + "…"
    prefix = " " * indent
    print(f"{prefix}{color}- {label}: {text}{C_RESET}")

class StepTimer:
    """Contexte pour mesurer le temps d’une étape."""
    def __init__(self, step_label: str):
        self.step_label = step_label
        self.start = None

    def __enter__(self):
        if DEBUG:
            self.start = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        if DEBUG and self.start is not None:
            duration = time.time() - self.start
            log("⏱️ Temps", f"{self.step_label} terminé en {duration:.2f}s", C_GREEN, indent=4)

# -------------------------------------------------------------
# 🔵 1) CONFIG FLASK + OPENAI + SITES FIABLES
# -------------------------------------------------------------

app = Flask(__name__)
CORS(app)
load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

ALLOWED_SITES = [
    "reuters.com", "apnews.com", "bbc.com",
    "lemonde.fr", "francetvinfo.fr",
    "lefigaro.fr", "liberation.fr", "leparisien.fr"
]

# -------------------------------------------------------------
# 🔵 1bis) CONFIG CENTRALISÉE DES AXES
# -------------------------------------------------------------
# 👉 Toute la définition des axes est ici.
# - label     : ce qui s'affiche ("Vrai", "Logique", etc.)
# - description : pour le prompt
# - tooltip   : pour l'info-bulle dans le front
# - poids     : poids dans le score global (somme = 1 idéalement)

AXES_CONFIG = {
    "fond": {
        "Vrai": {
            "label": "Vrai",
            "description": "Exactitude des présupposés rapportés par le texte.",
            "tooltip": "Dans quelle mesure les faits présentés sont fidèles aux informations vérifiables.",
            "poids": 0.40,
        },
        "Complet": {
            "label": "Complet",
            "description": "Degré de couverture des informations importantes.",
            "tooltip": "Le texte oublie-t-il des éléments importants ou des angles majeurs ?",
            "poids": 0.30,
        },
    },
    "forme": {
        "Neutre": {
            "label": "Neutre",
            "description": "Neutralité et équilibre du ton.",
            "tooltip": "Présence ou non de parti pris marqué, caricature, charge émotionnelle.",
            "poids": 0.15,
        },
        "Logique": {
            "label": "Logique",
            "description": "Cohérence et solidité du raisonnement.",
            "tooltip": "Qualité de l’argumentation, absence de contradictions internes ou sophismes.",
            "poids": 0.15,
        },
    },
}

# -------------------------------------------------------------
# 🔵 2) UTILITAIRES GÉNÉRAUX
# -------------------------------------------------------------

def extract_json(text: str, fallback: dict):
    """
    🧩 OpenAI renvoie parfois du texte qui contient du JSON au milieu.
    On essaie d'extraire le bloc { ... } et de le parser.
    """
    try:
        # 1️⃣ Essaie direct parsing
        return json.loads(text)
    except:
        pass

    try:
        # 2️⃣ Cherche le premier { et dernier } pour extraire le JSON
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_str = text[start:end+1]
            return json.loads(json_str)
    except Exception as e:
        log("⚠️ JSON ERROR", str(e), color=C_YELLOW, indent=4)

    return fallback

def color_for(score: int) -> str:
    """🖌️ Convertit une note en un emoji couleur (pour le front)."""
    if score >= 70:
        return "🟢"
    if score >= 40:
        return "🟡"
    return "🔴"

# -------------------------------------------------------------
# 🔵 3) STRUCTURES DE DONNÉES (Pydantic)
# -------------------------------------------------------------

class Axis(BaseModel):
    note: int = 50
    justification: str = ""
    couleur: str = "⚪"

class Axes(BaseModel):
    fond: Dict[str, Axis]
    forme: Dict[str, Axis]

class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1)

class AnalyzeResponse(BaseModel):
    score_global: int
    couleur_global: str
    resume: str
    commentaire: str
    axes: Axes

    justesse: int
    completude: int
    ton: int
    sophismes: int

    confiance_analyse: int
    explication_confiance: str

# -------------------------------------------------------------
# 🔵 4) FONCTIONS D'ANALYSE (PIPELINE)
# -------------------------------------------------------------

# Activer l'extraction automatique des URL
ENABLE_URL_EXTRACT = True

# 🟣 ÉTAPE 0 — EXTRACTION SIMPLE D'UN ARTICLE À PARTIR D'UNE URL

def extract_article_from_url(url: str) -> str:
    """
    Version simple et robuste : d'abord Trafilatura,
    sinon fallback HTML → texte.
    Retourne l'article propre ou "" si échec.
    """

    print("\n🔎 [EXTRACT] Tentative extraction URL…")

    # 1) Trafilatura
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        extracted = trafilatura.extract(downloaded) if downloaded else ""
        if extracted and len(extracted) > 300:
            print(f"✅ [EXTRACT] Trafilatura OK (len={len(extracted)})")
            return extracted
        print("⚠️ [EXTRACT] Trafilatura trop court → fallback")
    except Exception as e:
        print("⚠️ [EXTRACT] Trafilatura erreur :", e)

    # 2) Fallback HTML → texte
    try:
        import requests
        from bs4 import BeautifulSoup

        r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")

        # Supprime les éléments inutiles
        for tag in soup(["script", "style", "noscript", "footer", "header"]):
            tag.decompose()

        text = "\n".join(
            l.strip()
            for l in soup.get_text("\n").split("\n")
            if len(l.strip()) > 40
        )

        if len(text) > 300:
            print(f"✅ [EXTRACT] Fallback OK (len={len(text)})")
            return text
        print("❌ [EXTRACT] Fallback trop court")
        return ""

    except Exception as e:
        print("❌ [EXTRACT] Fallback erreur :", e)
        return ""

# 🟣 ÉTAPE 1 — Message global
def get_message_global(text: str):
    """
    1️⃣ On essaie de résumer en UNE idée globale :
        - À quoi sert l'article ?
        - Quel message principal il veut faire passer ?
    """
    with StepTimer("Étape 1 - Message global"):
        log("[1/8] Étape 1", "Analyse du message global…", C_BLUE)
        prompt = """
        Analyse ce texte et identifie ce qu’un lecteur RETIENT réellement après lecture.

        Réponds STRICTEMENT en JSON :
        {
          "message": "...",
          "opinion_retention": "...",
          "sujets_majeurs": ["...", "..."]
        }

        Définitions :
        - "message" = thèse centrale du texte.
        - "opinion_retention" = perception laissée à un lecteur moyen.
        - "sujets_majeurs" = les thèmes principaux sur lesquels le texte oriente la perception.
        """

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt + "\n\nTexte :\n" + text}]
        )
        data = extract_json(resp.choices[0].message.content, {"message": ""})
        log_data("Message global détecté", data.get("message", "—"))
        return data

# 🟣 ÉTAPE 2 — Résumé + faits + opinions
def summarize_facts(text: str):
    """
    2️⃣ On sépare :
        - ce qui est factuel (faits)
        - ce qui est subjectif (opinions)
    """
    with StepTimer("Étape 2 - Résumé + faits/opinions"):
        log("[2/8] Étape 2", "Résumé + extraction des faits et opinions…", C_BLUE)
        prompt = """
        Analyse le texte suivant.

        Réponds STRICTEMENT en JSON :
        {
          "resume": "...",
          "faits": [{"texte": "..."}],
          "opinions": ["...", "..."]
        }

        Rappels :
        - Un "fait" est vérifiable objectivement.
        - Une "opinion" exprime interprétation ou jugement.
        - Le résumé doit refléter ce que le texte cherche à faire retenir.
        """

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt + "\n\nTexte :\n" + text}],
            response_format={"type": "json_object"}
        )
        data = extract_json(resp.choices[0].message.content,
                            {"resume": "", "faits": [], "opinions": []})

        log_data("Résumé", data.get("resume", "—"))
        log_data("Nombre de faits détectés", len(data.get("faits", [])))
        log_data("Nombre d'opinions détectées", len(data.get("opinions", [])))

        # On affiche 1 ou 2 exemples pour pédagogie
        faits = data.get("faits", [])
        if faits:
            log_data("Exemple de fait", faits[0].get("texte", "—"), indent=6)
        opinions = data.get("opinions", [])
        if opinions:
            log_data("Exemple d'opinion", opinions[0], indent=6)

        return data

# 🟣 ÉTAPE 3 — Assertions vérifiables (anciennement entités)
def extract_entities(text: str):
    """
    3️⃣ Extraction des assertions vérifiables (présupposés/claims).
    """
    with StepTimer("Étape 3 - Assertions vérifiables"):
        log("[3/8] Étape 3", "Extraction des assertions vérifiables…", C_BLUE)

        prompt = """
        Tu dois EXTRAIRE les PRÉSUPPOSÉS du texte **uniquement s’il y en a**.

        📌 Définitions pour éviter toute ambiguïté :
        Un présupposé = 
        - une affirmation que le texte présente comme vraie,
        - ou une idée implicite sur laquelle il repose,
        - ou une conclusion suggérée au lecteur sans être démontrée.

        ⚠️ Important :
        Certains textes (dépêches factuelles, annonces neutres, descriptions brèves)
        ne contiennent PAS de présupposés significatifs.
        Dans ce cas, tu dois retourner une liste vide ET expliquer pourquoi.

        ────────────────────────────────────────────
        📌 Consigne :
        - Si le texte contient des présupposés → en extraire entre 3 et 6.
        - Si le texte n’en contient pas → renvoyer une liste vide mais EXPLIQUER pourquoi.

        ────────────────────────────────────────────
        📘 EXEMPLES

        🟦 Exemple A — Texte avec présupposés
        Texte : « La mairie a hissé le drapeau palestinien pour soutenir la paix. »
        Présupposés extraits :
        [
          "Le drapeau palestinien est un symbole de paix.",
          "Le geste de la mairie soutient la cause palestinienne.",
          "Ce geste a une portée politique ou morale."
        ]

        🟦 Exemple B — Texte sans présupposés
        Texte : « La mairie a publié à 14h un communiqué sur l'ouverture du parc. »
        Résultat :
        {
          "presupposes": [],
          "reason": "Le texte est purement descriptif, ne contient aucune interprétation ou affirmation implicite."
        }

        ────────────────────────────────────────────
        📌 FORMAT STRICT :
        Si des présupposés existent :
        {
          "presupposes": ["...", "..."]
        }

        Si le texte n’en contient pas :
        {
          "presupposes": [],
          "reason": "..."
        }
        """





        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt + "\n\nTexte :\n" + text}
            ]
        )

        raw = resp.choices[0].message.content
        data = extract_json(raw, [])

        log_data("Assertions détectées", data)

        return data

# 🟣 ÉTAPE 4 — Recherche web
def search_web(entities: list):
    """
    4️⃣ À partir des entités, on interroge Google Custom Search
        sur une liste de médias considérés comme fiables.
    """
    with StepTimer("Étape 4 - Recherche web"):
        log("[4/8] Étape 4", "Recherche web sur des sources fiables…", C_BLUE)

        key = os.getenv("GOOGLE_CSE_API_KEY")
        cx = os.getenv("GOOGLE_CSE_CX")
        if not key or not cx:
            log("⚠️ GOOGLE_CSE", "Pas de clé API ou de CX configuré → recherche web désactivée.", C_YELLOW, indent=4)
            return []

        results = []
        # Si entities est un dict avec 'presupposes', extraire la liste
        if isinstance(entities, dict):
            entity_list = entities.get("presupposes", [])
        else:
            entity_list = entities if isinstance(entities, list) else []

        for ent in entity_list[:3]:  # on limite à 3 entités pour ne pas exploser le quota
            query = f"{ent} ({' OR '.join(['site:' + s for s in ALLOWED_SITES])})"
            log_data("Requête web", query, indent=6)

            r = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": key, "cx": cx, "q": query, "num": 4}
            )
            data = r.json()
            hits = [
                {"titre": i["title"], "snippet": i["snippet"], "url": i["link"]}
                for i in data.get("items", [])
            ]
            log_data(f"Nombre de sources pour « {ent} »", len(hits), indent=6)

            results.append({"entité": ent, "sources": hits})

        return results

# 🟣 ÉTAPE 5 — Comparaison texte vs web
def compare_text_web(summary: dict, web_hits: list):
    """
    5️⃣ On compare :
        - ce que dit l'article (résumé + faits)
        - ce que disent les sources web
    pour repérer :
        - faits manquants
        - contradictions
        - divergences
    """
    with StepTimer("Étape 5 - Comparaison texte vs sources"):
        log("[5/8] Étape 5", "Comparaison du texte avec les sources web…", C_BLUE)

        prompt = """
        Tu compares un texte avec des articles fiables.

        Entrées :
        - summary : résumé + faits/opinions
        - web_hits : extraits de sources fiables

        Analyse :
        1) Ce que disent les sources fiables sur les présupposés.
        2) Où elles convergent.
        3) Où elles divergent.
        4) Quelles informations fiables manquent dans le texte.
        5) Comment ces différences modifient la perception du lecteur.

        Réponds STRICTEMENT en JSON :
        {
          "faits_manquants": ["...", "..."],
          "contradictions": ["...", "..."],
          "divergences": ["...", "..."],
          "impact": "faible | modéré | fort",
          "perception_impactee": "..."
        }

        Définitions :
        - "faits_manquants" = infos fiables importantes absentes du texte.
        - "contradictions" = texte dit X, sources fiables disent Y.
        - "divergences" = cadrages ou priorités différentes.
        - "impact" = importance de l'effet sur la perception du lecteur.
        - "perception_impactee" = ce qui change dans la tête du lecteur.
        """


        # On envoie un contexte compact (on évite d'injecter tout brut)
        payload = {
            "summary": summary,
            "web_hits": web_hits,
        }

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt},
                {"role": "user", "content": json.dumps(payload)}
            ]
        )
        data = extract_json(
            resp.choices[0].message.content,
            {"faits_manquants": [], "contradictions": [], "divergences": [], "impact": "faible"}
        )

        log_data("Impact global des différences", data.get("impact", "—"))
        log_data("Nb faits manquants", len(data.get("faits_manquants", [])))
        log_data("Nb contradictions", len(data.get("contradictions", [])))
        log_data("Nb divergences", len(data.get("divergences", [])))

        return data

# 🟣 ÉTAPE 6 — Évaluation des axes
def evaluate_axes(summary: dict, web_facts: list, diffs: dict, global_msg: dict):
    """
    6️⃣ À partir de tout ce qu'on a vu, on attribue des notes
        selon AXES_CONFIG (fond/formes).
    """
    with StepTimer("Étape 6 - Évaluation des axes"):
        log("[6/8] Étape 6", "Évaluation des 4 axes…", C_BLUE)

        # Construction dynamique du texte d'axes + template JSON attendu
        axes_lines = []
        axes_template = {"axes": {"fond": {}, "forme": {}}}
        for category, axes_def in AXES_CONFIG.items():
            for key, meta in axes_def.items():
                axes_lines.append(f"- {category}.{key} : {meta['description']}")
                axes_template["axes"][category][key] = {
                    "note": 0,
                    "justification": ""
                }

        prompt = """
        Tu dois attribuer une NOTE pour 4 axes :
        - fond.Vrai
        - fond.Complet
        - forme.Neutre
        - forme.Logique

        ⚠️ Notes obligatoires uniquement parmi :
        [0, 20, 40, 60, 80, 100]

        ────────────────────────────────────────────
        🔎 Rappel fondamental
        La note ne porte PAS sur les présupposés eux-mêmes,
        mais sur l’IMPACT que les informations FIABLES présentes ou absentes
        ont sur ce que RETIENT un lecteur du texte.

        ➡️ Si aucune information fiable ne manque OU n’impacte la perception,
        alors la note doit être élevée (80 ou 100).

        ➡️ Si l’axe n’est pas vraiment pertinent
        (ex: un texte neutre, descriptif, sans raisonnement),
        alors la note doit être haute mais la justification doit l’expliquer :
        « Axe faiblement sollicité dans ce type de texte ».

        ────────────────────────────────────────────
        🎯 BARÈME À UTILISER STRICTEMENT
        ────────────────────────────────────────────
        100 = Aucun impact perceptible. Perception identique.
        80  = Impact très faible, nuances mineures.
        60  = Impact modéré, perception légèrement modifiée.
        40  = Impact important, perception clairement modifiée.
        20  = Perception trompeuse ou très biaisée.
        0   = Perception inversée par rapport aux sources fiables.

        ────────────────────────────────────────────
        🟩 AXE 1 — VRAI
        Question : Les informations FIABLES confirment-elles ce que retient le lecteur ?
        Remarque : si le texte est fidèle aux sources fiables → note 80 ou 100.

        Justification :
        - si problèmes : « Le texte fait croire X, alors que les sources fiables indiquent Y… »
        - si pas de problème : « Les faits présentés correspondent aux sources fiables… »
        - si axe peu sollicité : « Le texte est descriptif, peu de présupposés → axe peu sollicité. »

        ────────────────────────────────────────────
        📘 FORMAT DE JUSTIFICATION (FLEXIBLE MAIS STRUCTURÉ)

        Chaque justification doit être précise, pédagogique et reposer sur ce que
        le lecteur RETIENT réellement du texte.

        Tu peux ignorer les sections non pertinentes si le texte ne contient pas
        de présupposés, pas de conclusions, pas de ton orienté, etc.  
        Dans ce cas, explique simplement : « cet axe est peu pertinent ici car… ».

        Sinon, utilise la structure suivante (de façon flexible) :

        1) 🎯 Ce que le texte fait croire, ou met en avant  
           - citer une idée, un cadrage ou une formulation du texte (pas mot à mot s’il est trop long)  
           - expliquer ce que le lecteur RETIENT

        2) 📚 Ce que disent les sources fiables (Reuters, AFP, BBC, Le Monde…)  
           - indiquer clairement où elles confirment, nuancent ou contredisent  
           - donner un exemple concret (même reformulé)

        3) 🎛️ Impact sur la perception du lecteur  
           - expliquer si cela change beaucoup, modérément ou peu ce que le lecteur comprend

        4) 🎓 Phrase pédagogique finale  
           - courte, pour aider l’utilisateur à comprendre *pourquoi cela compte*

        📌 Important :
        - ne pas inventer de contradictions si les sources ne disent rien → dire explicitement « aucune contradiction trouvée »
        - ne pas forcer des manquements s’il n’y en a pas → dire « aucune information fiable majeure manquante »
        - tu peux combiner plusieurs parties si c’est plus naturel
        ────────────────────────────────────────────


        ────────────────────────────────────────────
        🟧 AXE 2 — LOGIQUE
        Question : Le raisonnement mène-t-il à des conclusions qui seraient différentes
        si les informations FIABLES étaient présentes ?

        Justification :
        - si erreurs de raisonnement : expliquer lesquelles
        - si raisonnements cohérents : le dire explicitement
        - si le texte ne fait PAS de raisonnement : le dire (« axe non sollicité »)

        ────────────────────────────────────────────
        🟦 AXE 3 — COMPLET
        Question : Le texte oublie-t-il des informations FIABLES importantes ?
        Si rien d’important ne manque → note 80 ou 100.

        Justification :
        - si omissions importantes : lister précisément
        - sinon : dire explicitement que le texte reste complet par rapport aux sources fiables

        ────────────────────────────────────────────
        🟪 AXE 4 — NEUTRE
        Question : La formulation oriente-t-elle la perception, ou reste-t-elle neutre ?

        Justification :
        - si connotations : les citer
        - si texte neutre : le dire
        - si axe peu sollicité : le mentionner

        ────────────────────────────────────────────
        📌 FORMAT STRICT
        ────────────────────────────────────────────
        Réponds STRICTEMENT :
        {
          "axes": {
            "fond": {
              "Vrai":    {"note": 0, "justification": ""},
              "Complet": {"note": 0, "justification": ""}
            },
            "forme": {
              "Neutre":  {"note": 0, "justification": ""},
              "Logique": {"note": 0, "justification": ""}
            }
          }
        }

        ⚠️ Notes OBLIGATOIREMENT dans [0,20,40,60,80,100]
        """.strip()

        payload = {
            "global_msg": global_msg,
            "summary": summary,
            "web_facts": web_facts,
            "diffs": diffs,
        }

        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": prompt},
                {"role": "user", "content": json.dumps(payload)}
            ]
        )

        data = extract_json(resp.choices[0].message.content, {"axes": {}})

        axes = data.get("axes", {})
        fond = axes.get("fond", {})
        forme = axes.get("forme", {})

        # Logs pédagogiques par axe
        for category, axes_def in AXES_CONFIG.items():
            for key, meta in axes_def.items():
                note = axes.get(category, {}).get(key, {}).get("note", "—")
                log_data(f"Note {category}.{key}", note)

        return data

# 🟣 ÉTAPE 7 — Synthèse globale
def build_synthesis(axes: dict):
    """
    7️⃣ On produit un texte synthétique qui explique le résultat global
        (ce que le frontend affiche dans le gros encadré).
    """
    with StepTimer("Étape 7 - Synthèse"):
        log("[7/8] Étape 7", "Génération de la synthèse globale…", C_BLUE)

        prompt = """
        Tu dois écrire une synthèse très courte et percutante (3 phrases maximum).

        Objectif : que le lecteur comprenne en quelques secondes :
        1) ce que le texte lui fait croire,
        2) ce que l'analyse révèle comme limites essentielles,
        3) et si le texte est globalement fiable.

        Règles :
        - 3 phrases maximum.
        - Style clair, direct, pédagogique.
        - Pas de listes, pas de détails techniques.
        - Pas de chiffres ni de nom d’axes.
        - Mentionner uniquement les éléments essentiels visibles dans les justifications.
        - Utiliser ce modèle implicite :
            Phrase 1 : ce que le lecteur retient du texte (perception principale).
            Phrase 2 : les manques / biais / divergences importantes révélées par l'analyse.
            Phrase 3 : impact final sur la fiabilité du texte (fiable / assez fiable / partiel / peu fiable / non fiable).
        - Ne rien inventer.
        """
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt},
                {"role": "user", "content": json.dumps(axes)}
            ]
        )
        text = resp.choices[0].message.content.strip()
        log_data("Synthèse générée", text)
        return text

# 🟣 ÉTAPE 8 — Score global
def compute_score(axes: dict) -> int:
    """
    8️⃣ À partir des notes et de AXES_CONFIG, on calcule un score global pondéré.
    Fond compte plus que forme via les poids.
    """
    with StepTimer("Étape 8 - Score global"):
        log("[8/8] Étape 8", "Calcul du score global…", C_BLUE)

        total = 0.0
        for category, axes_def in AXES_CONFIG.items():
            cat_axes = axes.get(category, {})
            for key, meta in axes_def.items():
                note = cat_axes.get(key, {}).get("note", 0)
                poids = meta.get("poids", 0)
                total += note * poids

        score = int(round(total))
        log_data("Score global calculé", score)
        return score

# -------------------------------------------------------------
# 🔵 5) ROUTE PRINCIPALE — /analyze
# -------------------------------------------------------------

@app.route("/analyze", methods=["POST"])
def analyze():
    if DEBUG:
        print()
        log("===== 🚀 NOUVELLE ANALYSE LANCÉE =====", color=C_MAGENTA)

    try:
        payload = AnalyzeRequest(**request.json)
    except Exception as e:
        log("❌ ERREUR REQUÊTE", str(e), color=C_YELLOW)
        return jsonify({"error": "Requête invalide"}), 400

    text = payload.text.strip()

    log_data("Texte reçu (début)", text[:200] + ("…" if len(text) > 200 else ""), color=C_CYAN)

    # --------------------------------------------------
    # Si l'entrée est une URL → on tente d'extraire l'article
    # --------------------------------------------------
    if ENABLE_URL_EXTRACT and re.match(r"^https?://", text):
        print("🌐 [ANALYZE] URL détectée :", text[:80], "...")
        extracted = extract_article_from_url(text)

        if extracted and len(extracted) > 300:
            print(f"📝 [ANALYZE] Article extrait (len={len(extracted)}) → analyse OK\n")
            text = extracted[:8000]  # Limite sécurité
        else:
            print("❌ [ANALYZE] Impossible d'extraire un article → analyse probablement vide")

    # 1️⃣ → 7️⃣ : pipeline d'analyse
    global_msg = get_message_global(text)
    summary = summarize_facts(text)
    entities = extract_entities(text)
    web_hits = search_web(entities)
    diffs = compare_text_web(summary, web_hits)
    evals = evaluate_axes(summary, web_hits, diffs, global_msg)
    axes = evals["axes"]

    synthese = build_synthesis(axes)
    score = compute_score(axes)

    # Ajout des couleurs + labels + tooltips pour chaque axe (pour le front)
    for category, axes_def in AXES_CONFIG.items():
        for key, meta in axes_def.items():
            if category in axes and key in axes[category]:
                note_val = axes[category][key].get("note", 0)
                axes[category][key]["couleur"] = color_for(note_val)
                axes[category][key]["label"] = meta["label"]
                axes[category][key]["tooltip"] = meta["tooltip"]

    # Mapping vers les anciens champs pour compatibilité
    fond_v = axes["fond"]["Vrai"]["note"]
    fond_c = axes["fond"]["Complet"]["note"]
    forme_n = axes["forme"]["Neutre"]["note"]
    forme_l = axes["forme"]["Logique"]["note"]

    # Log final récap
    log("✅ ANALYSE TERMINÉE", color=C_GREEN)
    log_data("Score global", score, indent=4, color=C_GREEN)
    log_data("Couleur globale", color_for(score), indent=4, color=C_GREEN)

    response = AnalyzeResponse(
        score_global=score,
        couleur_global=color_for(score),
        resume=synthese,
        commentaire=synthese,
        axes=Axes(fond=axes["fond"], forme=axes["forme"]),
        # anciens noms, mais valeurs des nouveaux axes
        justesse=fond_v,
        completude=fond_c,
        ton=forme_n,
        sophismes=forme_l,
        confiance_analyse=score,           # pour l'instant = même valeur
        explication_confiance=""           # tu pourras remplir ça plus tard
    )

    return jsonify(response.model_dump())

# -------------------------------------------------------------
# 🔵 6) ROUTES POUR LE FRONTEND (fichiers statiques)
# -------------------------------------------------------------

@app.route("/")
def serve_frontend():
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
    return send_from_directory(frontend_dir, "index.html")

@app.route("/<path:path>")
def serve_static(path):
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
    file_path = os.path.join(frontend_dir, path)
    if os.path.exists(file_path):
        return send_from_directory(frontend_dir, path)
    return send_from_directory(frontend_dir, "index.html")

# -------------------------------------------------------------
# 🔵 7) LANCEMENT DU SERVEUR
# -------------------------------------------------------------

if __name__ == "__main__":
    log("🌐 SERVEUR", "Lancement sur http://0.0.0.0:5000", C_MAGENTA)
    app.run(host="0.0.0.0", port=5000, debug=False)
