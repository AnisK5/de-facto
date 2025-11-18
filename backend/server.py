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
# 🔵 2) UTILITAIRES GÉNÉRAUX
# -------------------------------------------------------------

def extract_json(text: str, fallback: dict):
    """
    🧩 OpenAI renvoie parfois du texte qui contient du JSON au milieu.
    On essaie d'extraire le bloc { ... } et de le parser.
    """
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group(0)) if match else fallback
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
    citation: str = ""
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
        prompt = "Donne le message global en 3 lignes max. JSON {\"message\":\"...\"}"
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
        1) Fais un résumé court, et mettant en avant le message que veut faire passer l'article, ce qu'on est censés retenir ou l'opinion qu'on est censés se faire
        2) Liste les faits (chaque fait dans {"texte": "..."}).
        3) Liste les opinions (phrases subjectives).

        Réponds STRICTEMENT au format JSON :
        {
          "resume": "...",
          "faits": [{"texte":"..."}],
          "opinions": ["...", "..."]
        }
        """
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt + "\n\nTexte :\n" + text}]
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

# 🟣 ÉTAPE 3 — Entités clés
def extract_entities(text: str):
        """
        Analyse le texte et identifie les PRINCIPALES ASSERTIONS vérifiables qu’il contient.

        Une assertion = une phrase qui présente un fait, une implication, un présupposé ou une conséquence supposée vraie par le texte.

        Exemples :
        - “X est pressenti pour…”
        - “Selon le texte, Y pourrait permettre de…”
        - “Il est affirmé que…”
        - “Le texte suggère que…”

        Règles :
        - Extrais entre 3 et 6 assertions MAX.
        - Chaque assertion doit être formulée clairement, comme une proposition factuelle qu’on peut vérifier sur des sources fiables.
        - Pas de résumé, pas de mots-clés : uniquement des affirmations vérifiables.

        Format STRICT :
        [
          "assertion 1",
          "assertion 2",
          "assertion 3"
        ]
        """
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Extrais les principales assertions vérifiables du texte.\n\nTexte :\n" + text}]
        )
        data = extract_json(resp.choices[0].message.content, [])

        log_data("Entités détectées", data)

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
        for ent in entities[:3]:  # on limite à 3 entités pour ne pas exploser le quota
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
        Tu es un assistant qui compare un article avec des sources fiables.

        Voici :
        - summary: résumé de l'article + faits extraits
        - web_hits: extraits d'articles de presse fiables

        Identifie :
        - faits manquants (informations importantes présentes dans le web mais pas dans le texte)
        - contradictions (le texte dit X, les sources disent Y)
        - divergences (angles ou formulations très différentes)
        - impact global : "faible", "modéré", ou "fort"

        Réponds STRICTEMENT en JSON :
        {
          "faits_manquants": ["...", "..."],
          "contradictions": ["...", "..."],
          "divergences": ["...", "..."],
          "impact": "faible"
        }
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
    6️⃣ À partir de tout ce qu'on a vu, on attribue des notes :
        - fond / justesse
        - fond / complétude
        - forme / ton
        - forme / sophismes
    """
    with StepTimer("Étape 6 - Évaluation des axes"):
        log("[6/8] Étape 6", "Évaluation des 4 axes…", C_BLUE)

        prompt = """
        Tu évalues la fiabilité d'un article selon 4 axes (0 à 100).

        Contexte :
        - global_msg: message principal de l'article
        - summary: résumé + faits/opinions
        - web_facts: extraits d'articles fiables
        - diffs: analyse des faits manquants/contradictions/divergences

        Axes :
        - fond.justesse      : exactitude des faits
        - fond.completude    : article oublie-t-il des infos importantes ?
        - forme.ton          : neutralité vs biais
        - forme.sophismes    : qualité du raisonnement (peu / beaucoup de sophismes)

        Réponds STRICTEMENT au format JSON :
        {
          "axes": {
            "fond": {
              "justesse":  {"note": 0, "justification": "", "citation": ""},
              "completude":{"note": 0, "justification": "", "citation": ""}
            },
            "forme": {
              "ton":       {"note": 0, "justification": "", "citation": ""},
              "sophismes": {"note": 0, "justification": "", "citation": ""}
            }
          }
        }
        """

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

        log_data("Note justesse", fond.get("justesse", {}).get("note", "—"))
        log_data("Note complétude", fond.get("completude", {}).get("note", "—"))
        log_data("Note ton", forme.get("ton", {}).get("note", "—"))
        log_data("Note sophismes", forme.get("sophismes", {}).get("note", "—"))

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
        À partir des notes et justifications des axes, écris une synthèse
        en 3 courts paragraphes, en français, pédagogique et nuancée.

        Ne fais pas de listes.
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
    8️⃣ À partir des 4 notes, on calcule un score global pondéré.
    Fond compte plus que forme.
    """
    with StepTimer("Étape 8 - Score global"):
        log("[8/8] Étape 8", "Calcul du score global…", C_BLUE)

        fond = axes.get("fond", {})
        forme = axes.get("forme", {})

        j = fond.get("justesse", {}).get("note", 0)
        c = fond.get("completude", {}).get("note", 0)
        t = forme.get("ton", {}).get("note", 0)
        s = forme.get("sophismes", {}).get("note", 0)

        score = int(0.4 * j + 0.3 * c + 0.15 * t + 0.15 * s)
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

    # Ajout des couleurs pour chaque axe (pour le front)
    axes["fond"]["justesse"]["couleur"]   = color_for(axes["fond"]["justesse"]["note"])
    axes["fond"]["completude"]["couleur"] = color_for(axes["fond"]["completude"]["note"])
    axes["forme"]["ton"]["couleur"]       = color_for(axes["forme"]["ton"]["note"])
    axes["forme"]["sophismes"]["couleur"] = color_for(axes["forme"]["sophismes"]["note"])

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
        justesse=axes["fond"]["justesse"]["note"],
        completude=axes["fond"]["completude"]["note"],
        ton=axes["forme"]["ton"]["note"],
        sophismes=axes["forme"]["sophismes"]["note"],
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
