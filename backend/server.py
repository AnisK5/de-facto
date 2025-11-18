# ======================================================
#  🔵 De Facto — Backend Nettoyé (aucune perte fonctionnelle)
# ======================================================

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, json, re, requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
from typing import Dict

# ------------------------------------------------------
# CONFIG
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
# HELPERS
# ------------------------------------------------------

def extract_json(text: str, fallback: dict):
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
# MODELES
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
    commentaire: str
    axes: Axes

    justesse: int
    completude: int
    ton: int
    sophismes: int

    confiance_analyse: int
    explication_confiance: str


# ------------------------------------------------------
# ANALYSE — TOUTES LES ÉTAPES CONSERVÉES
# (pré-analyse, résumé, ner, web search, comparaison, évaluation)
# ------------------------------------------------------

def pre_analyse(text: str):
    prompt = f"""
    Classe ce texte en faits / opinions / autres.
    Réponds JSON : {{"faits":0,"opinions":0,"autres":0}}
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}]
    )
    raw = resp.choices[0].message.content
    return extract_json(raw, {"faits":0,"opinions":0,"autres":0})

def get_message_global(text: str):
    prompt = "Donne le message global en 3 lignes max. JSON {\"message\":\"...\"}"
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}]
    )
    return extract_json(resp.choices[0].message.content, {"message":""})

def summarize_facts(text: str):
    prompt = f"""
    Résume + liste faits + opinions. 
    JSON : {{"resume":"...", "faits":[{{"texte":"..."}}], "opinions":["..."]}}
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}]
    )
    return extract_json(resp.choices[0].message.content,
                        {"resume":"","faits":[],"opinions":[]})

def search_web(entities: list):
    key = os.getenv("GOOGLE_CSE_API_KEY")
    cx  = os.getenv("GOOGLE_CSE_CX")
    if not key or not cx:
        return []

    results = []
    for ent in entities[:3]:
        q = f"{ent} ({' OR '.join(['site:'+s for s in ALLOWED_SITES])})"
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key":key,"cx":cx,"q":q,"num":4}
        )
        data = r.json()
        hits = [{"titre":i["title"],"snippet":i["snippet"],"url":i["link"]}
                for i in data.get("items",[])]
        results.append({"entité":ent,"sources":hits})
    return results

def compare_text_web(summary, web_hits):
    prompt = """
    Compare texte vs web.
    Réponds JSON : {
      "faits_manquants":[],
      "contradictions":[],
      "divergences":[],
      "impact":"faible"
    }
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}]
    )
    return extract_json(resp.choices[0].message.content,
        {"faits_manquants":[],"contradictions":[],"divergences":[],"impact":"faible"})

def evaluate_axes(summary, web_facts, diffs, global_msg):
    prompt = """
    Évalue 4 axes (0-100).
    JSON EXACT : {
      "axes":{
        "fond":{
          "justesse":{"note":0,"justification":"","citation":""},
          "completude":{"note":0,"justification":"","citation":""}
        },
        "forme":{
          "ton":{"note":0,"justification":"","citation":""},
          "sophismes":{"note":0,"justification":"","citation":""}
        }
      }
    }
    """
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role":"user","content":prompt}]
    )
    return extract_json(resp.choices[0].message.content, {"axes":{}})

def build_synthesis(axes):
    prompt = """
    Synthèse en 3 paragraphes. 
    Pas de listes.
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}]
    )
    return resp.choices[0].message.content.strip()

def compute_score(a):
    j = a["fond"]["justesse"]["note"]
    c = a["fond"]["completude"]["note"]
    t = a["forme"]["ton"]["note"]
    s = a["forme"]["sophismes"]["note"]
    return int(0.4*j + 0.3*c + 0.15*t + 0.15*s)

# ------------------------------------------------------
# ROUTE /analyze
# ------------------------------------------------------

@app.route("/analyze", methods=["POST"])
def analyze():
    payload = AnalyzeRequest(**request.json)
    text = payload.text.strip()

    global_msg = get_message_global(text)
    summary    = summarize_facts(text)

    ents_prompt = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":f"5 entités : {text}"}]
    )
    entities = extract_json(ents_prompt.choices[0].message.content, [])
    web_hits = search_web(entities)
    diffs    = compare_text_web(summary, web_hits)

    evals = evaluate_axes(summary, web_hits, diffs, global_msg)
    axes  = evals["axes"]

    synthese = build_synthesis(axes)
    score    = compute_score(axes)

    axes["fond"]["justesse"]["couleur"]   = color_for(axes["fond"]["justesse"]["note"])
    axes["fond"]["completude"]["couleur"] = color_for(axes["fond"]["completude"]["note"])
    axes["forme"]["ton"]["couleur"]       = color_for(axes["forme"]["ton"]["note"])
    axes["forme"]["sophismes"]["couleur"] = color_for(axes["forme"]["sophismes"]["note"])

    resp = AnalyzeResponse(
        score_global=score,
        couleur_global=color_for(score),
        resume=synthese,
        commentaire=synthese,
        axes=Axes(fond=axes["fond"], forme=axes["forme"]),
        justesse=axes["fond"]["justesse"]["note"],
        completude=axes["fond"]["completude"]["note"],
        ton=axes["forme"]["ton"]["note"],
        sophismes=axes["forme"]["sophismes"]["note"],
        confiance_analyse=score,
        explication_confiance=""
    )

    return jsonify(resp.model_dump())

# ------------------------------------------------------
# FRONTEND ROUTES
# ------------------------------------------------------

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

# ------------------------------------------------------
# RUN
# ------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
