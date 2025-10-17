from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os, json, re

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Bienvenue sur l’API du Baromètre de Fiabilité (Facto). Utilisez /analyze pour POSTER votre texte."})

@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(force=True)
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Aucun texte reçu"}), 400

    # --- PROMPT FACTO COMPLET ---
    prompt = f"""
    Tu es le moteur d'analyse du Baromètre de Fiabilité (Facto).
    Ta mission est d'évaluer la rigueur argumentative et la fiabilité d’un texte à visée informative.

    ⚠️ Si le texte n’est pas informatif (opinion, fiction, satire, etc.),
    indique-le dans "pertinence" et explique pourquoi aucune analyse n’est possible.
    Sinon, procède à l’analyse complète.

    Réponds uniquement en JSON strict, sans texte autour.

    Grille d'analyse :
    - FOND :
      • Justesse : qualité des sources, solidité du raisonnement, cohérence des faits
      • Complétude : pluralité des points de vue, nuance, contre-arguments
    - FORME :
      • Ton : neutralité, charge émotionnelle
      • Biais : sophismes, généralisations, appel à l’émotion

    Pour chaque sous-critère, fournis :
    - une note entre 0 et 1
    - une justification
    - un exemple concret tiré du texte

    Calcule un score global sur 100 et attribue une couleur :
      🟢 si score ≥ 70
      🟡 si 40 ≤ score < 70
      🔴 si score < 40

    Format JSON attendu :
    {{
      "pertinence": "<texte>",
      "score_global": <float entre 0 et 100>,
      "axes": {{
        "fond": {{
          "justesse": {{
            "note": <float>,
            "justification": "<texte>",
            "exemple": "<exemple tiré du texte>"
          }},
          "completuede": {{
            "note": <float>,
            "justification": "<texte>",
            "exemple": "<exemple tiré du texte>"
          }}
        }},
        "forme": {{
          "ton": {{
            "note": <float>,
            "justification": "<texte>",
            "exemple": "<exemple tiré du texte>"
          }},
          "biais": {{
            "note": <float>,
            "justification": "<texte>",
            "exemple": "<exemple tiré du texte>"
          }}
        }}
      }},
      "commentaire": "<2 phrases expliquant les points forts et faibles>",
      "synthese": "<phrase-synthèse courte>",
      "couleur": "<🟢 ou 🟡 ou 🔴>"
    }}

    Texte à analyser :
    ---
    {text}
    ---
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un moteur d’analyse rigoureuse pour Facto. Réponds toujours en JSON strict."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        raw_output = response.choices[0].message.content.strip()

        # --- Parsing robuste ---
        try:
            result = json.loads(raw_output)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            result = json.loads(match.group(0)) if match else None

        if not result:
            result = {"error": "Réponse non exploitable"}

        return jsonify(result)

    except Exception as e:
        print("Erreur GPT:", e)
        return jsonify({"error": str(e)}), 500
