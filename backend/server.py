from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, signal, json, re

# ---------------------------
# Flask + CORS
# ---------------------------
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ---------------------------
# OpenAI client (clé en var d'env OPENAI_API_KEY)
# ---------------------------
from dotenv import load_dotenv
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------
# Timeout hard (Render) pour éviter les requêtes bloquantes
# ---------------------------
def _timeout_handler(signum, frame):
    raise TimeoutError("Analyse trop longue (timeout Render).")
signal.signal(signal.SIGALRM, _timeout_handler)

# ---------------------------
# Helpers
# ---------------------------
def color_for(score: int) -> str:
    if score is None: return "⚪"
    if score >= 70: return "🟢"
    if score >= 40: return "🟡"
    return "🔴"

# ---------------------------
# Route principale
# ---------------------------
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Aucun texte reçu"}), 400

    # Tronquage protecteur (stabilité Render)
    MAX_LEN = 8000
    texte_tronque = False
    original_length = len(text)
    if original_length > MAX_LEN:
        texte_tronque = True
        text = text[:MAX_LEN] + " [...] (texte tronqué pour analyse)"

    # Prompt principal
    prompt = f"""
Tu es De Facto, un baromètre d’analyse de fiabilité des contenus.
Objectif : produire une scorecard claire (score global + 4 sous-notes) et des détails pliables.

Grille d’évaluation :
- FOND :
  • Justesse = précision des faits, attribution claire, sources identifiables.
  • Complétude = pluralité des points de vue, contre-arguments, nuance.
- FORME :
  • Ton = neutralité lexicale, faible charge émotionnelle.
  • Sophismes = présence de raisonnements fallacieux (généralisations, appels à l’émotion, etc.).

Procédé interne pour stabiliser :
- Effectue DEUX micro-analyses indépendantes puis rends la moyenne (arrondie) des notes.
- Notes sur 100. Couleurs : 🟢 >=70 ; 🟡 40–69 ; 🔴 <40.

Recherche interne simulée :
- Identifie 1–3 éléments clés à compléter/vérifier.
- Appuie-toi sur tes connaissances internes (jusqu’en 2024/2025) pour contextualiser brièvement.
- Si non concluante, indique-le clairement.

Limites (séparées) :
- limites_analyse_ia = ce que TON analyse ne peut pas garantir (pas d’accès web temps réel, ambiguités, etc.).
- limites_analyse_contenu = limites du TEXTE (extrait, un seul point de vue, absence de sources, etc.).

Réponds STRICTEMENT en JSON (rien d’autre) au format :
{{
  "score_global": <int>,
  "couleur_global": "<emoji>",
  "axes": {{
    "fond": {{
      "justesse": {{"note": <int>, "couleur": "<emoji>", "justification": "<1 phrase>", "citation": "<<=20 mots ou null>"}},
      "completude": {{"note": <int>, "couleur": "<emoji>", "justification": "<1 phrase>", "citation": "<<=20 mots ou null>"}}
    }},
    "forme": {{
      "ton": {{"note": <int>, "couleur": "<emoji>", "justification": "<1 phrase>", "citation": "<<=20 mots ou null>"}},
      "sophismes": {{"note": <int>, "couleur": "<emoji>", "justification": "<1 phrase>", "citation": "<<=20 mots ou null>"}}
    }}
  }},
  "commentaire": "<2 phrases max : forces/faiblesses>",
  "resume": "<3 phrases max>",
  "confiance_analyse": <int>,
  "limites_analyse_ia": ["<texte>", "..."],
  "limites_analyse_contenu": ["<texte>", "..."],
  "recherches_effectuees": ["<résumé court>", "..."],
  "methode": {{
    "principe": "De Facto évalue un texte selon deux axes : FOND (justesse, complétude) et FORME (ton, sophismes).",
    "criteres": {{
      "fond": "Justesse (véracité/sources) et complétude (pluralité/contre-arguments).",
      "forme": "Ton (neutralité) et sophismes (raisonnements fallacieux)."
    }},
    "avertissement": "Analyse basée sur le texte fourni ; pas d’accès web temps réel."
  }}
}}

Texte à analyser :
---
{text}
---
"""

    try:
        signal.alarm(25)

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un analyste textuel rigoureux, concis et transparent."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        signal.alarm(0)

        raw = resp.choices[0].message.content.strip()

        # Parsing JSON tolérant
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return jsonify({"error": "Réponse GPT non conforme (non JSON)."}), 500
            result = json.loads(m.group(0))

        # Valeurs par défaut
        result.setdefault("confiance_analyse", 80)
        result.setdefault("limites_analyse_ia", [])
        result.setdefault("limites_analyse_contenu", [])
        result.setdefault("recherches_effectuees", [])
        result.setdefault("methode", {
            "principe": "De Facto évalue un texte selon FOND (justesse, complétude) et FORME (ton, sophismes).",
            "criteres": {
                "fond": "Justesse (véracité/sources) et complétude (pluralité/contre-arguments).",
                "forme": "Ton (neutralité) et sophismes (raisonnements fallacieux)."
            },
            "avertissement": "Analyse basée sur le texte fourni ; pas d’accès web temps réel."
        })

        # Couleurs
        if "score_global" in result:
            result.setdefault("couleur_global", color_for(int(result["score_global"])))
        axes = result.get("axes", {})
        for bloc in ("fond", "forme"):
            if bloc in axes and isinstance(axes[bloc], dict):
                for crit in axes[bloc].values():
                    if isinstance(crit, dict) and "note" in crit:
                        crit.setdefault("couleur", color_for(int(crit["note"])))

        # Transparence si texte tronqué
        result["texte_tronque"] = texte_tronque
        if texte_tronque:
            result["limites_analyse_contenu"].append(
                f"Analyse effectuée sur un extrait (max {MAX_LEN} caractères sur {original_length})."
            )

        return jsonify(result)

    except TimeoutError:
        return jsonify({"error": "Analyse trop longue. Réessaie avec un texte plus court."}), 500
    except Exception as e:
        print("❌ Erreur:", e)
        return jsonify({"error": str(e)}), 500


# ---------------------------
# Serve frontend only in Replit / dev mode
# ---------------------------
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


# ---------------------------
# Run app
# ---------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))



