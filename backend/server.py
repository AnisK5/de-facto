from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
import os, signal, json, re, requests, urllib.parse, time
from datetime import datetime
from dotenv import load_dotenv

# ======================================================
# ⚙️ Feature flags — activables/désactivables sans casser
# ======================================================
ENABLE_SYNTHESIS = True       # Ajoute une synthèse narrative lisible
ENABLE_CONTEXT_BOX = True     # Ajoute un éclairage contextuel court + web enrichi
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
# 🌐 Recherche Google CSE (Programmable Search API)
# ======================================================
ALLOWED_SITES = [
    "reuters.com", "apnews.com", "bbc.com",
    "lemonde.fr", "francetvinfo.fr",
    "lefigaro.fr", "liberation.fr", "leparisien.fr"
]

def search_web_results(queries, per_query=5, pause=0.5):
    """Recherche Google CSE (Programmable Search API) sur plusieurs entités ou requêtes."""
    api_key = os.getenv("GOOGLE_CSE_API_KEY")
    cx = os.getenv("GOOGLE_CSE_CX")
    if not api_key or not cx:
        print("⚠️ GOOGLE_CSE_API_KEY ou GOOGLE_CSE_CX manquant — recherche désactivée.")
        return []

    all_hits = []
    seen = set()
    for q in queries:
        site_filter = " OR ".join([f"site:{s}" for s in ALLOWED_SITES])
        full_q = f"{q} ({site_filter})"
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": api_key,
            "cx": cx,
            "q": full_q,
            "num": per_query,
            "hl": "fr",
            "lr": "lang_fr",
            "safe": "off"
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                print("⚠️ Erreur Google CSE:", r.status_code, r.text[:200])
                continue
            data = r.json()
            results = []
            for item in data.get("items", []) or []:
                link = item.get("link")
                if link and link not in seen:
                    seen.add(link)
                    results.append({
                        "titre": item.get("title"),
                        "snippet": item.get("snippet"),
                        "url": link
                    })
            if results:
                all_hits.append({"entité": q, "sources": results})
            time.sleep(pause)
        except Exception as e:
            print("⚠️ Erreur recherche Google:", e)
            continue
    return all_hits

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
    # 🧩 Étape 1 — Pré-analyse de type de texte (faits/opinions/autres)
    # ======================================================
    try:
        pre_prompt = f"""
        Classe le texte selon 3 catégories :
        - FAITS (affirmations vérifiables)
        - OPINIONS (jugements ou interprétations)
        - AUTRES (ironie, satire, poésie, récit, etc.)

        Retourne un JSON au format :
        {{
          "faits": <int>,
          "opinions": <int>,
          "autres": <int>
        }}
        Texte :
        {text[:2000]}
        """
        pre_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un linguiste qui catégorise les phrases d'un texte."},
                {"role": "user", "content": pre_prompt}
            ],
            temperature=0
        )
        fact_mix = json.loads(pre_resp.choices[0].message.content.strip())
    except Exception as e:
        print("⚠️ Erreur pré-analyse :", e)
        fact_mix = {"faits": 0, "opinions": 0, "autres": 0}

    total = sum(fact_mix.values()) or 1
    densite_faits = int((fact_mix["faits"] / total) * 100)
    type_texte = (
        "Principalement factuel" if densite_faits > 60 else
        "Opinion ou analyse" if fact_mix["opinions"] > 40 else
        "Autre (narratif, satirique…)"
    )

    # ======================================================
    # 🌍 Étape intermédiaire : Recherche Web enrichie
    #    (entités → recherche → faits manquants / contradictions / impact)
    # ======================================================
    def web_context_research(text: str):
        """
        Étape d'enrichissement factuel :
        1) Extrait les entités du texte (personnes, lieux, orga, événements)
        2) Recherche des sources fiables (Reuters, AP, BBC, Le Monde, Franceinfo)
        3) Synthétise : faits manquants précis + contradictions + impact + fiabilité
        Retour JSON robuste même en cas d'échec partiel.
        """
        try:
            # 1) Extraction d'entités
            ent_prompt = f"""
            Extrait les principales entités nommées (personnes, lieux, organisations, événements, lois, chiffres clés)
            du texte suivant :
            {text[:2000]}

            Réponds uniquement en JSON : ["entité1", "entité2", ...]
            """
            ent_resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Tu es un extracteur d'entités journalistiques (NER)."},
                    {"role": "user", "content": ent_prompt}
                ],
                temperature=0
            )
            try:
                entities = json.loads(ent_resp.choices[0].message.content.strip())
            except Exception:
                entities = []
            if not isinstance(entities, list):
                entities = []
            entities = [e for e in entities if isinstance(e, str) and e.strip()]
            if not entities:
                return {
                    "recherches_effectuees": [],
                    "faits_manquants": [],
                    "contradictions": [],
                    "impact": "faible",
                    "fiabilite_sources": "Aucune source consultable (pas d'entités détectées).",
                    "synthese": "Aucune entité détectée — enrichissement impossible."
                }

            # 2) Recherche Web (Google CSE) — requêtes multi-angles
            queries = []
            for ent in entities[:5]:
                queries += [
                    f"{ent} actualité",
                    f"{ent} controverse",
                    f"{ent} critiques",
                    f"{ent} biographie",
                    f"{ent} politique"
                ]
            recherches = search_web_results(queries, per_query=4)

            # 3) Fusion IA : comparer texte vs résultats
            synth_prompt = f"""
            Compare le texte suivant :
            {text[:3500]}

            Avec ces résultats de recherche (médias généralistes fiables et agences) :
            {json.dumps(recherches, ensure_ascii=False, indent=2)}

            Ton rôle :
            1. Identifier les **faits précis manquants** (dates, chiffres, citations, critiques, décisions officielles) à ajouter.
            2. Signaler les **contradictions** ou corrections notables entre le texte et les sources.
            3. Évaluer la **fiabilité** globale des sources (diversité, réputation).
            4. Estimer l’**impact** des manques/contradictions sur la compréhension du lecteur (faible / moyen / fort).
            5. Résumer en 2 phrases utiles.

            Réponds en JSON strict :
            {{
              "faits_manquants": [
                {{"texte": "<fait ajouté>", "source": "<média>", "url": "<url ou null>"}}
              ],
              "contradictions": ["<phrase>", "..."],
              "impact": "<faible|moyen|fort>",
              "fiabilite_sources": "<phrase brève>",
              "synthese": "<2 phrases de résumé>"
            }}
            """
            synth_resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Tu es un fact-checker journalistique expert et neutre."},
                    {"role": "user", "content": synth_prompt}
                ],
                temperature=0.3
            )

            try:
                result = json.loads(synth_resp.choices[0].message.content.strip())
            except Exception:
                # fallback compact si parsing impossible
                result = {
                    "faits_manquants": [],
                    "contradictions": [],
                    "impact": "faible",
                    "fiabilite_sources": "Synthèse non structurée.",
                    "synthese": "La synthèse n'a pas pu être structurée."
                }

            # joindre les recherches brutes pour le front / debug
            result["recherches_effectuees"] = recherches
            # normaliser impact
            impact = (result.get("impact") or "faible").strip().lower()
            if impact not in ("faible", "moyen", "fort"):
                impact = "faible"
            result["impact"] = impact

            # nettoyer faits_manquants (format stable)
            fm = []
            for f in result.get("faits_manquants", []) or []:
                if isinstance(f, dict) and f.get("texte"):
                    fm.append({
                        "texte": str(f.get("texte")).strip(),
                        "source": (f.get("source") or "").strip() or None,
                        "url": (f.get("url") or "").strip() or None
                    })
            result["faits_manquants"] = fm

            # contradictions => liste de str
            contr = []
            for c in result.get("contradictions", []) or []:
                if isinstance(c, str) and c.strip():
                    contr.append(c.strip())
            result["contradictions"] = contr

            return result

        except Exception as e:
            print("⚠️ Web context failed:", e)
            return {
                "recherches_effectuees": [],
                "faits_manquants": [],
                "contradictions": [],
                "impact": "faible",
                "fiabilite_sources": "Recherche contextuelle non disponible.",
                "synthese": "Recherche contextuelle non disponible."
            }

    web_info = web_context_research(text) if ENABLE_CONTEXT_BOX else {
        "recherches_effectuees": [],
        "faits_manquants": [],
        "contradictions": [],
        "impact": "faible",
        "fiabilite_sources": "Contexte non activé.",
        "synthese": "Contexte non activé."
    }

    # ======================================================
    # 🧠 Étape 3 — Analyse principale complète
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
    et explique si cela peut influencer la présentation des faits.

    ---

    ### 🌍 Compléments factuels trouvés sur le Web (à exploiter)
    {json.dumps(web_info, ensure_ascii=False, indent=2)}

    ---
### ⚔️ Instruction spéciale — mode "analyse investigatrice"
Utilise les résultats de la recherche Web pour :
- Citer les faits précis absents du texte, avec leurs sources.
- Évaluer la gravité de ces omissions : si elles changent la compréhension globale, abaisse fortement la note de complétude.
- Si une contradiction claire est trouvée, baisse la note de justesse.
- Mentionne ces faits manquants explicitement dans le commentaire et le résumé.

    ### 🧾 Texte à analyser :
    ---
    {text}
    ---
    """

    try:
        signal.alarm(45)
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
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return jsonify({"error": "Réponse GPT non conforme (non JSON)"}), 500
            result = json.loads(m.group(0))

        # ======================================================
        # Post-traitement enrichi
        # ======================================================
        result.setdefault("confiance_analyse", 80)
        result.setdefault("type_texte", type_texte)
        result.setdefault("densite_faits", densite_faits)

        # 🎯 Pondération douce du score global selon densité factuelle
        if "score_global" in result:
            sg = int(result["score_global"])
            if densite_faits > 60:
                sg = min(sg + 5, 100)
            elif densite_faits < 30:
                sg = max(sg - 5, 0)
            result["score_global"] = sg
            result["couleur_global"] = color_for(sg)

        # 🔎 Ajoute info sur le contenu du texte
        result["composition"] = {
            "faits": fact_mix["faits"],
            "opinions": fact_mix["opinions"],
            "autres": fact_mix["autres"],
            "densite_faits": densite_faits
        }

        # 🌍 Insère le contexte Web brute pour le front
        result["faits_complementaires"] = web_info.get("faits_manquants", [])
        result["contexte_synthese"] = web_info.get("synthese")
        result["contexte_impact"] = web_info.get("impact")
        result["contexte_contradictions"] = web_info.get("contradictions", [])
        result["contexte_fiabilite_sources"] = web_info.get("fiabilite_sources", "")
        result["recherches_effectuees"] = web_info.get("recherches_effectuees", [])

        # 🧮 PONDÉRATION INTELLIGENTE SELON LE CONTEXTE WEB
        # Barème explicite :
        # - Contradictions : -20 (≥2), -10 (1)
        # - Faits manquants : -25 (≥3), -15 (2), -8 (1) sur complétude
        # - Impact global "moyen" : -5 sur score global ; "fort" : -10
        axes = result.get("axes", {}) or {}
        fond = axes.get("fond", {}) or {}
        justesse = (fond.get("justesse", {}) or {}).get("note", 70)
        completude = (fond.get("completude", {}) or {}).get("note", 70)

        nb_contrad = len(web_info.get("contradictions", []) or [])
        nb_faits = len(web_info.get("faits_manquants", []) or [])
        impact = (web_info.get("impact") or "faible").lower()

        # Ajustements justesse par contradictions
        if nb_contrad >= 2:
            justesse -= 20
        elif nb_contrad == 1:
            justesse -= 10

        # Ajustements complétude par faits manquants
        if nb_faits >= 3:
            completude -= 25
        elif nb_faits == 2:
            completude -= 15
        elif nb_faits == 1:
            completude -= 8

        # Clamps 0..100
        justesse = max(0, min(100, int(justesse)))
        completude = max(0, min(100, int(completude)))

        # Replace in result if structure exists
        if "fond" in axes:
            if "justesse" in axes["fond"]:
                axes["fond"]["justesse"]["note"] = justesse
                axes["fond"]["justesse"]["couleur"] = color_for(justesse)
            if "completude" in axes["fond"]:
                axes["fond"]["completude"]["note"] = completude
                axes["fond"]["completude"]["couleur"] = color_for(completude)

        # Ajustement score global par impact
        if "score_global" in result:
            if "fort" in impact:
                result["score_global"] = max(0, result["score_global"] - 10)
            elif "moyen" in impact:
                result["score_global"] = max(0, result["score_global"] - 5)
            result["couleur_global"] = color_for(result["score_global"])

        # ✅ (Optionnel) Enregistrer une trace pour /logs
        try:
            log_item = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "input_len": original_length,
                "texte_tronque": bool(texte_tronque),
                "type_texte": type_texte,
                "densite_faits": densite_faits,
                "web_faits_manquants": nb_faits,
                "web_contradictions": nb_contrad,
                "web_impact": impact,
                "score_global": result.get("score_global"),
                "axes": result.get("axes", {}),
                "resume": result.get("resume"),
                "commentaire": result.get("commentaire"),
            }
            with open("logs.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_item, ensure_ascii=False) + "\n")
        except Exception as e:
            print("ℹ️ Échec d'écriture logs.jsonl :", e)

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
                    try:
                        logs.append(json.loads(line))
                    except Exception:
                        continue
        logs = sorted(logs, key=lambda x: x.get("timestamp", ""), reverse=True)[:50]
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(logs)


# ======================================================
# Diagnostic / version
# ======================================================
@app.route("/version")
def version():
    return jsonify({"version": "De Facto v2.7-explicable-CSE", "status": "✅ actif"})


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
