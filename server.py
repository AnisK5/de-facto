from flask import Flask, request, jsonify

app = Flask(__name__)


# ----------------------------
# Endpoint de test GET
# ----------------------------
@app.route("/ping")
def ping():
    return "Serveur OK"


# ----------------------------
# Endpoint principal POST
# ----------------------------

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    text = data.get("text", "")

    # Ici on simule juste un score pour tester Bubble
    score = 75  # par exemple, score sur 100
    return jsonify({"score": score})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
