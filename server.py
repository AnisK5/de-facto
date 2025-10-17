from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os, json, re

# --- Initialisation ---
app = Flask(__name__)
CORS(app)

# --- Client OpenAI ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- Route d'accueil (optionnelle, pour tester depuis le navigateur) ---
@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Bienvenue sur l’API du Baromètre de Fiabilité (Facto). Utilisez /analyze pour POSTER votre texte."})

# --- Route principale ---
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(force=True)
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "Aucun texte reçu"}), 400

    # --- Prompt Facto (amélioré) ---
    prompt = f"""
    Tu es le moteur d'analyse du Baromètre de Fiabilité (Facto).
    Ta mission est d'évaluer la rigueur argumentative et la fiabilité d’un texte.
    Réponds uniquement en JSON strict, sans texte autour.

    Analyse le texte suivant selon cette grille :
    - Le FOND : 
      • Justesse (qualité des sources, solidité du raisonnement, cohérence des faits)
      • Complétude (prise en compte de plusieurs points de vue, nuance, contre-arguments)
    - La FORME : 
      • Ton (neutralité, charge émotionnelle)
      • Biais (raisonnements fallacieux, appels à l’émotion, généralisations abusives)

    Calcule un score global sur 100 et attribue une couleur :
      🟢 si score ≥ 70
      🟡 si 40 ≤ score < 70
      🔴 si score < 40

    Donne ta réponse sous le format JSON strict suivant :
    {{
      "score_global": <float entre 0 et 100>,
      "axes": {{
        "fond": {{
          "justesse": <float>,
          "completuede": <float>
        }},
        "forme": {{
          "ton": <float>,
          "biais": <float>
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
        # --- Appel GPT ---
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un moteur d’analyse rigoureuse de textes pour Facto. Réponds toujours en JSON strict."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        raw_output = response.choices[0].message.content.strip()

        # --- Parsing robuste du JSON ---
        try:
            result = json.loads(raw_output)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group(0))
                except json.JSONDecodeError:
                    result = None
            else:
                result = None

        # --- Si rien de valide, on renvoie un format par défaut ---
        if not result:
            result = {
                "score_global": None,
                "axes": {
                    "fond": {"justesse": None, "completuede": None},
                    "forme": {"ton": None, "biais": None}
                },
                "commentaire": "Erreur : réponse du modèle non exploitable.",
                "synthese": "Analyse impossible à interpréter.",
                "couleur": "⚪"
            }

        return jsonify(result)

    except Exception as e:
        print("Erreur GPT:", e)
        return jsonify({"error": str(e)}), 500
