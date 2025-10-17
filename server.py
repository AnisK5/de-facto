from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os

# --- Initialisation ---
app = Flask(__name__)
CORS(app)

# --- Client OpenAI ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- Route principale ---
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(force=True)
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "Aucun texte reçu"}), 400

    # --- Appel à GPT ---
    prompt = f"""
    Tu es un outil d’analyse de texte.
    Analyse le texte suivant selon ces critères :
    - Score global (entre 0 et 1)
    - Fiabilité (entre 0 et 1)
    - Cohérence (entre 0 et 1)
    - Rigueur argumentative (entre 0 et 1)
    - Un commentaire global (2 phrases)
    - Un résumé du texte

    Donne ta réponse au format JSON strict :
    {{
      "score_global": <float>,
      "sous_scores": {{
        "fiabilite": <float>,
        "coherence": <float>,
        "rigueur": <float>
      }},
      "commentaire": "<texte>",
      "resume": "<texte>"
    }}

    Voici le texte :
    ---
    {text}
    ---
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # modèle rapide et peu coûteux
            messages=[
                {"role": "system", "content": "Tu es un assistant d'analyse de texte structuré."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4
        )

        # --- Récupérer le JSON renvoyé par GPT ---
        gpt_content = response.choices[0].message.content

        # ⚠️ GPT renvoie du texte (pas toujours JSON strict) → on essaie de parser
        import json
        result = json.loads(gpt_content)

        return jsonify(result)

    except Exception as e:
        print("Erreur GPT:", e)
        return jsonify({"error": str(e)}), 500
