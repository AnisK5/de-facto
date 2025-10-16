import os
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # <-- Autorise toutes les origines

@app.route("/ping")
def ping():
    return "Serveur OK"

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    text = data.get("text", "")
    # Exemple JSON complet
    return jsonify({
        "score_global": 75,
        "sous_scores": {
            "fiabilite": 80,
            "rigueur_argumentative": 70,
            "coherence": 75
        },
        "commentaire": "Exemple de texte simulé",
        "resume": "Texte clair avec quelques points à améliorer"
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))  # Render fournit le port via cette variable
    app.run(host="0.0.0.0", port=port)