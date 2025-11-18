# ======================================================
# 🔵 BLOC 1/6 — IMPORTS + PYDANTIC + CONFIGURATION
# ======================================================

# ------------ IMPORTS GÉNÉRAUX ------------
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, signal, json, re, requests, urllib.parse, time
from datetime import datetime
from dotenv import load_dotenv

# Recherche web / threads
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ------------ PYDANTIC ------------
from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Optional, Any


# ======================================================
# 🔧 CONFIG FLASK & OPENAI
# ======================================================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
ENABLE_URL_EXTRACT = True


# ======================================================
# 🧩 MODÈLES PYDANTIC — CONTRAT JSON GARANTI
# ======================================================

# ---------- UN ITEM D’AXE ----------
class AxeItem(BaseModel):
    note: int = Field(default=50, ge=0, le=100)
    justification: str = ""
    exemple: str = ""
    effet: str = ""
    citation: str = ""
    couleur: str = "⚪"


# ---------- AXES FOND ----------
class AxesFond(BaseModel):
    justesse: AxeItem = AxeItem()
    completude: AxeItem = AxeItem()


# ---------- AXES FORME ----------
class AxesForme(BaseModel):
    ton: AxeItem = AxeItem()
    sophismes: AxeItem = AxeItem()


# ---------- STRUCTURE COMPLÈTE DES AXES ----------
class Axes(BaseModel):
    fond: AxesFond = AxesFond()
    forme: AxesForme = AxesForme()


# ---------- RÉPONSE FINALE (JSON RENVOYÉ AU FRONTEND) ----------
class FinalResponse(BaseModel):
    score_global: int = 50
    couleur_global: str = "⚪"
    resume: str = "Analyse non disponible."
    commentaire: str = ""
    commentaire_web: str = ""

    # Pré-analyse
    densite_faits: int = 0
    type_texte: str = ""

    # Faits/opinions/message global
    message_global: Dict[str, Any] = {}
    recherches_effectuees: List[Any] = []
    faits_web: Dict[str, Any] = {}
    diffs: Dict[str, Any] = {}

    # Axes (structure propre)
    axes: Axes = Axes()

    # Compatibilité frontend
    justesse: int = 50
    completude: int = 50
    ton: int = 50
    sophismes: int = 50

    # Débogage
    web_context: Dict[str, Any] = {}

    # Confiance interne
    confiance_analyse: int = 70
    explication_confiance: str = "Analyse interne : cohérence moyenne entre les critères."

# ======================================================
# 🟦 COMPLÉMENTS PYDANTIC MANQUANTS
# ======================================================

# Ce modèle décrit chaque entrée d’un axe en détail.
class AxisDetail(BaseModel):
    note: int = Field(default=50, ge=0, le=100)
    justification: str = ""
    exemple: str = ""
    effet: str = ""
    citation: str = ""
    couleur: str = "⚪"


# Requête envoyée par le frontend
class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1)


# Réponse complète validée envoyée au frontend
class AnalyzeResponse(BaseModel):
    score_global: int
    couleur_global: str
    resume: str
    axes: Axes

    justesse: int | None = None
    completude: int | None = None
    ton: int | None = None
    sophismes: int | None = None

    densite_faits: int = 0
    type_texte: str = ""
    message_global: dict = {}

    recherches_effectuees: list = []
    faits_web: dict = {}
    diffs: dict = {}
    web_context: dict = {}
    commentaire_web: str = ""
    commentaire: str = ""

    confiance_analyse: int = 70
    explication_confiance: str = ""


# ------------ TIMEOUT HANDLER ------------
def _timeout_handler(signum, frame):
    raise TimeoutError("Analyse trop longue (timeout Render/Replit).")

signal.signal(signal.SIGALRM, _timeout_handler)


# ------------ HELPER COULEUR ------------
def color_for(score: int) -> str:
    if score is None: return "⚪"
    if score >= 70: return "🟢"
    if score >= 40: return "🟡"
    return "🔴"




# ======================================================
# 🔵 BLOC 2/6 — RECHERCHE WEB + OUTILS D’ANALYSE
# ======================================================
# Ici :
#   - on définit les sites autorisés
#   - on interroge Google CSE en parallèle
#   - on formate le commentaire web
#   - on crée les briques IA : résumé, message global,
#     consolidation web, comparaison, évaluation, synthèse.
# ======================================================

# ------------------------------------------------------
# 2.1 — SITES AUTORISÉS POUR LA RECHERCHE WEB
# ------------------------------------------------------
ALLOWED_SITES = [
    "reuters.com", "apnews.com", "bbc.com",
    "lemonde.fr", "francetvinfo.fr",
    "lefigaro.fr", "liberation.fr", "leparisien.fr"
]


# ------------------------------------------------------
# 2.2 — RECHERCHE WEB (GOOGLE CSE)
# ------------------------------------------------------
def search_web_results(queries, per_query=5, pause=0.5):
    """
    Recherche Google Programmable Search (CSE) sur plusieurs requêtes.

    Entrée :
      - queries : liste de chaînes, ex ["Macron actualité", "Union européenne"]
    Sortie :
      - liste de blocs :
        [
          {
            "entité": "Macron actualité",
            "sources": [
              {"titre": "...", "snippet": "...", "url": "..."},
              ...
            ]
          },
          ...
        ]
    """

    api_key = os.getenv("GOOGLE_CSE_API_KEY")
    cx = os.getenv("GOOGLE_CSE_CX")

    if not api_key or not cx:
        print("⚠️ GOOGLE_CSE_API_KEY ou GOOGLE_CSE_CX manquant — recherche désactivée.")
        return []

    all_hits = []      # Tous les résultats agrégés
    seen = set()       # URLs déjà vues (pour éviter les doublons)
    seen_lock = Lock() # Verrou pour protéger `seen` dans les threads

    # Sous-fonction exécutée pour une requête donnée
    def fetch(q):
        # Filtre sur la liste de sites autorisés
        site_filter = " OR ".join([f"site:{s}" for s in ALLOWED_SITES])
        full_q = f"{q} ({site_filter})"

        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": api_key,
            "cx": cx,
            "q": full_q,
            "num": per_query,
            "hl": "fr",
            "lr": "lang_fr",
            "safe": "off",
        }

        try:
            r = requests.get(url, params=params, timeout=8)
            if r.status_code != 200:
                return q, []

            data = r.json()
            results = []

            for item in (data.get("items", []) or []):
                link = item.get("link")
                if not link:
                    continue

                # Déduplication multi-threads
                with seen_lock:
                    if link in seen:
                        continue
                    seen.add(link)

                results.append({
                    "titre": item.get("title"),
                    "snippet": item.get("snippet"),
                    "url": link
                })

            return q, results

        except Exception as e:
            print(f"⚠️ Erreur recherche Google pour '{q}':", e)
            return q, []

    # Lancement en parallèle (threads)
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch, q) for q in queries]

        for fut in as_completed(futures):
            q, results = fut.result()
            if results:
                all_hits.append({"entité": q, "sources": results})

    return all_hits


# ------------------------------------------------------
# 2.3 — COMMENTAIRE WEB LISIBLE À PARTIR DE web_info
# ------------------------------------------------------
def formate_commentaires_web(web_info: dict) -> str:
    """
    Crée un commentaire journalistique à partir :
      - des faits manquants
      - des contradictions
      - des divergences de cadrage

    Ce texte est destiné à être affiché dans une "boîte contexte"
    à côté de l’analyse principale.
    """

    commentaires = []

    # 1️⃣ Contradictions : ton “fact-check” nuancé
    for c in web_info.get("contradictions", []) or []:
        if isinstance(c, dict):
            commentaires.append(
                f"Selon {c.get('source', 'une source')}, "
                f"{(c.get('correction_ou_nuance') or '').strip()} "
                f"ce qui nuance l’affirmation du texte "
                f"({(c.get('affirmation_du_texte') or '').strip()})."
            )
        elif isinstance(c, str):
            commentaires.append(c.strip())

    # 2️⃣ Faits manquants : ton “analyse critique”
    for f in web_info.get("faits_manquants", []) or []:
        if isinstance(f, dict):
            commentaires.append(
                f"Le texte n’évoque pas {(f.get('description') or '').strip()} "
                f"(mentionné par {f.get('source', 'une autre source')}). "
                f"{(f.get('explication') or '').strip()}"
            )

    # 3️⃣ Divergences de cadrage : ton “analyse narrative”
    for d in web_info.get("divergences_de_cadrage", []) or []:
        if isinstance(d, dict):
            commentaires.append(
                f"Le cadrage diffère : {(d.get('resume') or '').strip()} "
                f"{(d.get('impact') or '').strip()}"
            )

    # 4️⃣ Synthèse finale courte si disponible
    synth = web_info.get("synthese", "")
    if synth:
        commentaires.append((synth or "").strip())

    return " ".join(commentaires[:5]) or "Aucun écart majeur entre le texte et les sources consultées."


# ======================================================
# 2.4 — BRIQUES IA : RÉSUMÉ, MESSAGE GLOBAL, WEB FACTS
# ======================================================

# -------------------------
# 4.1 — Résumé + faits/opinions
# -------------------------
def summarize_text(client: OpenAI, text: str) -> dict:
    """
    Étape 1 :
      - Résume le texte
      - Liste les faits (avec extraits)
      - Liste les opinions
    """

    prompt = f"""
    Résume le texte suivant de manière neutre, puis liste :
    - Les faits (affirmations vérifiables)
    - Les opinions (jugements, interprétations).

    Pour chaque fait, fournis un extrait (≤15 mots) prouvant d’où tu le tires.

    Réponds UNIQUEMENT en JSON :
    {{
      "resume": "...",
      "faits": [{{"texte": "...", "extrait_article": "..."}}],
      "opinions": ["...", "..."]
    }}

    Texte :
    {text[:4000]}
    """

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Tu es un journaliste neutre. Sépare faits/opinions avec extraits précis."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
        )

        raw = resp.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(match.group(0)) if match else {
            "resume": "",
            "faits": [],
            "opinions": []
        }

    except Exception as e:
        print("⚠️ summarize_text error:", e)
        return {"resume": "", "faits": [], "opinions": []}


# -------------------------
# 4.2 — Message global perçu
# -------------------------
def extract_global_message(client: OpenAI, text: str) -> dict:
    """
    Étape 0 :
      - message global retenu
      - ton
      - intention perçue
      - niveau de confiance
      - impression émotionnelle
    """

    prompt = f"""
    Lis ce texte comme un lecteur moyen.
    Décris :
    1) Message global retenu
    2) Ton général
    3) Intention perçue
    4) Niveau de confiance
    5) Impression émotionnelle

    Réponds UNIQUEMENT en JSON :
    {{
      "message_global": "...",
      "ton_general": "...",
      "intention_perçue": "...",
      "niveau_de_confiance": "...",
      "resume_emotionnel": "..."
    }}

    Texte :
    {text[:4000]}
    """

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu décris ce que retient un lecteur moyen."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.35,
        )
        raw = resp.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group(0)) if m else {}

    except Exception as e:
        print("⚠️ extract_global_message error:", e)
        return {}


# -------------------------
# 4.3 — Faits web consolidés
# -------------------------
def consolidate_web_facts(client: OpenAI, web_hits: list) -> dict:
    """
    Étape 2 :
      - Convertit les résultats web bruts → liste de faits sourcés.
    """

    prompt = f"""
    Convertis ces extraits web en faits vérifiables et neutres.
    Pour chaque fait : indique la source, l’URL et un extrait court.

    Réponds UNIQUEMENT en JSON :
    {{
      "faits_web": [
        {{"fait": "...", "source": "...", "url": "...", "extrait_source": "..."}}
      ]
    }}

    Extraits web :
    {json.dumps(web_hits, ensure_ascii=False, indent=2)}
    """

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu identifies des faits web neutres et sourcés."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
        )

        raw = resp.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(match.group(0)) if match else {"faits_web": []}

    except Exception as e:
        print("⚠️ consolidate_web_facts error:", e)
        return {"faits_web": []}


# -------------------------
# 4.4 — Comparaison texte vs web
# -------------------------
def compare_text_with_web(client: OpenAI, summary: dict, web_facts: dict) -> dict:
    """
    Étape 3 :
      - Faits manquants
      - Contradictions
      - Divergences de cadrage
    """

    prompt = f"""
    Compare les faits du texte et les faits web.
    Identifie :
      - faits manquants
      - contradictions
      - divergences de cadrage

    Pour chaque cas, donne un extrait du texte + un extrait source.

    Réponds UNIQUEMENT en JSON :
    {{
      "faits_manquants": [...],
      "contradictions": [...],
      "divergences_de_cadrage": [...],
      "impact": "faible|moyen|fort"
    }}

    FAITS DU TEXTE :
    {json.dumps(summary, ensure_ascii=False, indent=2)}

    FAITS DU WEB :
    {json.dumps(web_facts, ensure_ascii=False, indent=2)}
    """

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu compares texte et sources web."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
        )

        raw = resp.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group(0)) if m else {
            "faits_manquants": [],
            "contradictions": [],
            "divergences_de_cadrage": [],
            "impact": "faible"
        }

    except Exception as e:
        print("⚠️ compare_text_with_web error:", e)
        return {
            "faits_manquants": [],
            "contradictions": [],
            "divergences_de_cadrage": [],
            "impact": "faible"
        }


# ======================================================
# 2.5 — SCORE GLOBAL + RECHERCHE CONTEXTUELLE
# ======================================================

# -------------------------
# Score global (0–100)
# -------------------------
def compute_global_score(evals_axes: dict, diffs_impact: str, densite_faits: int) -> int:
    """
    Calcule un score global final (0–100) selon 4 pondérations :
      - Justesse       (40%)
      - Complétude     (30%)
      - Ton            (15%)
      - Sophismes      (15%)

    Ajustements :
      - Impact 'fort' : -10 si Justesse < 60 ou Complétude < 60
      - Impact 'moyen': -5  si Justesse < 60 ou Complétude < 60
      - Densité factuelle : +5 si >60%, -5 si <30%
    """

    try:
        j = int(evals_axes["fond"]["justesse"]["note"])
        c = int(evals_axes["fond"]["completude"]["note"])
        t = int(evals_axes["forme"]["ton"]["note"])
        s = int(evals_axes["forme"]["sophismes"]["note"])
    except Exception:
        return 50  # Sécurité en cas de JSON partiel

    base = 0.4 * j + 0.3 * c + 0.15 * t + 0.15 * s

    impact = (diffs_impact or "faible").lower().strip()
    if (j < 60 or c < 60):
        if impact == "fort":
            base -= 10
        elif impact == "moyen":
            base -= 5

    if densite_faits > 60:
        base += 5
    elif densite_faits < 30:
        base -= 5

    return max(0, min(100, round(base)))


# -------------------------
# Recherche web contextuelle (NER → web → synthèse)
# -------------------------
def web_context_research(text: str) -> dict:
    """
    Étape d’enrichissement factuel :
      1) extraction d’entités (NER)
      2) recherche web (Google CSE)
      3) synthèse journalistique IA
    """

    try:
        # 1️⃣ Entités NER
        ent_prompt = f"""
        Extrait les principales entités (personnes, lieux, organisations, événements)
        du texte suivant :
        {text[:2000]}

        Réponds UNIQUEMENT en JSON : ["entité1", "entité2", ...]
        """

        ent_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un extracteur d'entités journalistiques (NER)."},
                {"role": "user", "content": ent_prompt}
            ],
            temperature=0,
        )

        raw_entities = ent_resp.choices[0].message.content.strip()
        m = re.search(r"\[.*\]", raw_entities, re.DOTALL)
        entities = json.loads(m.group(0)) if m else []

        entities = [
            e for e in entities
            if isinstance(e, str) and e.strip() and len(e.strip()) >= 2
        ]

        if not entities:
            return {
                "recherches_effectuees": [],
                "faits_manquants": [],
                "contradictions": [],
                "divergences_de_cadrage": [],
                "impact": "faible",
                "fiabilite_sources": "Aucune entité détectée.",
                "synthese": "Impossible d’enrichir : aucune entité détectée."
            }

        # 2️⃣ Recherche web
        queries = [f"{ent} actualité" for ent in entities[:3]]
        print("🌍 Recherche web sur :", entities)
        recherches = search_web_results(queries, per_query=4)

        # 3️⃣ Synthèse IA
        synth_prompt = f"""
        Compare le texte suivant avec les sources ci-dessous.
        Identifie :
        - faits manquants
        - contradictions
        - divergences de cadrage

        Réponds UNIQUEMENT en JSON :
        {{
          "faits_manquants": [...],
          "contradictions": [...],
          "divergences_de_cadrage": [...],
          "impact": "faible|moyen|fort",
          "fiabilite_sources": "...",
          "synthese": "..."
        }}

        TEXTE :
        {text}

        SOURCES :
        {json.dumps(recherches, ensure_ascii=False, indent=2)}
        """

        synth_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un fact-checker journalistique neutre."},
                {"role": "user", "content": synth_prompt}
            ],
            temperature=0.3,
        )

        content = synth_resp.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", content, re.DOTALL)
        result = json.loads(m.group(0)) if m else {}

        result["recherches_effectuees"] = recherches
        return result

    except Exception as e:
        print("⚠️ web_context_research failed:", e)
        return {
            "recherches_effectuees": [],
            "faits_manquants": [],
            "contradictions": [],
            "divergences_de_cadrage": [],
            "impact": "faible",
            "fiabilite_sources": "Erreur interne durant la recherche.",
            "synthese": "Recherche contextuelle indisponible."
        }


# ======================================================
# 2.6 — SYNTHÈSE NARRATIVE & ÉVALUATION PAR AXES
# ======================================================

def evaluate_text(client: OpenAI, summary: dict, web_facts: dict, diffs: dict, global_msg: Optional[dict] = None) -> dict:
    """
    Étape 4 :
      - Note sur 4 axes :
          justesse, complétude, ton, sophismes
      - Renvoie un JSON de la forme :
        { "axes": { "fond": {...}, "forme": {...} } }
    """

    msg_context = (global_msg or {}).get("message_global", "")

    prompt = f"""
    Tu évalues le texte sur 4 axes : justesse, complétude, ton, rigueur argumentative.

    Structure OBLIGATOIRE :
    {{
      "axes": {{
        "fond": {{
          "justesse": {{
            "note": <0-100>,
            "justification": "...",
            "citation": "...",
            "exemple": "...",
            "effet": "..."
          }},
          "completude": {{
            "note": <0-100>,
            "justification": "...",
            "citation": "...",
            "exemple": "...",
            "effet": "..."
          }}
        }},
        "forme": {{
          "ton": {{
            "note": <0-100>,
            "justification": "...",
            "citation": "...",
            "exemple": "...",
            "effet": "..."
          }},
          "sophismes": {{
            "note": <0-100>,
            "justification": "...",
            "citation": "...",
            "exemple": "...",
            "effet": "..."
          }}
        }}
      }}
    }}

    Règles :
      - Donne un exemple précis pour chaque critère.
      - Explique l’effet sur le lecteur.
      - Réponds UNIQUEMENT avec du JSON.

    Contexte perçu : "{msg_context}"

    Résumé :
    {json.dumps(summary, ensure_ascii=False, indent=2)}

    Faits web :
    {json.dumps(web_facts, ensure_ascii=False, indent=2)}

    Différences texte/web :
    {json.dumps(diffs, ensure_ascii=False, indent=2)}
    """

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Analyste pédagogique, concret, avec exemples."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.25,
        )

        raw = resp.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {"axes": {}}
        return parsed

    except Exception as e:
        print("⚠️ evaluate_text error:", e)
        return {"axes": {}}


def synthesize_from_axes(client: OpenAI, evaluation: dict) -> str:
    """
    Étape 5 :
      - 3 paragraphes :
          1) Ce que le texte fait croire
          2) Ce qui manque / simplifie
          3) Effet global sur la compréhension
      - Jamais de score dans la synthèse.
    """

    prompt = f"""
    Écris une synthèse en 3 blocs :
    1) Ce que le texte fait croire (message + ton + présentation)
    2) Ce qui manque ou simplifie (exemples + effet lecteur)
    3) Effet global sur la compréhension

    Interdits :
      - aucune note ou score
      - pas de jargon

    Matière :
    {json.dumps(evaluation, ensure_ascii=False, indent=2)}
    """

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un journaliste explicateur, clair et concret."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.35,
        )

        return resp.choices[0].message.content.strip()

    except Exception as e:
        print("⚠️ synthesize_from_axes error:", e)
        return "Synthèse non disponible."




# ======================================================
# 🔵 BLOC 3/6 — ROUTE PRINCIPALE /analyze
# ======================================================
# Pipeline complet :
#   1) Préparation du texte (URL, tronquage)
#   2) Pré-analyse (faits/opinions/autres)
#   3) Lancement parallèle :
#        - extract_global_message
#        - summarize_text
#        - web_context_research
#   4) Consolidation :
#        - faits web
#        - comparaison texte ↔ web
#   5) Évaluation (4 axes)
#   6) Score global + couleur
#   7) Synthèse narrative
#   8) Construction de la réponse pour le frontend
# ======================================================


@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    # CORS preflight
    if request.method == "OPTIONS":
        return ("", 204)

    # --------------------------------------------------
    # 3.1 — RÉCUPÉRATION & VALIDATION DE L’ENTRÉE
    # --------------------------------------------------
    payload = request.get_json(silent=True) or {}

    try:
        parsed = AnalyzeRequest(**payload)
    except ValidationError:
        return jsonify({"error": "Aucun texte reçu"}), 400

    text = (parsed.text or "").strip()
    if not text:
        return jsonify({"error": "Aucun texte reçu"}), 400

    # --------------------------------------------------
    # 3.2 — EXTRACTION D’URL VIA TRAFILATURA (si activée)
    # --------------------------------------------------
    if ENABLE_URL_EXTRACT and re.match(r"^https?://", text):
        try:
            import trafilatura

            downloaded = trafilatura.fetch_url(text)
            fetched = trafilatura.extract(downloaded) or ""
            if len(fetched.strip()) >= 300:
                text = fetched.strip()[:8000]
                print(f"✅ Trafilatura OK (len={len(text)})")
            else:
                print("⚠️ Extraction trop courte → texte brut conservé.")
        except Exception as e:
            print("⚠️ Trafilatura indisponible :", e)

    # --------------------------------------------------
    # 3.3 — TRONQUAGE DE SÉCURITÉ (taille max)
    # --------------------------------------------------
    MAX_LEN = 8000
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN] + " […] (tronqué pour analyse)"

    # --------------------------------------------------
    # 3.4 — PRÉ-ANALYSE (densité factuelle)
    # --------------------------------------------------
    try:
        pre_prompt = f"""
        Classe le texte selon 3 catégories :
        - FAITS (affirmations vérifiables)
        - OPINIONS (jugements)
        - AUTRES (récit, humour, etc.)

        Réponds uniquement en JSON :
        {{
          "faits": <int>,
          "opinions": <int>,
          "autres": <int>
        }}

        Texte :
        {text[:2000]}
        """

        pre_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Tu es un linguiste qui classe les phrases.",
                },
                {"role": "user", "content": pre_prompt},
            ],
            temperature=0,
        )
        raw = pre_resp.choices[0].message.content.strip()
        try:
            fact_mix = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            fact_mix = json.loads(m.group(0)) if m else {
                "faits": 0,
                "opinions": 0,
                "autres": 0,
            }

    except Exception as e:
        print("⚠️ Erreur pré-analyse :", e)
        fact_mix = {"faits": 0, "opinions": 0, "autres": 0}

    total = sum(fact_mix.values()) or 1
    densite_faits = int((fact_mix["faits"] / total) * 100)

    type_texte = (
        "Principalement factuel" if densite_faits > 60 else
        "Opinion ou analyse" if fact_mix["opinions"] > 40 else
        "Autre (narratif, satirique…)"
    )

    # --------------------------------------------------
    # 3.5 — PIPELINE PRINCIPAL EN PARALLÈLE
    # --------------------------------------------------
    try:
        signal.alarm(120)  # sécurité anti-timeout

        with ThreadPoolExecutor(max_workers=3) as executor:
            f_msg = executor.submit(extract_global_message, client, text)
            f_sum = executor.submit(summarize_text, client, text)
            f_webc = executor.submit(web_context_research, text)

            global_msg = f_msg.result()
            summary = f_sum.result()
            web_info = f_webc.result()

        # --------------------------------------------------
        # 3.6 — CONSOLIDATION WEB & COMPARAISON
        # --------------------------------------------------
        web_hits = web_info.get("recherches_effectuees", [])
        web_facts = consolidate_web_facts(client, web_hits)
        diffs = compare_text_with_web(client, summary, web_facts)

        # Ajuster l’impact selon le message global perçu
        if global_msg and "message_global" in global_msg:
            mg = (global_msg.get("message_global") or "").lower()
            if any(w in mg for w in ("consensus", "unanimité", "apaisé")) and diffs.get("faits_manquants"):
                diffs["impact"] = "fort"
            elif any(w in mg for w in ("controverse", "critique", "division")):
                diffs["impact"] = "moyen"

        # --------------------------------------------------
        # 3.7 — ÉVALUATION PAR AXES (justesse, complétude…)
        # --------------------------------------------------
        evals_axes_full = evaluate_text(client, summary, web_facts, diffs, global_msg)
        axes_struct = evals_axes_full.get("axes", {})

        # Sécurité : structure par défaut si l’IA a raté le format
        axes_struct.setdefault("fond", {})
        axes_struct.setdefault("forme", {})


        # Valeur par défaut pour un axe si l'IA n'a pas retourné le bon format
        fallback = {
            "note": 50,
            "justification": "Analyse non disponible",
            "citation": "",
            "severity_for_reader": "moyenne"
        }

        axes_struct["fond"].setdefault("justesse", fallback.copy())
        axes_struct["fond"].setdefault("completude", fallback.copy())
        axes_struct["forme"].setdefault("ton", fallback.copy())
        axes_struct["forme"].setdefault("sophismes", fallback.copy())


        # --------------------------------------------------
        # 3.8 — SCORE GLOBAL (avec densité factuelle)
        # --------------------------------------------------
        base_score = compute_global_score(
            axes_struct,
            diffs.get("impact"),
            densite_faits,
        )

        # Lissage selon densité factuelle
        score_global = base_score
        if densite_faits > 60:
            score_global = min(score_global + 5, 100)
        elif densite_faits < 30:
            score_global = max(score_global - 5, 0)

        # --------------------------------------------------
        # 3.9 — COULEURS PAR AXE + PATCH COMPAT FRONTEND
        # --------------------------------------------------
        try:
            axes_struct["fond"]["justesse"]["couleur"] = color_for(
                axes_struct["fond"]["justesse"].get("note")
            )
            axes_struct["fond"]["completude"]["couleur"] = color_for(
                axes_struct["fond"]["completude"].get("note")
            )
            axes_struct["forme"]["ton"]["couleur"] = color_for(
                axes_struct["forme"]["ton"].get("note")
            )
            axes_struct["forme"]["sophismes"]["couleur"] = color_for(
                axes_struct["forme"]["sophismes"].get("note")
            )
        except Exception as e:
            print("⚠️ Impossible d’ajouter les couleurs aux axes :", e)

        # Champs à plat pour le radar du frontend (compat)
        justesse_note = axes_struct["fond"]["justesse"].get("note")
        completude_note = axes_struct["fond"]["completude"].get("note")
        ton_note = axes_struct["forme"]["ton"].get("note")
        sophismes_note = axes_struct["forme"]["sophismes"].get("note")

        # --------------------------------------------------
        # 3.10 — SYNTHÈSE NARRATIVE (3 paragraphes)
        # --------------------------------------------------
        synthèse = synthesize_from_axes(
            client,
            {
                "axes": axes_struct,
                "score_global": score_global,
                "densite_faits": densite_faits,
                "type_texte": type_texte,
                "message_global": global_msg,
            },
        )

        # --------------------------------------------------
        # 3.11 — CONSTRUCTION DE LA RÉPONSE (backend → frontend)
        # --------------------------------------------------
        response_payload = {
            # Score global + couleur
            "score_global": score_global,
            "couleur_global": color_for(score_global),

            # Synthèse
            "resume": synthèse,
            "commentaire": synthèse,  # compat ancien frontend

            # Axes détaillés
            "axes": axes_struct,
            "justesse": justesse_note,
            "completude": completude_note,
            "ton": ton_note,
            "sophismes": sophismes_note,

            # Métadonnées de texte
            "densite_faits": densite_faits,
            "type_texte": type_texte,
            "message_global": global_msg,

            # Contexte web et commentaire associé
            "recherches_effectuees": web_hits,
            "faits_web": web_facts,
            "diffs": diffs,
            "web_context": web_info,
            "commentaire_web": formate_commentaires_web(web_info),

            # Confiance de l’analyse (proxy : score global)
            "confiance_analyse": score_global,
            "explication_confiance": "Analyse interne : cohérence moyenne entre les critères.",
        }

        # --------------------------------------------------
        # 3.12 — LOGGING LOCAL (logs.jsonl)
        # --------------------------------------------------
        try:
            log_item = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "input_len": len(text),
                "type_texte": type_texte,
                "densite_faits": densite_faits,
                "score_global": score_global,
                "axes": axes_struct,
                "resume": synthèse,
            }
            with open("logs.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_item, ensure_ascii=False) + "\n")
        except Exception as e:
            print("ℹ️ Échec écriture logs.jsonl :", e)

        # Optionnel : valider la structure de sortie avec Pydantic
        # (sécurité supplémentaire, mais pas obligatoire)
        try:
            resp_model = AnalyzeResponse(
                score_global=score_global,
                couleur_global=color_for(score_global),
                resume=synthèse,
                axes=Axes(
                    fond=AxesFond(
                        justesse=AxisDetail(**axes_struct["fond"]["justesse"]),
                        completude=AxisDetail(**axes_struct["fond"]["completude"]),
                    ),
                    forme=AxesForme(
                        ton=AxisDetail(**axes_struct["forme"]["ton"]),
                        sophismes=AxisDetail(**axes_struct["forme"]["sophismes"]),
                    ),
                ),
                densite_faits=densite_faits,
                type_texte=type_texte,
                message_global=global_msg,
                recherches_effectuees=web_hits,
                faits_web=web_facts,
                diffs=diffs,
                web_context=web_info,
                commentaire_web=response_payload["commentaire_web"],
                commentaire=response_payload["commentaire"],
                confiance_analyse=response_payload["confiance_analyse"],
                explication_confiance=response_payload["explication_confiance"],
            )
            # On retourne le dict validé (et compatible frontend)
            return jsonify(resp_model.model_dump())
        except Exception as e:
            # Si la validation Pydantic échoue, on renvoie quand même le dict brut
            print("⚠️ Validation Pydantic AnalyzeResponse échouée :", e)
            return jsonify(response_payload)

    except TimeoutError:
        return jsonify({"error": "Analyse trop longue (timeout)."}), 500

    except Exception as e:
        print("❌ Erreur pipeline analyze() :", e)
        return jsonify({"error": str(e)}), 500

    finally:
        signal.alarm(0)  # toujours désarmer le timeout


# ======================================================
# 🔵 BLOC 4/6 — HISTORIQUE DES ANALYSES (/logs)
# ======================================================

@app.route("/logs", methods=["GET"])
def get_logs():
    """
    Retourne les 50 dernières analyses enregistrées dans logs.jsonl.
    Format : liste de JSON (timestamp, score, densité de faits, etc.)
    """
    logs = []

    try:
        if os.path.exists("logs.jsonl"):
            with open("logs.jsonl", "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        logs.append(json.loads(line))
                    except Exception:
                        continue  # ligne corrompue ignorée

        logs = sorted(
            logs,
            key=lambda x: x.get("timestamp", ""),
            reverse=True,
        )[:50]

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(logs)


# ======================================================
# 🔵 BLOC 5/6 — DIAGNOSTIC /version
# ======================================================

@app.route("/version", methods=["GET"])
def version():
    """
    Endpoint de diagnostic.
    Permet de vérifier que l'API est vivante et d'afficher un label de version.
    """
    return jsonify({
        "version": "De Facto v2.8-explicable-CSE-pyramid-pydantic",
        "status": "✅ actif"
    })


# ======================================================
# 🔵 BLOC 6/6 — FRONTEND (Replit) + LANCEMENT SERVEUR
# ======================================================

if os.getenv("REPL_ID"):
    @app.route("/")
    def serve_frontend():
        """Sert le fichier frontend/index.html comme page d'accueil en mode Replit."""
        return send_from_directory(
            os.path.join(os.getcwd(), "frontend"),
            "index.html"
        )

    @app.route("/<path:path>")
    def serve_static(path: str):
        """
        Sert les fichiers statiques du dossier frontend (JS, CSS, images).
        Si le fichier demandé n'existe pas, on renvoie index.html
        pour laisser le frontend (ex: React) gérer le routage.
        """
        frontend_path = os.path.join(os.getcwd(), "frontend")
        file_path = os.path.join(frontend_path, path)

        if os.path.exists(file_path):
            return send_from_directory(frontend_path, path)
        else:
            return send_from_directory(frontend_path, "index.html")


if __name__ == "__main__":
    # Lancement du serveur Flask
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
    )
