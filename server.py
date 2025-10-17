from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os
import signal
import json
import re

# --- Initialisation du serveur Flask ---
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# --- Initialisation du client OpenAI ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- Fonction de sécurité : timeout ---
def handler(signum, frame):
    raise TimeoutError("Analyse trop longue (timeout Render).")

signal.signal(signal.SIGALRM, handler)

# --- Route d'accueil (diagnostic simple) ---
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Bienvenue sur l’API De Facto v1.6 (stable + détaillée)",
        "routes": ["/analyze (POST)"],
        "hint": "POST { text: '<texte ou url>' }"
    })

# --- Route principale ---
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(force=True)
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "Aucun texte reçu"}), 400

    # --- Limite de texte pour éviter les crash Render ---
    if len(text) > 4000:
        text = text[:4000] + " [...] (texte tronqué pour analyse)"

    # --- Prompt enrichi, mais compact ---
    prompt = f"""
    Tu es De Facto, un baromètre de fiabilité qui évalue la rigueur et la crédibilité d’un texte informatif.

    ⚙️ Méthode :
    1. Fais deux analyses internes indépendantes du texte.
    2. Calcule la moyenne des scores obtenus pour plus de stabilité.
    3. Pour chaque critère (fiabilité, cohérence, rigueur) :
       - Donne une note sur 100.
       - Fournis une courte justification (1 phrase).
       - Si possible, cite un extrait représentatif du texte (max 20 mots).
       - Attribue une couleur indicative : 🟢 si >=70, 🟡 si 40–69, 🔴 si <40.
    4. Ajoute un score global sur 100 et sa couleur correspondante.
    5. Donne un résumé du texte et un commentaire global (2 phrases max).
    6. Estime un score de confiance (0–100) indiquant ta certitude.
    7. Termine par une liste des limites de ton analyse.

    Réponds STRICTEMENT en JSON au format suivant :
    {{
      "score_global": <int>,
      "couleur_global": "<emoji>",
      "sous_scores": {{
        "fiabilite": {{
          "note": <int>,
          "couleur": "<emoji>",
          "justification": "<texte>",
          "citation": "<texte ou null>"
        }},
        "coherence": {{
          "note": <int>,
          "couleur": "<emoji>",
          "justification": "<texte>",
          "citation": "<texte ou null>"
        }},
        "rigueur": {{
          "note": <int>,
          "couleur": "<emoji>",
          "justification": "<texte>",
          "citation": "<texte ou null>"
        }}
      }},
      "commentaire": "<texte>",
      "resume": "<texte>",
      "confiance_analyse": <int>,
      "limites_analyse": ["<texte>", "<texte>"]
    }}

    Texte à analyser :
    ---
    {text}
    ---
    """

    try:
        # Timeout de 25 secondes max
        signal.alarm(25)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un assistant d’analyse de texte rigoureux et fiable."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        signal.alarm(0)

        gpt_content = response.choices[0].message.content.strip()

        # Parsing JSON tolérant
        try:
            result = json.loads(gpt_content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", gpt_content, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
            else:
                print("⚠️ Réponse non JSON:", gpt_content[:300])
                return jsonify({"error": "Réponse GPT non conforme."}), 500

        # Valeurs par défaut
        result.setdefault("confiance_analyse", 80)
        result.setdefault("limites_analyse", ["Non précisées."])

        # Si GPT oublie les couleurs, on les régénère côté Python
        def color_for(value):
            if value >= 70: return "🟢"
            if value >= 40: return "🟡"
            return "🔴"

        if "sous_scores" in result:
            for key, val in result["sous_scores"].items():
                if isinstance(val, dict) and "note" in val:
                    val.setdefault("couleur", color_for(val["note"]))

        if "score_global" in result:
            result.setdefault("couleur_global", color_for(result["score_global"]))

        return jsonify(result)

    except TimeoutError:
        return jsonify({"error": "Analyse trop longue. Réessaie avec un texte plus court."}), 500

    except Exception as e:
        print("❌ Erreur GPT:", e)
        return jsonify({"error": str(e)}), 500

# --- Lancement local ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
