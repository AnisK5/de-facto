# =====================================================
#  DE FACTO - BACKEND D'ANALYSE DE TEXTE
#  Version : 1.4
#  Auteur : Anis + ChatGPT
#  Mission : Évaluer la fiabilité et la rigueur argumentative d’un texte.
# =====================================================

from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from datetime import datetime
import os, json, re

# ----------------------------
# 1️⃣ INITIALISATION DU SERVEUR
# ----------------------------

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ----------------------------
# 2️⃣ PAGE D’ACCUEIL
# ----------------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Bienvenue sur l’API De Facto.",
        "routes": ["/analyze (POST)"],
        "description": "Envoyez un texte pour obtenir une analyse complète et transparente."
    })


# ----------------------------
# 3️⃣ FONCTION PRINCIPALE : /analyze
# ----------------------------
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    # Lecture du texte envoyé par le frontend
    data = request.get_json(force=True)
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "Aucun texte reçu."}), 400

    word_count = len(text.split())
    if word_count < 50:
        return jsonify({"error": "Texte trop court pour une analyse fiable (min. 50 mots)."}), 400


    # ----------------------------
    # 4️⃣ PROMPT GPT
    # ----------------------------
    prompt = f"""
    Tu es le moteur d'analyse de DE FACTO, un outil de fiabilité des textes.
    Ta mission : évaluer la rigueur argumentative d’un texte informatif selon une méthode claire et reproductible.

    🧭 DÉFINITION MÉTHODOLOGIQUE :
    - FOND :
        • Justesse : précision des faits, qualité des sources citées, cohérence interne.
        • Complétude : diversité des points de vue, mention de contre-arguments, ouverture à la nuance.
    - FORME :
        • Ton : neutralité du vocabulaire, absence de charge émotionnelle.
        • Biais : détection des sophismes, généralisations ou appels à l’émotion.

    🧱 CONSIGNES :
    - Si le texte n’est pas informatif (opinion, fiction, humour...), indique-le clairement dans "type_texte".
    - Donne une note de 0 à 1 pour chaque sous-critère.
    - Ajoute pour chacun : une courte justification, 1–3 exemples du texte ("preuves"), et un ou deux points d'amélioration ("elements_manquants").
    - Calcule un score global pondéré : 70 % fond, 30 % forme.
    - Attribue une couleur selon la grille suivante :
        🟢 ≥ 70
        🟡 40–69
        🔴 < 40
    - Indique un niveau de confiance (0 à 1) basé sur la clarté et la longueur du texte.
    - Fournis :
        - une impression générale,
        - un conseil de lecture,
        - les limites du texte,
        - les limites de ton analyse,
        - les vérifications suggérées,
        - et un résumé des critères appliqués.
    - Ajoute une section "methode" explicitant les critères d’analyse.

    📊 FORMAT JSON STRICT :
    {{
      "pertinence": "<texte>",
      "type_texte": "<informatif | opinion | fiction | autre>",
      "confiance": <float>,
      "score_global": <float>,
      "couleur": "<🟢 | 🟡 | 🔴>",
      "axes": {{
        "fond": {{
          "justesse": {{
            "note": <float>,
            "couleur": "<🟢 | 🟡 | 🔴>",
            "preuves": ["<exemple>", "..."],
            "explications": ["<texte>", "..."],
            "elements_manquants": ["<texte>", "..."]
          }},
          "completuede": {{
            "note": <float>,
            "couleur": "<🟢 | 🟡 | 🔴>",
            "preuves": ["<exemple>", "..."],
            "explications": ["<texte>", "..."],
            "elements_manquants": ["<texte>", "..."]
          }}
        }},
        "forme": {{
          "ton": {{
            "note": <float>,
            "couleur": "<🟢 | 🟡 | 🔴>",
            "preuves": ["<exemple>", "..."],
            "explications": ["<texte>", "..."]
          }},
          "biais": {{
            "note": <float>,
            "couleur": "<🟢 | 🟡 | 🔴>",
            "preuves": ["<exemple>", "..."],
            "explications": ["<texte>", "..."]
          }}
        }}
      }},
      "commentaire": "<texte>",
      "synthese": "<phrase courte>",
      "impression_generale": "<phrase courte>",
      "conseil": "<recommandation>",
      "resume_criteres": ["<phrase>", "..."],
      "verifications_suggerees": ["<élément à vérifier>", "..."],
      "limites_texte": ["<texte>", "..."],
      "limites_analyse": ["<texte>", "..."],
      "methode": {{
        "principe": "De Facto évalue la rigueur argumentative d’un texte selon deux axes : le fond et la forme.",
        "criteres": {{
          "justesse": "Vérifie la précision des faits et la présence de sources identifiables.",
          "completuede": "Mesure la diversité des points de vue et la prise en compte des contre-arguments.",
          "ton": "Analyse la neutralité du vocabulaire et la charge émotionnelle.",
          "biais": "Détecte les sophismes et généralisations abusives."
        }},
        "avertissement": "L’analyse porte sur le texte fourni, pas sur la réputation du média ou de l’auteur."
      }}
    }}

    Texte à analyser :
    ---
    {text}
    ---
    """

    # ----------------------------
    # 5️⃣ APPEL À GPT
    # ----------------------------
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es le moteur d’analyse structuré et transparent de De Facto."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        raw_output = response.choices[0].message.content.strip()

        # ----------------------------
        # 6️⃣ PARSING DU JSON
        # ----------------------------
        try:
            result = json.loads(raw_output)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            result = json.loads(match.group(0)) if match else {"error": "JSON invalide"}

        # ----------------------------
        # 7️⃣ CALCUL LOCAL + COULEURS
        # ----------------------------
        def couleur_note(note):
            if note is None: return "⚪"
            if note >= 0.7: return "🟢"
            elif note >= 0.4: return "🟡"
            else: return "🔴"

        try:
            fond = result.get("axes", {}).get("fond", {})
            forme = result.get("axes", {}).get("forme", {})

            for axe in [fond, forme]:
                for critere in axe.values():
                    note = critere.get("note", 0)
                    critere["couleur"] = couleur_note(note)

            fond_score = (fond.get("justesse", {}).get("note", 0) + fond.get("completuede", {}).get("note", 0)) / 2
            forme_score = (forme.get("ton", {}).get("note", 0) + forme.get("biais", {}).get("note", 0)) / 2
            score_global = round((fond_score * 0.7 + forme_score * 0.3) * 100, 1)
            result["score_global"] = score_global
            result["couleur"] = couleur_note(score_global / 100)
        except Exception as e:
            print("⚠️ Erreur calcul couleur :", e)

        # ----------------------------
        # 8️⃣ LOGS (sauvegarde locale)
        # ----------------------------
        try:
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "texte": text[:2000],
                "resultat": result
            }
            with open("logs.json", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print("⚠️ Erreur de log :", e)

        # ----------------------------
        # 9️⃣ RÉPONSE AU FRONT
        # ----------------------------
        return jsonify(result)

    except Exception as e:
        print("❌ Erreur GPT :", e)
        return jsonify({"error": str(e)}), 500


# =====================================================
# SYNTHÈSE DU CODE
# =====================================================
# ✅ Reçoit un texte (POST /analyze)
# ✅ Analyse fond / forme / justesse / complétude / ton / biais
# ✅ Fournit : commentaires, conseils, limites, méthode, suggestions
# ✅ Calcule localement les couleurs et le score global (70/30)
# ✅ Sauvegarde les résultats dans logs.json
# ✅ Renvoie un JSON clair, complet et UX-friendly
# =====================================================
