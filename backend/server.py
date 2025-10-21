from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, signal, json, re
from dotenv import load_dotenv

# ======================================================
# ⚙️ Feature flags — activables/désactivables sans casser
# ======================================================
ENABLE_SYNTHESIS = True       # Ajoute une synthèse narrative lisible
ENABLE_CONTEXT_BOX = True     # Ajoute un éclairage contextuel court
ENABLE_TRANSPARENCY = True    # Ajoute mentions "expérimental" et tronquage
ENABLE_URL_EXTRACT = True     # Active Trafilatura (si URL fournie)

# ======================================================
# Flask setup
# ======================================================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ======================================================
# OpenAI client
# ======================================================
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ======================================================
# Timeout (Render/Replit safety)
# ======================================================
def _timeout_handler(signum, frame):
    raise TimeoutError("Analyse trop longue (timeout Render).")
signal.signal(signal.SIGALRM, _timeout_handler)

# ======================================================
# Helpers
# ======================================================
def color_for(score: int) -> str:
    if score is None: return "⚪"
    if score >= 70: return "🟢"
    if score >= 40: return "🟡"
    return "🔴"


# ======================================================
# 🧩 Route principale : analyse
# ======================================================
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Aucun texte reçu"}), 400

    # 🔗 Extraction d’URL via Trafilatura (si activée)
    if ENABLE_URL_EXTRACT and re.match(r"^https?://", text):
        try:
            import trafilatura
            fetched = trafilatura.extract(trafilatura.fetch_url(text)) or ""
            if len(fetched.strip()) >= 300:
                text = fetched.strip()[:8000]
                print(f"✅ Trafilatura OK (len={len(text)})")
            else:
                print("⚠️ Extraction trop courte, texte brut conservé.")
        except Exception as e:
            print("⚠️ Trafilatura indisponible :", e)

    # Tronquage protecteur
    MAX_LEN = 8000
    texte_tronque = len(text) > MAX_LEN
    original_length = len(text)
    if texte_tronque:
        text = text[:MAX_LEN] + " [...] (texte tronqué pour analyse)"

    # ======================================================
    # 🧠 Prompt enrichi
    # ======================================================
    prompt = f"""
Tu es **De Facto**, un baromètre d’analyse journalistique fiable et clair.

Objectif : produire une fiche lisible, structurée et contextualisée :
1️⃣ Synthèse générale (forces/faiblesses principales)
2️⃣ Scorecard complète : FOND (justesse + complétude) / FORME (ton + sophismes)
3️⃣ Limites et transparence

Grille de notation :
- FOND (60 %) :
  • Justesse : précision factuelle, attribution claire.
  • Complétude : pluralité des points de vue, contexte manquant.
- FORME (40 %) :
  • Ton : neutralité lexicale, absence de charge émotionnelle.
  • Sophismes : erreurs logiques, généralisations.

Procédure :
- Donne un score 0–100 pour chaque sous-critère.
- Calcule le score global pondéré.
- Rédige une **synthèse_contextuelle** (3–5 phrases max) :
  style journalistique, pas scolaire ;
  résumé lisible des forces/faiblesses ;
  mentionne si des éléments clés manquent.
- Si activé, ajoute un champ **eclairage_contextuel** :
  un court paragraphe sur l’impact de ces manques sur la compréhension.
- Mentionne dans "limites_analyse_contenu" si le texte est tronqué.
- Ajoute dans "limites_analyse_ia" une note d’honnêteté :
  "Analyse expérimentale : De Facto est en amélioration continue."

Réponds STRICTEMENT en JSON avec les champs suivants :
{{
  "score_global": <int>,
  "couleur_global": "<emoji>",
  "synthese_contextuelle": "<texte court>",
  "axes": {{
    "fond": {{
      "justesse": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase>", "citation": "<<=20 mots>"}},
      "completude": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase>", "citation": "<<=20 mots>"}}
    }},
    "forme": {{
      "ton": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase>", "citation": "<<=20 mots>"}},
      "sophismes": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase>", "citation": "<<=20 mots>"}}
    }}
  }},
  "commentaire": "<phrase courte>",
  "confiance_analyse": <int>,
  "limites_analyse_ia": ["<texte>", "..."],
  "limites_analyse_contenu": ["<texte>", "..."],
  "recherches_effectuees": ["<texte>", "..."],
  "methode": {{
    "principe": "De Facto évalue un texte selon FOND (justesse, complétude) et FORME (ton, sophismes).",
    "criteres": {{
      "fond": "Justesse (véracité/sources) et complétude (pluralité/contre-arguments).",
      "forme": "Ton (neutralité) et sophismes (raisonnements fallacieux)."
    }},
    "avertissement": "Analyse basée sur le texte fourni ; pas d’accès web temps réel."
  }}
}}

Texte :
---
{text}
---
"""

    try:
        signal.alarm(30)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un analyste journalistique rigoureux, concis et clair."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.25
        )
        signal.alarm(0)

        raw = resp.choices[0].message.content.strip()

        # Parsing JSON tolérant
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return jsonify({"error": "Réponse GPT non conforme (non JSON)"}), 500
            result = json.loads(m.group(0))

        # Valeurs par défaut (non destructif)
        result.setdefault("confiance_analyse", 80)
        result.setdefault("limites_analyse_ia", [])
        result.setdefault("limites_analyse_contenu", [])
        result.setdefault("recherches_effectuees", [])
        result.setdefault("methode", {})
        if ENABLE_SYNTHESIS:
            result.setdefault("synthese_contextuelle", "")
        if ENABLE_CONTEXT_BOX:
            result.setdefault("eclairage_contextuel", "")

        # Couleurs
        if "score_global" in result:
            result["couleur_global"] = color_for(int(result["score_global"]))
        axes = result.get("axes", {})
        for bloc in ("fond", "forme"):
            for crit in (axes.get(bloc) or {}).values():
                if isinstance(crit, dict) and "note" in crit:
                    crit.setdefault("couleur", color_for(int(crit["note"])))

        # Transparence
        if ENABLE_TRANSPARENCY:
            if texte_tronque:
                result["limites_analyse_contenu"].append(
                    f"Analyse effectuée sur un extrait (max {MAX_LEN} caractères sur {original_length})."
                )
            if not any("Analyse expérimentale" in x for x in result["limites_analyse_ia"]):
                result["limites_analyse_ia"].append(
                    "Analyse expérimentale : De Facto est en amélioration continue et peut comporter des imprécisions."
                )

        return jsonify(result)

    except TimeoutError:
        return jsonify({"error": "Analyse trop longue. Réessaie avec un texte plus court."}), 500
    except Exception as e:
        print("❌ Erreur :", e)
        return jsonify({"error": str(e)}), 500


# ======================================================
# Diagnostic / version
# ======================================================
@app.route("/version")
def version():
    return jsonify({"version": "De Facto v2.1-context", "status": "✅ actif"})


# ======================================================
# Frontend (Replit uniquement)
# ======================================================
if os.getenv("REPL_ID"):
    @app.route("/")
    def serve_frontend():
        return send_from_directory(os.path.join(os.getcwd(), "frontend"), "index.html")

    @app.route("/<path:path>")
    def serve_static(path):
        frontend_path = os.path.join(os.getcwd(), "frontend")
        file_path = os.path.join(frontend_path, path)
        if os.path.exists(file_path):
            return send_from_directory(frontend_path, path)
        else:
            return send_from_directory(frontend_path, "index.html")


# ======================================================
# Run
# ======================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
