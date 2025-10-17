from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(
    app,
    resources={r"/analyze": {"origins": ["*"]}},  # ou restreins à weweb.app si tu préfères
    methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"]
)

@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(force=True)
    text = data.get("text", "")
    # ... ta logique existante, renvoyant déjà le JSON structuré ...
    return jsonify({
        "score_global": 0.82,
        "sous_scores": {"fiabilite": 0.8, "coherence": 0.85, "rigueur": 0.78},
        "commentaire": "OK",
        "resume": "..."
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))  # Render fournit le port via cette variable
    app.run(host="0.0.0.0", port=port)