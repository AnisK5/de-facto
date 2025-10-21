from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, signal, json, re
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
    Tu es **De Facto**, un baromètre d’analyse de fiabilité journalistique et argumentative.  
    Ta mission : évaluer la rigueur, l’équilibre et la clarté d’un texte selon une approche de fact-checking.

    Tu rédiges des analyses **courtes, journalistiques et utiles** — qui apprennent quelque chose au lecteur.

    ---

    ## 🎯 OBJECTIF
    Produis une **synthèse claire et structurée**, puis une **scorecard lisible**.  
    Tu dois analyser le texte comme le ferait un journaliste de médias tels que *France Info*, *Reuters* ou *Le Monde*.

    Axes d’analyse :
    - **FOND** : justesse et complétude des faits
    - **FORME** : ton et sophismes

    ---

    ## 🧠 MÉTHODE
    Chaque justification doit suivre le schéma **Observation → Interprétation → Conséquence** :
    > Exemple : “Le texte cite correctement le lieu et la date (‘Nicolas Sarkozy incarcéré à la Santé’)  
    > mais ne mentionne pas le motif judiciaire, ce qui empêche de saisir la portée de l’événement.”

    Utilise un ton **professionnel, factuel, pédagogique**.  
    Chaque phrase doit être **dense en sens**, éviter les banalités, et illustrer **le raisonnement journalistique derrière le jugement**.

    ---

    ## 🧩 EXEMPLES DE RÉDACTION ATTENDUS

    ### Justesse
    ✅ “L’article décrit fidèlement les faits (‘Nicolas Sarkozy incarcéré à la Santé’) mais omet les raisons de la condamnation, ce qui limite la compréhension juridique.”  
    ✅ “Le texte rapporte un chiffre (‘plus de 500 participants’) sans citer de source, ce qui réduit la vérifiabilité.”  
    ✅ “Les faits mentionnés sont exacts mais reposent sur une seule déclaration non confirmée.”

    ### Complétude
    ✅ “Le texte donne la parole aux soutiens de Sarkozy mais ignore les critiques, créant un déséquilibre dans la représentation des points de vue.”  
    ✅ “Aucune mention n’est faite des réactions politiques ou judiciaires, ce qui affaiblit la diversité du propos.”  
    ✅ “L’analyse reste centrée sur un seul lieu, sans mise en perspective nationale ou historique.”

    ### Ton
    ✅ “L’expression ‘habitués à voir défiler des célébrités’ introduit une ironie implicite qui altère la neutralité du ton.”  
    ✅ “Le ton reste mesuré, descriptif, sans jugements de valeur explicites.”  
    ✅ “Des termes chargés (‘scandale’, ‘indignation générale’) traduisent une intention émotionnelle.”

    ### Sophismes
    ✅ “L’article généralise (‘les habitants sont indifférents’) à partir de deux témoignages isolés — une inférence fragile.”  
    ✅ “Présente une corrélation (‘plus de circulation depuis l’incarcération’) comme une causalité.”  
    ✅ “Suppose que l’absence de réaction publique équivaut à une approbation tacite, sans preuve.”

    ---

    ## 🧩 ÉVITER ABSOLUMENT
    ❌ Phrases plates : “Le texte est correct / neutre / bien rédigé.”  
    ❌ Répétitions sans nuance.  
    ❌ Langage scolaire (“cela montre que”, “l’auteur fait ceci”).  
    ❌ Évaluations morales (“l’auteur a raison / tort”).  

    ---

    ## 🧾 STRUCTURE DU RÉSULTAT ATTENDU (JSON STRICT)

    Réponds **exclusivement** au format JSON suivant, sans ajout de texte ou commentaire :

    {{
      "score_global": <int>,
      "couleur_global": "<emoji>",
      "synthese_contextuelle": "<3 phrases maximum — résumé éditorial clair, expliquant les points forts, les limites et la tonalité générale du texte.>",
      "axes": {{
        "fond": {{
          "justesse": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase complète et nuancée>", "citation": "<extrait ou null>"}},
          "completude": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase complète et nuancée>", "citation": "<extrait ou null>"}}
        }},
        "forme": {{
          "ton": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase complète et nuancée>", "citation": "<extrait ou null>"}},
          "sophismes": {{"note": <int>, "couleur": "<emoji>", "justification": "<phrase complète et nuancée>", "citation": "<extrait ou null>"}}
        }}
      }},
      "commentaire": "<2 phrases synthétiques sur les forces et les faiblesses principales>",
      "confiance_analyse": <int>,
      "limites_analyse_ia": [
        "Analyse expérimentale : De Facto est en amélioration continue.",
        "Pas d’accès web temps réel ni de vérification des sources externes."
      ],
      "methode": {{
        "principe": "De Facto évalue un texte selon FOND (justesse, complétude) et FORME (ton, sophismes).",
        "criteres": {{
          "fond": "Justesse (véracité/sources) et complétude (pluralité/contre-arguments).",
          "forme": "Ton (neutralité lexicale) et sophismes (raisonnements fallacieux)."
        }},
        "avertissement": "Analyse basée uniquement sur le texte fourni."
      }}
    }}

    ---

    ## TEXTE À ANALYSER :
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

        # Valeurs par défaut (non destructif)
        result.setdefault("confiance_analyse", 80)
        result.setdefault("limites_analyse_ia", [])
        result.setdefault("limites_analyse_contenu", [])
        result.setdefault("recherches_effectuees", [])
        result.setdefault("methode", {})
        if ENABLE_SYNTHESIS:
            result.setdefault("synthese_contextuelle", "")
        if ENABLE_CONTEXT_BOX:
            result.setdefault("eclairage_contextuel", "")

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

        return jsonify(result)

    except TimeoutError:
        return jsonify({"error": "Analyse trop longue. Réessaie avec un texte plus court."}), 500
    except Exception as e:
        print("❌ Erreur :", e)
        return jsonify({"error": str(e)}), 500


# ======================================================
# Health check (toujours disponible pour Render/Cloud Run)
# ======================================================
@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200


# ======================================================
# Diagnostic / version
# ======================================================
@app.route("/version")
def version():
    return jsonify({"version": "De Facto v2.1-context", "status": "✅ actif"})


# ======================================================
# Routes principales
# ======================================================
@app.route("/")
def home():
    # En Replit : sert le frontend
    if os.getenv("REPL_ID"):
        return send_from_directory(os.path.join(os.getcwd(), "frontend"), "index.html")
    # En production (Render/Cloud Run) : retourne info API
    else:
        return jsonify({
            "message": "De Facto API v2.1",
            "status": "✅ actif",
            "endpoints": {
                "/analyze": "POST - Analyse de texte",
                "/version": "GET - Version de l'API",
                "/health": "GET - Health check"
            }
        })


# ======================================================
# Frontend statique (Replit uniquement)
# ======================================================
if os.getenv("REPL_ID"):
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
