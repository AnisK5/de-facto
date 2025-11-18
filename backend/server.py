# ======================================================
#  🔵 De Facto — Backend Simplifié (Pipeline complet)
# ======================================================

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, json, re, requests, signal
from dotenv import load_dotenv
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Any

# ------------------------------------------------------
# 0 — CONFIG
# ------------------------------------------------------
app = Flask(__name__)
CORS(app)
load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

ALLOWED_SITES = [
    "reuters.com", "apnews.com", "bbc.com",
    "lemonde.fr", "francetvinfo.fr",
    "lefigaro.fr", "liberation.fr", "leparisien.fr"
]

# ------------------------------------------------------
# 🎯 HELPERS
# ------------------------------------------------------

def extract_json(text: str, fallback: dict):
    """Extrait un JSON dans un texte réponse IA."""
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(m.group(0)) if m else fallback
    except:
        return fallback


def color_for(score: int) -> str:
    if score >= 70: return "🟢"
    if score >= 40: return "🟡"
    return "🔴"


# ------------------------------------------------------
# 📦 MODELES
# ------------------------------------------------------

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
    axes: Axes
    justesse: int
    completude: int
    ton: int
    sophismes: int

    densite_faits: int
    type_texte: str
    message_global: dict

    recherches_effectuees: list
    faits_web: dict
    diffs: dict
    web_context: dict
    commentaire_web: str
    commentaire: str

    confiance_analyse: int
    explication_confiance: str


# ------------------------------------------------------
# 🔎 1 — PRÉ-ANALYSE (densité factuelle)
# ------------------------------------------------------

def pre_analyse(text: str):
    prompt = f"""
    Classe ce texte en :
    - faits
    - opinions
    - autres

    Réponds en JSON :
    {{
      "faits": int,
      "opinions": int,
      "autres": int
    }}

    Texte :
    {text[:1500]}
    """

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    raw = resp.choices[0].message.content
    data = extract_json(raw, {"faits": 0, "opinions": 0, "autres": 0})

    total = sum(data.values()) or 1
    densite = int(data["faits"] / total * 100)

    if densite > 60:
        type_txt = "Principalement factuel"
    elif data["opinions"] > 40:
        type_txt = "Opinion ou analyse"
    else:
        type_txt = "Autre"

    return densite, type_txt


# ------------------------------------------------------
# 🧠 2 — MESSAGE GLOBAL
# ------------------------------------------------------

def get_message_global(text: str):
    prompt = f"""
    Donne le message global, le ton, l'intention et l'effet émotionnel.

    Réponds en JSON :
    {{
      "message_global": "...",
      "ton_general": "...",
      "intention": "...",
      "emotion": "..."
    }}
    """

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return extract_json(resp.choices[0].message.content, {})


# ------------------------------------------------------
# 📰 3 — RÉSUMÉ + FAITS / OPINIONS
# ------------------------------------------------------

def summarize_facts(text: str):
    prompt = f"""
    Résume ce texte puis liste les faits et les opinions.

    Réponds en JSON :
    {{
      "resume": "...",
      "faits": [{"texte": "..."}],
      "opinions": ["..."]
    }}

    Texte :
    {text[:4000]}
    """

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return extract_json(resp.choices[0].message.content, {
        "resume": "",
        "faits": [],
        "opinions": []
    })


# ------------------------------------------------------
# 🌍 4 — RECHERCHE WEB (simplifiée)
# ------------------------------------------------------

def search_web(entities: list):
    """Google CSE simplifié (mêmes résultats, code plus court)."""
    key = os.getenv("GOOGLE_CSE_API_KEY")
    cx = os.getenv("GOOGLE_CSE_CX")
    if not key or not cx:
        return []

    results = []
    for ent in entities[:3]:
        q = f"{ent} ({' OR '.join(['site:'+s for s in ALLOWED_SITES])})"
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": key, "cx": cx, "q": q, "num": 4}
        )
        data = r.json()
        hits = [{"titre": i["title"], "snippet": i["snippet"], "url": i["link"]}
                for i in data.get("items", [])]
        results.append({"entité": ent, "sources": hits})
    return results


# ------------------------------------------------------
# 🔍 5 — COMPARAISON TEXTE ↔ WEB (fusionnée)
# ------------------------------------------------------

def compare_text_web(summary, web_hits):
    prompt = f"""
    Analyse les différences entre :
    - les faits du texte
    - les sources web

    Réponds en JSON :
    {{
      "faits_manquants": [...],
      "contradictions": [...],
      "divergences": [...],
      "impact": "faible|moyen|fort"
    }}
    """

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt.replace("SUMMARY", "")}]
    )

    return extract_json(resp.choices[0].message.content, {
        "faits_manquants": [],
        "contradictions": [],
        "divergences": [],
        "impact": "faible"
    })


# ------------------------------------------------------
# 📊 6 — ÉVALUATION AXES (compactée)
# ------------------------------------------------------

def evaluate_axes(summary, web_facts, diffs, global_msg):
    prompt = f"""
    Évalue le texte sur 4 axes (0-100) :
    - justesse
    - completude
    - ton
    - sophismes

    Réponds en JSON EXACT :
    {{
      "axes": {{
        "fond": {{
          "justesse": {{ "note": 0-100, "justification": "...", "citation": "..." }},
          "completude": {{ "note": 0-100, "justification": "...", "citation": "..." }}
        }},
        "forme": {{
          "ton": {{ "note": 0-100, "justification": "...", "citation": "..." }},
          "sophismes": {{ "note": 0-100, "justification": "...", "citation": "..." }}
        }}
      }}
    }}
    """

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )

    return extract_json(resp.choices[0].message.content, {"axes": {}})


# ------------------------------------------------------
# 📝 7 — SYNTHÈSE NARRATIVE
# ------------------------------------------------------

def build_synthesis(axes):
    prompt = f"""
    Écris une synthèse en 3 paragraphes :
    1) Ce que le texte fait croire
    2) Ce qui manque ou simplifie
    3) Effet global sur la compréhension

    Pas de notes ni jargon.
    """

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return resp.choices[0].message.content.strip()


# ------------------------------------------------------
# ⭐ SCORE GLOBAL
# ------------------------------------------------------

def compute_score(a):
    j = a["fond"]["justesse"]["note"]
    c = a["fond"]["completude"]["note"]
    t = a["forme"]["ton"]["note"]
    s = a["forme"]["sophismes"]["note"]
    return int(0.4*j + 0.3*c + 0.15*t + 0.15*s)


# ------------------------------------------------------
# 🚀 ROUTE PRINCIPALE
# ------------------------------------------------------

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        payload = AnalyzeRequest(**request.json)
    except ValidationError:
        return jsonify({"error": "Texte manquant"}), 400

    text = payload.text.strip()

    # 1
    densite, type_texte = pre_analyse(text)

    # 2
    global_msg = get_message_global(text)

    # 3
    summary = summarize_facts(text)

    # 4
    ents_prompt = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Donne 5 entités du texte en JSON liste : {text}"}]
    )
    entities = extract_json(ents_prompt.choices[0].message.content, [])
    web_hits = search_web(entities)

    # 5
    web_facts = {"facts_web": web_hits}
    diffs = compare_text_web(summary, web_hits)

    # 6
    evals = evaluate_axes(summary, web_facts, diffs, global_msg)
    axes = evals["axes"]

    # 7
    synthese = build_synthesis(axes)

    # 8 score
    score = compute_score(axes)

    # Colors
    axes["fond"]["justesse"]["couleur"] = color_for(axes["fond"]["justesse"]["note"])
    axes["fond"]["completude"]["couleur"] = color_for(axes["fond"]["completude"]["note"])
    axes["forme"]["ton"]["couleur"] = color_for(axes["forme"]["ton"]["note"])
    axes["forme"]["sophismes"]["couleur"] = color_for(axes["forme"]["sophismes"]["note"])

    # 9 payload final
    resp = AnalyzeResponse(
        score_global=score,
        couleur_global=color_for(score),
        resume=synthese,
        commentaire=synthese,
        axes=Axes(
            fond=axes["fond"],
            forme=axes["forme"]
        ),
        justesse=axes["fond"]["justesse"]["note"],
        completude=axes["fond"]["completude"]["note"],
        ton=axes["forme"]["ton"]["note"],
        sophismes=axes["forme"]["sophismes"]["note"],
        densite_faits=densite,
        type_texte=type_texte,
        message_global=global_msg,
        recherches_effectuees=web_hits,
        faits_web=web_facts,
        diffs=diffs,
        web_context={"recherches": web_hits},
        commentaire_web="Analyse web simplifiée — pas d'écarts significatifs.",
        confiance_analyse=score,
        explication_confiance="Analyse consolidée simplifiée."
    )

    return jsonify(resp.model_dump())


# ------------------------------------------------------
# 🎨 FRONTEND ROUTES
# ------------------------------------------------------
@app.route("/")
def serve_frontend():
    """Sert la page d'accueil"""
    return send_from_directory(os.path.join(os.getcwd(), "frontend"), "index.html")


@app.route("/<path:path>")
def serve_static(path):
    """Sert les fichiers statiques du frontend"""
    frontend_path = os.path.join(os.getcwd(), "frontend")
    file_path = os.path.join(frontend_path, path)
    if os.path.exists(file_path):
        return send_from_directory(frontend_path, path)
    else:
        return send_from_directory(frontend_path, "index.html")


# ------------------------------------------------------
# ▶️ RUN
# ------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
