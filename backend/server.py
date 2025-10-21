from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, signal, json, re
from dotenv import load_dotenv

# ---------------------------
# Flask + CORS
# ---------------------------
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ---------------------------
# OpenAI client (clé en var d'env OPENAI_API_KEY)
# ---------------------------
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------
# Timeout (Render)
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

    MAX_LEN = 8000
    texte_tronque = False
    original_length = len(text)
    if original_length > MAX_LEN:
        texte_tronque = True
        text = text[:MAX_LEN] + " [...] (texte tronqué pour analyse)"

    # Mode enrichi activé
    ENABLE_ENRICHED = True

    # Prompt principal enrichi
    prompt = f"""
Tu es **De Facto**, un baromètre d’analyse de fiabilité des contenus publics.

Ta mission : produire une **analyse vivante, concrète et comparative** du texte suivant.
L’objectif est d’aider à comprendre la fiabilité réelle, pas seulement à donner des notes.

---

### 🎯 Grille d’évaluation
- **FOND**
  • Justesse → Vérifie la précision factuelle, les sources implicites, les affirmations vérifiables.  
    → Donne un exemple précis du texte et, si possible, situe-le par rapport à ce qui est connu publiquement (autres médias, faits récents).  
  • Complétude → Évalue la pluralité des points de vue, la prise en compte de contre-arguments, la nuance.  
    → Identifie clairement ce qui manque.

- **FORME**
  • Ton → Analyse la neutralité lexicale, repère les signaux émotionnels ou partisans.  
    → Donne un exemple de formulation typique.  
  • Sophismes → Détecte les raisonnements fallacieux (généralisations, appels à l’émotion, causalités douteuses).  
    → Explique brièvement leur effet sur la fiabilité.

---

### 🔍 Contexte simulé
Si tu connais des faits publics (2024–2025) liés au sujet, tu peux t’y référer brièvement
(ex : “selon Le Monde, l’affaire concernait…”, ou “d’autres médias ont rapporté…”).  
Tu ne fais PAS de recherche web, tu t’appuies sur ta mémoire interne.

---

### 💡 Sortie demandée
Réponds STRICTEMENT en JSON, au format suivant :

{{
  "score_global": <int>,
  "couleur_global": "<emoji>",
  "axes": {{
    "fond": {{
      "justesse": {{
        "note": <int>, "couleur": "<emoji>",
        "justification": "<phrase précise et concrète>",
        "citation": "<<=20 mots>",
        "comparaison": "<référence à des faits connus ou contexte>"
      }},
      "completude": {{
        "note": <int>, "couleur": "<emoji>",
        "justification": "<phrase concrète sur la pluralité manquante ou présente>",
        "citation": "<<=20 mots>",
        "comparaison": "<élément contextuel ou manquant>"
      }}
    }},
    "forme": {{
      "ton": {{
        "note": <int>, "couleur": "<emoji>",
        "justification": "<phrase concrète sur le ton>",
        "citation": "<<=20 mots>"
      }},
      "sophismes": {{
        "note": <int>, "couleur": "<emoji>",
        "justification": "<phrase claire expliquant le biais>",
        "citation": "<<=20 mots>"
      }}
    }}
  }},
  "commentaire": "<2 phrases max : forces/faiblesses>",
  "resume": "<3 phrases max>",
  "confiance_analyse": <int>,
  "eclairage": {{
    "faits_complementaires": ["<faits publics connus>", "..."],
    "manques_identifies": ["<points clés absents du texte>", "..."],
    "impact_sur_fiabilite": "<phrase claire sur la conséquence des manques>"
  }},
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

---

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
                {"role": "system", "content": "Tu es un analyste textuel rigoureux, concret et pédagogue."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4
        )
        signal.alarm(0)

        raw = resp.choices[0].message.content.strip()

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return jsonify({"error": "Réponse GPT non conforme (non JSON)."}), 500
            result = json.loads(m.group(0))

        # Valeurs par défaut
        result.setdefault("confiance_analyse", 80)
        result.setdefault("eclairage", {
            "faits_complementaires": [],
            "manques_identifies": [],
            "impact_sur_fiabilite": ""
        })
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

        if texte_tronque:
            result["texte_tronque"] = True
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
# Serve frontend in dev (Replit)
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
