from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os
import signal
import json
import re

# --- Initialisation de Flask ---
app = Flask(__name__)

# Autoriser toutes les origines (utile pour tests locaux et production)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# --- Initialisation du client OpenAI ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- Protection : Timeout automatique ---
def handler(signum, frame):
    raise TimeoutError("Analyse trop longue (timeout Render).")

signal.signal(signal.SIGALRM, handler)


# --- Route d’accueil pour tests rapides ---
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Bienvenue sur l’API De Facto v1.5.2 (stable + cohérente)",
        "routes": ["/analyze (POST)"],
        "hint": "POST { text: '<texte ou url>' }"
    })


# --- Route principale : /analyze ---
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    # --- Récupération du texte envoyé ---
    data = request.get_json(force=True)
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "Aucun texte reçu"}), 400

    # --- Protection : tronquer les textes trop longs ---
    if len(text) > 4000:
        text = text[:4000] + " [...] (texte tronqué pour analyse)"

    # --- Prompt optimisé : cohérent, stable, et explicatif ---
    prompt = f"""
    Tu es De Facto, un baromètre de fiabilité qui évalue la rigueur et la crédibilité d’un texte informatif.

    ⚙️ Méthode :
    - Fais **deux analyses internes indépendantes** du texte.
    - Compare-les et donne **une moyenne arrondie des scores**.
    - Indique aussi un **score de confiance** (0 à 100) représentant ta certitude sur ton évaluation.
    - Si certaines informations manquent, fais une recherche interne dans tes connaissances.
    - Mentionne clairement les **limites** de ton analyse (incomplétude du texte, ambiguïtés, etc.)

    Donne ta réponse STRICTEMENT en JSON au format :
    {{
      "score_global": <int>,
      "sous_scores": {{
        "fiabilite": <int>,
        "coherence": <int>,
        "rigueur": <int>
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
        # Timeout : 25 secondes maximum
        signal.alarm(25)

        # --- Appel à GPT ---
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # modèle rapide, stable et peu coûteux
            messages=[
                {"role": "system", "content": "Tu es un assistant d’analyse de texte rigoureux et méthodique."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3  # stabilité accrue
        )

        signal.alarm(0)  # stoppe le timer une fois terminé

        # --- Récupération du contenu GPT ---
        gpt_content = response.choices[0].message.content.strip()

        # --- Parsing JSON avec tolérance ---
        try:
            result = json.loads(gpt_content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", gpt_content, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
            else:
                print("⚠️ Réponse GPT non JSON:", gpt_content[:300])
                return jsonify({"error": "Réponse GPT non conforme"}), 500

        # --- Valeurs par défaut si certains champs manquent ---
        result.setdefault("confiance_analyse", 80)
        result.setdefault("limites_analyse", ["Non précisées."])

        # --- Envoi au frontend ---
        return jsonify(result)

    except TimeoutError as e:
        print("⏱️ Timeout Render:", e)
        return jsonify({"error": "Analyse trop longue. Essaie avec un texte plus court."}), 500

    except Exception as e:
        print("❌ Erreur GPT:", e)
        return jsonify({"error": f"Erreur interne : {str(e)}"}), 500


# --- Lancement local ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
