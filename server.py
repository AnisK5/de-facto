# ============================
#  FACTO - BACKEND D'ANALYSE DE TEXTE
#  Version : 1.2 (avec pondération, preuves, limites, logs)
#  Auteur : Anis + ChatGPT
# ============================

from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from datetime import datetime
import os, json, re

# ----------------------------
# 1️⃣  CONFIGURATION DU SERVEUR
# ----------------------------

# Création de l’application Flask
app = Flask(__name__)

# Autoriser les requêtes cross-origin (depuis ton front HTML ou WeWeb)
CORS(app)

# Initialisation du client OpenAI avec la clé d’API (stockée sur Render)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ----------------------------
# 2️⃣  PAGE D’ACCUEIL
# ----------------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Bienvenue sur l’API du Baromètre de Fiabilité (Facto).",
        "routes": ["/analyze (POST)"],
        "description": "Envoyez un texte pour obtenir une analyse complète (fond, forme, preuves, limites, etc.)."
    })

# ----------------------------
# 3️⃣  FONCTION PRINCIPALE D’ANALYSE
# ----------------------------
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    # Réponse automatique pour les requêtes CORS (pré-vol)
    if request.method == "OPTIONS":
        return ("", 204)

    # Récupération du texte envoyé par le front
    data = request.get_json(force=True)
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "Aucun texte reçu."}), 400

    # Vérification simple de la longueur du texte
    word_count = len(text.split())
    if word_count < 50:
        return jsonify({
            "error": "Texte trop court pour une analyse fiable (min. 50 mots).",
            "word_count": word_count
        }), 400

    # ----------------------------
    # 4️⃣  PROMPT D’ANALYSE GPT
    # ----------------------------
    prompt = f"""
    Tu es le moteur d'analyse du Baromètre de Fiabilité (Facto).
    Ta mission est d'évaluer la rigueur argumentative et la fiabilité d’un texte à visée informative.

    ⚠️ Si le texte n’est pas informatif (opinion, fiction, satire, etc.), indique-le clairement.

    Analyse selon 4 sous-critères :
    - **FOND** :
        • Justesse : qualité des sources, cohérence des faits.
        • Complétude : diversité des points de vue, nuance, contre-arguments.
    - **FORME** :
        • Ton : neutralité, charge émotionnelle.
        • Biais : sophismes, généralisations, appel à l’émotion.

    Pour chaque sous-critère, fournis :
    - une note entre 0 et 1,
    - des preuves citées (éléments factuels du texte),
    - des explications (interprétation, contexte),
    - les éléments manquants (ce qui affaiblit le raisonnement).

    Ensuite :
    - Calcule un score global sur 100 (pondération : 70 % fond, 30 % forme).
    - Donne une couleur indicative (🟢 ≥70, 🟡 40–69, 🔴 <40).
    - Indique un niveau de confiance (0 à 1).
    - Indique le type de texte (informatif, opinion, fiction, etc.).
    - Mentionne les limites de l’analyse (texte incomplet, ambiguïté, manque de contexte...).
    - Fournis une impression générale et un conseil de lecture.

    Réponds **uniquement en JSON strict**, sans texte autour.

    Format attendu :
    {{
      "pertinence": "<texte>",
      "type_texte": "<informatif | opinion | fiction | autre>",
      "confiance": <float>,
      "score_global": <float>,
      "axes": {{
        "fond": {{
          "justesse": {{
            "note": <float>,
            "preuves": ["<exemple>", "..."],
            "explications": ["<texte>", "..."],
            "elements_manquants": ["<texte>", "..."]
          }},
          "completuede": {{
            "note": <float>,
            "preuves": ["<exemple>", "..."],
            "explications": ["<texte>", "..."],
            "elements_manquants": ["<texte>", "..."]
          }}
        }},
        "forme": {{
          "ton": {{
            "note": <float>,
            "preuves": ["<exemple>", "..."],
            "explications": ["<texte>", "..."]
          }},
          "biais": {{
            "note": <float>,
            "preuves": ["<exemple>", "..."],
            "explications": ["<texte>", "..."]
          }}
        }}
      }},
      "commentaire": "<2 phrases sur les forces et faiblesses>",
      "synthese": "<phrase courte de conclusion>",
      "impression_generale": "<phrase résumant la fiabilité perçue>",
      "conseil": "<recommandation pour le lecteur>",
      "couleur": "<🟢 | 🟡 | 🔴>",
      "limites": ["<texte>", "..."]
    }}

    Texte à analyser :
    ---
    {text}
    ---
    """

    # ----------------------------
    # 5️⃣  APPEL À L’API GPT
    # ----------------------------
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # modèle rapide et économique
            messages=[
                {"role": "system", "content": "Tu es un moteur d'analyse rigoureux et transparent pour Facto."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3  # faible pour la stabilité des résultats
        )

        # Extraction du contenu textuel
        raw_output = response.choices[0].message.content.strip()

        # ----------------------------
        # 6️⃣  VALIDATION ET PARSING DU JSON
        # ----------------------------
        try:
            result = json.loads(raw_output)
        except json.JSONDecodeError:
            # Si GPT renvoie du texte autour du JSON, on extrait proprement
            match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            result = json.loads(match.group(0)) if match else {"error": "JSON invalide"}

        # ----------------------------
        # 7️⃣  PONDÉRATION ET CALCUL LOCAL DU SCORE GLOBAL
        # ----------------------------
        try:
            fond = result.get("axes", {}).get("fond", {})
            forme = result.get("axes", {}).get("forme", {})

            fond_score = (
                fond.get("justesse", {}).get("note", 0) +
                fond.get("completuede", {}).get("note", 0)
            ) / 2

            forme_score = (
                forme.get("ton", {}).get("note", 0) +
                forme.get("biais", {}).get("note", 0)
            ) / 2

            score_global = round((fond_score * 0.7 + forme_score * 0.3) * 100, 1)
            result["score_global"] = score_global
        except Exception:
            pass  # en cas d’erreur, on garde le score GPT

        # ----------------------------
        # 8️⃣  SAUVEGARDE DANS LES LOGS
        # ----------------------------
        try:
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "texte": text[:2000],  # on limite la taille du texte stocké
                "word_count": word_count,
                "resultat": result
            }
            with open("logs.json", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print("⚠️ Erreur de sauvegarde des logs :", e)

        # ----------------------------
        # 9️⃣  RETOUR AU FRONT
        # ----------------------------
        return jsonify(result)

    except Exception as e:
        print("❌ Erreur GPT :", e)
        return jsonify({"error": str(e)}), 500

# ----------------------------
# 🔟 SYNTHÈSE DU CODE
# ----------------------------
# Ce backend :
# ✅ Reçoit un texte (via POST /analyze)
# ✅ Analyse fond, forme, justesse, ton, biais...
# ✅ Fournit justifications, preuves, éléments manquants
# ✅ Détecte les limites de l’analyse et le type de texte
# ✅ Calcule le score global pondéré (70 % fond / 30 % forme)
# ✅ Enregistre l’analyse dans logs.json
# ✅ Retourne un JSON complet, structuré et lisible par ton front
# ----------------------------

# (Aucune exécution locale à prévoir ici : Render lance automatiquement gunicorn server:app)
