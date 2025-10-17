from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os, signal, json, re

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---- Timeout Render (évite les requêtes bloquantes) ----
def _timeout_handler(signum, frame):
    raise TimeoutError("Analyse trop longue (timeout Render).")
signal.signal(signal.SIGALRM, _timeout_handler)

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "De Facto v1.7 (scorecard + détails pliables + méthode)",
        "routes": ["/analyze (POST)"],
        "hint": "POST { text: '<texte ou url>' }"
    })

@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Aucun texte reçu"}), 400

    # ---- Limiter la longueur pour rester stable sur Render ----
    MAX_LEN = 8000  # ≈ 1300 mots
    texte_tronque = False
    if len(text) > MAX_LEN:
        texte_tronque = True
        original_length = len(text)
        text = text[:MAX_LEN] + " [...] (texte tronqué pour analyse)"

    # ---- Prompt : scores + détails + MÉTHODE ----
    prompt = f"""
Tu es De Facto, un baromètre d’analyse de fiabilité des contenus (articles, posts).
Objectif : produire une évaluation concise (scorecard) ET une fiche détaillée pliable.

Méthode (à expliquer dans la sortie):
- FOND : Fiabilité (précision des faits, sources identifiables), Cohérence (logique, chronologie, non-contradiction).
- FORME : Rigueur (structure argumentative, mention des limites/contre-arguments).
- Les scores sont sur 100. Couleurs: 🟢 ≥70 ; 🟡 40–69 ; 🔴 <40.

Procédé interne:
- Fais DEUX analyses internes et renvoie la moyenne (pour stabiliser).
- Si le texte semble partiel, ajuste le niveau de confiance.

Réponds STRICTEMENT en JSON au format suivant (ne renvoie rien d’autre) :
{{
  "score_global": <int>,
  "couleur_global": "<emoji>",
  "sous_scores": {{
    "fiabilite": {{
      "note": <int>,
      "couleur": "<emoji>",
      "justification": "<1 phrase>",
      "citation": "<extrait (max 20 mots) ou null>"
    }},
    "coherence": {{
      "note": <int>,
      "couleur": "<emoji>",
      "justification": "<1 phrase>",
      "citation": "<extrait (max 20 mots) ou null>"
    }},
    "rigueur": {{
      "note": <int>,
      "couleur": "<emoji>",
      "justification": "<1 phrase>",
      "citation": "<extrait (max 20 mots) ou null>"
    }}
  }},
  "commentaire": "<2 phrases max : forces / faiblesses>",
  "resume": "<3 phrases max>",
  "confiance_analyse": <int>,
  "limites_analyse": ["<texte>", "..."],
  "verifications_suggerees": ["<élément à vérifier>", "..."],
  "methode": {{
    "principe": "De Facto évalue la rigueur argumentative d’un texte selon FOND (fiabilité, cohérence) et FORME (rigueur).",
    "criteres": {{
      "fiabilite": "Précision factuelle, attribution claire, présence/qualité des sources.",
      "coherence": "Structure logique, chronologie claire, absence de contradictions.",
      "rigueur": "Argumentation structurée, prise en compte des limites/contre-arguments, nuance."
    }},
    "avertissement": "Analyse du texte fourni uniquement ; pas de navigation web en temps réel."
  }}
}}

Texte à analyser :
---
{text}
---
"""

    try:
        signal.alarm(25)  # garde-fou Render

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un assistant d’analyse textuelle rigoureux, concis et transparent."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        signal.alarm(0)

        raw = resp.choices[0].message.content.strip()

        # ---- Parsing JSON tolérant ----
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return jsonify({"error": "Réponse GPT non conforme (non JSON)."}), 500
            result = json.loads(m.group(0))

        # ---- Valeurs par défaut + couleurs si manquantes ----
        def color_for(v: int) -> str:
            if v is None: return "⚪"
            if v >= 70: return "🟢"
            if v >= 40: return "🟡"
            return "🔴"

        result.setdefault("confiance_analyse", 80)
        result.setdefault("limites_analyse", [])
        result.setdefault("verifications_suggerees", [])
        result.setdefault("methode", {
            "principe": "De Facto évalue la rigueur argumentative (FOND/FORME).",
            "criteres": {
                "fiabilite": "Précision des faits, attribution claire, sources.",
                "coherence": "Logique, chronologie, non-contradiction.",
                "rigueur": "Structure argumentative, limites/contre-arguments."
            },
            "avertissement": "Analyse limitée au texte fourni."
        })

        # Couleurs par défaut si oubliées
        if "sous_scores" in result:
            for k, v in result["sous_scores"].items():
                if isinstance(v, dict) and "note" in v:
                    v.setdefault("couleur", color_for(v["note"]))
        if "score_global" in result:
            result.setdefault("couleur_global", color_for(result["score_global"]))

        # Transparence si tronqué
        result["texte_tronque"] = texte_tronque
        if texte_tronque:
            result["limites_analyse"].append(
                f"Analyse effectuée sur un extrait (max 8 000 caractères). Les résultats peuvent être partiels."
            )

        return jsonify(result)

    except TimeoutError:
        return jsonify({"error": "Analyse trop longue. Réessaie avec un texte plus court."}), 500
    except Exception as e:
        print("❌ Erreur:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
