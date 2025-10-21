from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, signal, json, re
from dotenv import load_dotenv
import trafilatura

def extract_text_from_url(url):
    """Extrait automatiquement le texte principal d'un article avec trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            print(f"⚠️ Impossible de télécharger {url}")
            return None
        extracted = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        if not extracted:
            print(f"⚠️ Aucun contenu détecté sur {url}")
            return None
        extracted = extracted.strip()
        if len(extracted) < 300:
            print("⚠️ Contenu trop court, probablement une page vide.")
            return None
        return extracted[:8000]  # Tronquage de sécurité
    except Exception as e:
        print(f"❌ Erreur extraction Trafilatura : {e}")
        return None

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

    # 🧩 Nouvelle étape : détection et extraction d'article via trafilatura
    if re.match(r"^https?://", text):
        fetched = extract_text_from_url(text)
        if fetched:
            text = fetched
            print("✅ Article extrait avec Trafilatura (longueur :", len(text), ")")
        else:
            print("⚠️ Extraction échouée ou contenu vide.")

    # Sécurité : tronquer les textes très longs
    if len(text) > MAX_LEN:
        texte_tronque = True
        text = text[:MAX_LEN] + " [...] (texte tronqué pour analyse)"
    
    # Mode enrichi activé
    ENABLE_ENRICHED = True

    # Prompt principal enrichi
    prompt = f"""
    Tu es De Facto, un baromètre d’analyse de fiabilité et de rigueur journalistique.
    Tu produis une **scorecard claire et utile** (score global + 4 sous-notes), accompagnée d’un **éclairage contextuel** inspiré des pratiques fact-checking.

    ### Objectif
    Mesurer la **fiabilité perçue** d’un texte en analysant :
    - la précision des faits,
    - la diversité des points de vue,
    - le ton employé,
    - et la qualité argumentative.

    ### Échelle stricte
    ⚠️ **Toutes les notes sont sur 100**, pas sur 10.  
    Un texte “moyennement fiable” tourne autour de 60–70.  
    Un texte “faible” <40.  
    Un texte “exemplaire” >85.

    ### Grille d’analyse
    **FOND :**
    - *Justesse* → véracité, sources, précision factuelle.
    - *Complétude* → pluralité, contre-arguments, nuances.

    **FORME :**
    - *Ton* → neutralité lexicale, absence d’émotion.
    - *Sophismes* → détection de généralisations, biais de causalité, appels à l’émotion.

    ### Éclairage contextuel
    Ajoute une section intitulée **"Éclairage contextuel"** comportant :
    - une sous-partie **"Faits complémentaires"** : 1 à 3 rappels contextuels ou éléments connus dans la presse ou les bases factuelles internes (ex. Wikipédia, Le Monde, Reuters, etc.),
    - une sous-partie **"Manques identifiés"** : ce que l’article omet et qui changerait la perception s’il était inclus,
    - termine par une phrase sur **l’impact de ces manques sur la fiabilité**.

    ### Format de réponse (strict JSON)
    {{
      "score_global": <int>,
      "couleur_global": "<emoji>",
      "axes": {{
        "fond": {{
          "justesse": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase>", "citation": "<20 mots max>"}},
          "completude": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase>", "citation": "<20 mots max>"}}
        }},
        "forme": {{
          "ton": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase>", "citation": "<20 mots max>"}},
          "sophismes": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase>", "citation": "<20 mots max>"}}
        }}
      }},
      "commentaire": "<2 phrases max : forces/faiblesses>",
      "resume": "<3 phrases max>",
      "eclairage_contextuel": {{
        "faits_complementaires": ["<texte>", "..."],
        "manques_identifies": ["<texte>", "..."],
        "impact_fiabilite": "<phrase>"
      }},
      "confiance_analyse": <int>,
      "limites_analyse_ia": ["<texte>", "..."],
      "limites_analyse_contenu": ["<texte>", "..."],
      "methode": {{
        "principe": "Analyse selon FOND (justesse, complétude) et FORME (ton, sophismes).",
        "avertissement": "Analyse basée sur le texte fourni ; sans accès web temps réel."
      }}
    }}

    Texte à analyser :
    ---
    {text}
    ---
    """

    try:
        signal.alarm(25)

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role":
                "system",
                "content":
                "Tu es un analyste textuel rigoureux, concret et pédagogue."
            }, {
                "role": "user",
                "content": prompt
            }],
            temperature=0.2)
        signal.alarm(0)

        raw = resp.choices[0].message.content.strip()

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return jsonify(
                    {"error": "Réponse GPT non conforme (non JSON)."}), 500
            result = json.loads(m.group(0))

        # Valeurs par défaut
        result.setdefault("confiance_analyse", 80)
        result.setdefault(
            "eclairage", {
                "faits_complementaires": [],
                "manques_identifies": [],
                "impact_sur_fiabilite": ""
            })
        result.setdefault("limites_analyse_ia", [])
        result.setdefault("limites_analyse_contenu", [])
        result.setdefault("recherches_effectuees", [])
        result.setdefault(
            "methode", {
                "principe":
                "De Facto évalue un texte selon FOND (justesse, complétude) et FORME (ton, sophismes).",
                "criteres": {
                    "fond":
                    "Justesse (véracité/sources) et complétude (pluralité/contre-arguments).",
                    "forme":
                    "Ton (neutralité) et sophismes (raisonnements fallacieux)."
                },
                "avertissement":
                "Analyse basée sur le texte fourni ; pas d’accès web temps réel."
            })

        # Couleurs
        if "score_global" in result:
            result.setdefault("couleur_global",
                              color_for(int(result["score_global"])))
        axes = result.get("axes", {})
        for bloc in ("fond", "forme"):
            if bloc in axes and isinstance(axes[bloc], dict):
                for crit in axes[bloc].values():
                    if isinstance(crit, dict) and "note" in crit:
                        crit.setdefault("couleur",
                                        color_for(int(crit["note"])))

        if texte_tronque:
            result["texte_tronque"] = True
            result["limites_analyse_contenu"].append(
                f"Analyse effectuée sur un extrait (max {MAX_LEN} caractères sur {original_length})."
            )

        return jsonify(result)

    except TimeoutError:
        return jsonify({
            "error":
            "Analyse trop longue. Réessaie avec un texte plus court."
        }), 500
    except Exception as e:
        print("❌ Erreur:", e)
        return jsonify({"error": str(e)}), 500


# ---------------------------
# Serve frontend in dev (Replit)
# ---------------------------
if os.getenv("REPL_ID"):

    @app.route("/")
    def serve_frontend():
        return send_from_directory(os.path.join(os.getcwd(), "frontend"),
                                   "index.html")

    @app.route("/<path:path>")
    def serve_static(path):
        frontend_path = os.path.join(os.getcwd(), "frontend")
        file_path = os.path.join(frontend_path, path)
        if os.path.exists(file_path):
            return send_from_directory(frontend_path, path)
        else:
            return send_from_directory(frontend_path, "index.html")


# ---------------------------
# Endpoint de version / diagnostic
# ---------------------------


@app.route("/")
def home():
    return jsonify({
        "message": "Backend De Facto actif",
        "version": "1.9-strict",
        "routes": ["/analyze", "/version"]
    })


@app.route("/version")
def version():
    return jsonify({
        "version": "De Facto v1.9-strict",
        "temperature": 0.2,
        "status": "backend actif ✅"
    })


# ---------------------------
# Run app
# ---------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
