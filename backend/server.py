from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, signal, json, re
from datetime import datetime
from dotenv import load_dotenv

# ======================================================
# ⚙️ Feature flags — activables/désactivables sans casser
# ======================================================
ENABLE_SYNTHESIS = True       # Ajoute une synthèse narrative lisible
ENABLE_CONTEXT_BOX = True     # Ajoute un éclairage contextuel court
ENABLE_TRANSPARENCY = True    # Ajoute mentions "expérimental" et tronquage
ENABLE_URL_EXTRACT = True     # Active Trafilatura (si URL fournie)

# ======================================================
# Flask setup
# ======================================================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ======================================================
# OpenAI client
# ======================================================
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ======================================================
# Timeout (Render/Replit safety)
# ======================================================
def _timeout_handler(signum, frame):
    raise TimeoutError("Analyse trop longue (timeout Render).")
signal.signal(signal.SIGALRM, _timeout_handler)

# ======================================================
# Helpers
# ======================================================
def color_for(score: int) -> str:
    if score is None: return "⚪"
    if score >= 70: return "🟢"
    if score >= 40: return "🟡"
    return "🔴"


# ======================================================
# 🧩 Route principale : analyse
# ======================================================
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Aucun texte reçu"}), 400

    # 🔗 Extraction d’URL via Trafilatura (si activée)
    if ENABLE_URL_EXTRACT and re.match(r"^https?://", text):
        try:
            import trafilatura
            fetched = trafilatura.extract(trafilatura.fetch_url(text)) or ""
            if len(fetched.strip()) >= 300:
                text = fetched.strip()[:8000]
                print(f"✅ Trafilatura OK (len={len(text)})")
            else:
                print("⚠️ Extraction trop courte, texte brut conservé.")
        except Exception as e:
            print("⚠️ Trafilatura indisponible :", e)

    # Tronquage protecteur
    MAX_LEN = 8000
    texte_tronque = len(text) > MAX_LEN
    original_length = len(text)
    if texte_tronque:
        text = text[:MAX_LEN] + " [...] (texte tronqué pour analyse)"

    # ======================================================
    # 🧠 Prompt enrichi
    # ======================================================
    prompt = f"""
    Tu es **De Facto**, un analyste de contenu journalistique.  
    Ton rôle est d'évaluer un texte selon deux axes : **FOND** (justesse, complétude) et **FORME** (ton, sophismes),  
    puis de produire une **analyse claire, utile et concrète**.

    ---

    ### 🎯 Objectif
    Fournir une **analyse journalistique enrichissante**, pas une évaluation scolaire.  
    Chaque réponse doit **aider l'utilisateur à comprendre ce que le texte dit, oublie, ou oriente.**

    ---

    ### 🧩 Structure de sortie (STRICT JSON)
    Tu répondras **uniquement** en JSON au format suivant :
    {{
      "score_global": <int>,
      "couleur_global": "<emoji>",
      "axes": {{
        "fond": {{
          "justesse": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase claire>", "citation": "<<=20 mots ou null>"}},
          "completude": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase claire>", "citation": "<<=20 mots ou null>"}}
        }},
        "forme": {{
          "ton": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase claire>", "citation": "<<=20 mots ou null>"}},
          "sophismes": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase claire>", "citation": "<<=20 mots ou null>"}}
        }}
      }},
      "commentaire": "<2 phrases de synthèse journalistique>",
      "resume": "<3 phrases synthétiques, utiles et percutantes>",
      "confiance_analyse": <int>,
      "explication_confiance": "<phrase expliquant pourquoi la confiance est à ce niveau>",
      "hypothese_interpretative": "<1 phrase : raison possible du ton ou du cadrage médiatique>",
      "limites_analyse_ia": ["<texte>", "..."],
      "limites_analyse_contenu": ["<texte>", "..."],
      "recherches_effectuees": ["<résumé court>", "..."],
      "methode": {{
        "principe": "De Facto évalue le texte selon deux axes : FOND (justesse, complétude) et FORME (ton, sophismes).",
        "criteres": {{
          "fond": "Justesse (véracité/sources) et complétude (pluralité/contre-arguments).",
          "forme": "Ton (neutralité lexicale) et sophismes (raisonnements fallacieux)."
        }},
        "avertissement": "Analyse expérimentale — le modèle peut commettre des erreurs."
      }}
    }}

    ---

    ### 🧠 Directives pour chaque section

    #### 🟩 Synthèse globale (commentaire + résumé)
    Rédige comme un mini article.  
    Mets en avant **ce qui manque, ce qui biaise, ou ce qui change la compréhension**.

    **Exemples :**
    - « L’article présente les faits judiciaires de manière exacte mais omet les arguments de la défense, ce qui oriente la lecture. »
    - « Le texte décrit l’émotion du public sans rappeler les faits de base, créant une impression partielle. »
    - « Les données chiffrées sont exactes mais décontextualisées, ce qui exagère la gravité du phénomène. »

    À éviter :
    - « Le ton est neutre. »
    - « Le texte manque de détails. »

    ---

    #### 🧩 Détails des 4 critères

    **Exemples de bonnes justifications :**
    - Justesse 🟢 : « L’auteur cite la condamnation de 2021 avec précision. »
    - Complétude 🟡 : « Aucune mention des arguments adverses. »
    - Ton 🔴 : « L’expression “enfin condamné” montre un parti pris implicite. »
    - Sophismes 🟡 : « L’auteur généralise à partir d’un seul témoignage. »


    ### 📰 Conscience du média
    Si le texte provient d’un média connu, identifie son orientation ou ton éditorial habituel
    (ex. CNews, Mediapart, Le Figaro, Libération, etc.)
    et explique si cela peut influencer la présentation des faits.

    Exemples :
    - « CNews, souvent perçu comme orienté à droite, met l’accent sur les critiques de la gauche et minimise les contre-arguments. »
    - « Mediapart adopte une approche plus militante, ce qui explique le ton accusatoire. »
    - « Le Monde privilégie un ton factuel et analytique. »

    ---

    #### 🔍 Confiance de l’analyse
Ce score indique **dans quelle mesure ton évaluation du texte est fiable**, pas la fiabilité du texte lui-même.

Rédige une phrase simple expliquant pourquoi la confiance de l’analyse est à ce niveau, 
sans répéter le pourcentage ni la mention “Confiance faible/moyenne/élevée”.  
Donne une raison concrète liée au texte : longueur, structure, ton ironique, caractère tronqué, ou densité factuelle.

**Exemples :**
- « Analyse fiable car le texte est clair et bien structuré. »
- « Texte court ou tronqué, ce qui limite la fiabilité de l’analyse. »
- « Ton ironique et ambigu, ce qui rend l’interprétation prudente. »



    ---

    #### 💭 Hypothèse éditoriale
    Explique brièvement pourquoi le texte est rédigé de cette manière selon son cadrage médiatique.

    ---

    #### ⚠️ Transparence
    - Si le texte est un extrait, le signaler.
    - Mentionner qu’il s’agit d’une **analyse IA expérimentale.**

    ---

    ### 🧾 Texte à analyser :
    ---
    {text}
    ---
    """

    try:
        signal.alarm(30)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un analyste journalistique rigoureux, concis et clair."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.25
        )
        signal.alarm(0)

        raw = resp.choices[0].message.content.strip()

        # Parsing JSON tolérant
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return jsonify({"error": "Réponse GPT non conforme (non JSON)"}), 500
            result = json.loads(m.group(0))

        # Valeurs par défaut
        result.setdefault("confiance_analyse", 80)
        result.setdefault("limites_analyse_ia", [])
        result.setdefault("limites_analyse_contenu", [])
        result.setdefault("recherches_effectuees", [])
        result.setdefault("methode", {})

        # Couleurs
        if "score_global" in result:
            result["couleur_global"] = color_for(int(result["score_global"]))
        axes = result.get("axes", {})
        for bloc in ("fond", "forme"):
            for crit in (axes.get(bloc) or {}).values():
                if isinstance(crit, dict) and "note" in crit:
                    crit.setdefault("couleur", color_for(int(crit["note"])))

        # Transparence
        if ENABLE_TRANSPARENCY:
            if texte_tronque:
                result["limites_analyse_contenu"].append(
                    f"Analyse effectuée sur un extrait (max {MAX_LEN} caractères sur {original_length})."
                )
            if not any("Analyse expérimentale" in x for x in result["limites_analyse_ia"]):
                result["limites_analyse_ia"].append(
                    "Analyse expérimentale : De Facto est en amélioration continue et peut comporter des imprécisions."
                )

        # ======================================================
        # 🪣 Sauvegarde historique locale
        # ======================================================
        try:
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "input_excerpt": text[:300],
                "score_global": result.get("score_global"),
                "resume": result.get("resume"),
                "commentaire": result.get("commentaire")
            }
            with open("logs.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print("⚠️ Impossible d’écrire le log :", e)

        return jsonify(result)

    except TimeoutError:
        return jsonify({"error": "Analyse trop longue. Réessaie avec un texte plus court."}), 500
    except Exception as e:
        print("❌ Erreur :", e)
        return jsonify({"error": str(e)}), 500


# ======================================================
# 📜 Historique des analyses
# ======================================================
@app.route("/logs", methods=["GET"])
def get_logs():
    """Retourne les 50 dernières analyses enregistrées."""
    logs = []
    try:
        if os.path.exists("logs.jsonl"):
            with open("logs.jsonl", "r", encoding="utf-8") as f:
                for line in f:
                    logs.append(json.loads(line))
        logs = sorted(logs, key=lambda x: x["timestamp"], reverse=True)[:50]
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(logs)


# ======================================================
# Diagnostic / version
# ======================================================
@app.route("/version")
def version():
    return jsonify({"version": "De Facto v2.3-hist-complete", "status": "✅ actif"})


# ======================================================
# Frontend (Replit uniquement)
# ======================================================
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


# ======================================================
# Run
# ======================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
