# =====================================================
#  DE FACTO - BACKEND D'ANALYSE DE TEXTE
#  Version : 1.5
#  Mission : Analyser la rigueur (Fond/Forme), stabiliser les notes,
#            simuler une "recherche interne", et accepter des URLs.
# =====================================================

from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from datetime import datetime
import os, json, re, time

# --- Pour l'extraction de texte depuis une URL ---
import requests
from bs4 import BeautifulSoup

# ----------------------------
# 1) CONFIGURATION FLASK + OPENAI
# ----------------------------
app = Flask(__name__)
CORS(app)  # autorise les appels depuis ton front (HTML/WeWeb/…)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))  # clé lue depuis les variables d'env (Render)

# ----------------------------
# 2) OUTILS : extraction de texte si l’utilisateur colle un lien
# ----------------------------
def is_url(candidate: str) -> bool:
    """Détecte rapidement si l’entrée ressemble à une URL."""
    return candidate.startswith("http://") or candidate.startswith("https://")

def extract_text_from_url(url: str, max_paragraphs: int = 40) -> tuple[str, dict]:
    """
    Télécharge la page et extrait un texte lisible (paragraphe <p>).
    Retourne (texte, meta_source)
    - meta_source = {"type": "url", "valeur": url, "ok": bool, "details": "..."}
    """
    meta = {"type": "url", "valeur": url, "ok": False, "details": ""}
    try:
        # User-Agent simple pour réduire les blocages
        r = requests.get(url, timeout=10, headers={"User-Agent": "DeFactoBot/1.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        paragraphs = [p.get_text(separator=" ", strip=True) for p in soup.find_all("p")]
        # Concatène les n premiers paragraphes (évite les pages très longues)
        text = "\n\n".join([p for p in paragraphs if p][:max_paragraphs]).strip()
        meta["ok"] = True
        meta["details"] = f"{len(paragraphs)} paragraphes bruts, {min(len(paragraphs), max_paragraphs)} gardés."
        return text, meta
    except Exception as e:
        meta["details"] = f"Erreur d'extraction: {e}"
        return "", meta

# ----------------------------
# 3) OUTILS : couleur à partir d’une note (0..1)
# ----------------------------
def couleur_note(note: float) -> str:
    """Mappe une note [0..1] vers un emoji couleur UX."""
    if note is None:
        return "⚪"
    if note >= 0.7:
        return "🟢"
    if note >= 0.4:
        return "🟡"
    return "🔴"

# ----------------------------
# 4) PAGE D’ACCUEIL
# ----------------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Bienvenue sur l’API De Facto v1.5",
        "routes": ["/analyze (POST)"],
        "hint": "POST { text: '<texte ou url>', stabiliser?: bool, iterations?: int }"
    })

# ----------------------------
# 5) COEUR : /analyze
# ----------------------------
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    # Réponse CORS preflight
    if request.method == "OPTIONS":
        return ("", 204)

    # --- Lecture de l'entrée ---
    payload = request.get_json(force=True)
    # text_or_url peut être soit un texte, soit une URL (ex: https://...)
    text_or_url = (payload.get("text") or "").strip()
    if not text_or_url:
        return jsonify({"error": "Aucun texte ni URL fourni."}), 400

    # Stabilisation (multi-échantillons) : activable à la demande
    stabiliser: bool = bool(payload.get("stabiliser", True))  # on active par défaut pour MVP stable
    iterations: int = int(payload.get("iterations", 2))       # 2 à 3 suffisent en général

    # --- Si c'est une URL, on extrait le texte ---
    source = {"type": "texte", "valeur": None, "ok": True, "details": ""}
    if is_url(text_or_url):
        extracted, meta = extract_text_from_url(text_or_url)
        if not extracted:
            return jsonify({"error": "Impossible d'extraire le texte de l'URL.", "source": meta}), 400
        text = extracted
        source = meta
    else:
        text = text_or_url
        source["valeur"] = f"{len(text.split())} mots"

    # --- Garde-fous longueur ---
    word_count = len(text.split())
    if word_count < 50:
        return jsonify({"error": "Texte trop court pour une analyse fiable (min. 50 mots).", "source": source}), 400
    if word_count > 8000:
        # évite les prompts géants / dépassement token
        text = " ".join(text.split()[:8000])
        source["details"] += " | Texte tronqué à 8000 mots."

    # ----------------------------
    # PROMPT : consignes claires + "recherche interne" simulée
    # ----------------------------
    prompt = f"""
Tu es le moteur d'analyse de DE FACTO.
Objectif : évaluer la rigueur argumentative d’un texte à visée informative selon deux axes (Fond/Forme).

MÉTHODE :
- FOND :
  • Justesse = précision des faits, sources identifiables, cohérence interne.
  • Complétude = diversité des points de vue, mention de limites/contre-arguments, nuances.
- FORME :
  • Ton = neutralité du vocabulaire, faible charge émotionnelle.
  • Biais = sophismes, généralisations abusives, appels à l’émotion.

POUR CHAQUE SOUS-CRITÈRE (justesse, complétude, ton, biais), fournis :
- "note" (0..1),
- "preuves" : 1–3 extraits factuels du texte,
- "explications" : brève justification,
- "elements_manquants" : ce qui affaiblit l’argumentation.

AJOUTS DEMANDÉS :
- Calcule un score global pondéré (70% Fond : moyenne justesse+complétude ; 30% Forme : moyenne ton+biais) → sur 100.
- Ajoute les couleurs (🟢 ≥70 ; 🟡 40–69 ; 🔴 <40) pour chaque sous-note et pour le score global.
- "type_texte" (informatif / opinion / fiction / autre).
- "confiance" (0..1) en ta propre analyse.
- "impression_generale" (phrase courte).
- "commentaire" (2 phrases forces/faiblesses).
- "synthese" (phrase très courte).
- "resume_criteres" : 3–6 puces qui résument ce qui a été observé.
- "verifications_suggerees" : 1–4 propositions concrètes à vérifier.
- **Séparer** les limites :
  • "limites_texte" = limites du contenu (extrait, un seul point de vue, etc.)
  • "limites_analyse" = limites de ton analyse (ambiguïtés, ironie possible, absence d'accès web, etc.)

RECHERCHE INTERNE SIMULÉE :
- Pour chaque "elements_manquants" important, tente une courte "recherche interne" basée sur tes connaissances jusqu'en 2024/2025.
- Rends un objet "recherche_effectuee" :
  {{
    "points_recherches": ["<point>", "..."],
    "resultats": ["<résumé trouvé>", "..."],
    "limites": ["<pourquoi c'est incertain>", "..."]
  }}
- Si tu ne peux rien ajouter de fiable, écris explicitement : "non vérifiable à partir de mes données".

FORMAT JSON STRICT (réponds uniquement par ce JSON) :
{{
  "pertinence": "<texte>",
  "type_texte": "<informatif | opinion | fiction | autre>",
  "confiance": <float>,
  "score_global": <float>,
  "couleur": "<🟢 | 🟡 | 🔴>",
  "axes": {{
    "fond": {{
      "justesse": {{
        "note": <float>, "couleur": "<🟢|🟡|🔴>",
        "preuves": ["<extrait>", "..."],
        "explications": ["<texte>", "..."],
        "elements_manquants": ["<texte>", "..."]
      }},
      "completuede": {{
        "note": <float>, "couleur": "<🟢|🟡|🔴>",
        "preuves": ["<extrait>", "..."],
        "explications": ["<texte>", "..."],
        "elements_manquants": ["<texte>", "..."]
      }}
    }},
    "forme": {{
      "ton": {{
        "note": <float>, "couleur": "<🟢|🟡|🔴>",
        "preuves": ["<extrait>", "..."],
        "explications": ["<texte>", "..."]
      }},
      "biais": {{
        "note": <float>, "couleur": "<🟢|🟡|🔴>",
        "preuves": ["<extrait>", "..."],
        "explications": ["<texte>", "..."]
      }}
    }}
  }},
  "commentaire": "<texte>",
  "synthese": "<phrase courte>",
  "impression_generale": "<phrase courte>",
  "resume_criteres": ["<puce>", "..."],
  "verifications_suggerees": ["<élément>", "..."],
  "limites_texte": ["<texte>", "..."],
  "limites_analyse": ["<texte>", "..."],
  "recherche_effectuee": {{
    "points_recherches": ["<point>", "..."],
    "resultats": ["<résumé>", "..."],
    "limites": ["<limite>", "..."]
  }},
  "methode": {{
    "principe": "De Facto évalue la rigueur argumentative d’un texte selon deux axes : le fond (justesse, complétude) et la forme (ton, biais).",
    "criteres": {{
      "justesse": "Présence de faits précis, sources identifiables, cohérence.",
      "completuede": "Pluralité de points de vue, contre-arguments, nuance.",
      "ton": "Neutralité lexicale, faible charge émotionnelle.",
      "biais": "Absence de sophismes, de généralisations abusives."
    }},
    "avertissement": "Analyse limitée au texte fourni ; pas de navigation web en temps réel."
  }}
}}

TEXTE À ANALYSER :
---
{text}
---
"""

    # ----------------------------
    # APPEL GPT : 1 ou plusieurs itérations pour stabiliser
    # ----------------------------
    def call_gpt_once() -> dict:
        """Envoie le prompt et parse la réponse JSON (avec récupération de JSON encapsulé)."""
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es le moteur d'analyse rigoureux et transparent de De Facto. Réponds uniquement en JSON strict."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1  # ⚠️ très bas pour maximiser la stabilité
        )
        raw = resp.choices[0].message.content.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return {"error": "Réponse non-JSON"}
            return json.loads(m.group(0))

    # Appels multiples si stabilisation activée
    results = []
    n_calls = max(1, min(iterations if stabiliser else 1, 5))  # borne haute de sécurité
    for i in range(n_calls):
        one = call_gpt_once()
        results.append(one)
        # petite pause pour éviter d'éventuels artefacts côté modèle
        if i + 1 < n_calls:
            time.sleep(0.2)

    # ----------------------------
    # AGRÉGATION : moyenne des sous-notes (si plusieurs itérations)
    # ----------------------------
    base = results[0] if results else {"error": "Aucune réponse du modèle."}

    def get_note(d, path):
        """Récupère une note float dans un dict via un petit chemin."""
        try:
            for k in path:
                d = d[k]
            return float(d)
        except Exception:
            return None

    # Chemins vers les 4 sous-notes
    paths = {
        "fond.justesse": ["axes", "fond", "justesse", "note"],
        "fond.completuede": ["axes", "fond", "completuede", "note"],
        "forme.ton": ["axes", "forme", "ton", "note"],
        "forme.biais": ["axes", "forme", "biais", "note"],
    }

    # Calcule les moyennes si plusieurs réponses
    if len(results) > 1 and "error" not in base:
        # Moyenne pour chaque sous-note
        for label, path in paths.items():
            vals = [get_note(r, path) for r in results]
            vals = [v for v in vals if isinstance(v, (int, float))]
            avg = sum(vals) / len(vals) if vals else None
            # Injecte la moyenne dans la base
            axe, crit = label.split(".")
            if "axes" in base and axe in base["axes"] and crit in base["axes"][axe]:
                base["axes"][axe][crit]["note"] = avg

        # Recalcule couleurs des sous-notes
        try:
            for axe_key in ["fond", "forme"]:
                for crit_key in base["axes"][axe_key]:
                    note = base["axes"][axe_key][crit_key].get("note")
                    base["axes"][axe_key][crit_key]["couleur"] = couleur_note(note)
        except Exception:
            pass

        # Recalcule le score global pondéré (local, côté serveur)
        try:
            f_j = base["axes"]["fond"]["justesse"]["note"] or 0
            f_c = base["axes"]["fond"]["completuede"]["note"] or 0
            fo_t = base["axes"]["forme"]["ton"]["note"] or 0
            fo_b = base["axes"]["forme"]["biais"]["note"] or 0
            fond_score = (f_j + f_c) / 2
            forme_score = (fo_t + fo_b) / 2
            score_global = round((fond_score * 0.7 + forme_score * 0.3) * 100, 1)
            base["score_global"] = score_global
            base["couleur"] = couleur_note(score_global / 100)
        except Exception:
            pass

    # Ajoute un bloc "stabilisation" + "source" à la réponse finale
    if "error" not in base:
        base["stabilisation"] = {
            "mode": "moyenne_multi" if n_calls > 1 else "single",
            "iterations": n_calls
        }
        base["source"] = source

    # ----------------------------
    # LOGS : sauvegarde simple (append line JSON)
    # ----------------------------
    try:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": source,
            "word_count": word_count,
            "resultat": base
        }
        with open("logs.json", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print("⚠️ Erreur de log :", e)

    # ----------------------------
    # REPONSE
    # ----------------------------
    return jsonify(base)
