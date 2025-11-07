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
# 🧩 Commentaire web
# ======================================================

def formate_commentaires_web(web_info):
    """Crée un commentaire journalistique à partir des faits manquants, contradictions et divergences."""
    commentaires = []

    # Contradictions : ton “fact-check” nuancé
    for c in web_info.get("contradictions", []) or []:
        if isinstance(c, dict):
            commentaires.append(
                f"Selon {c.get('source', 'une source')}, {c.get('correction_ou_nuance', '').strip()} "
                f"ce qui nuance l’affirmation du texte ({c.get('affirmation_du_texte', '').strip()})."
            )
        elif isinstance(c, str):
            commentaires.append(c.strip())

    # Faits manquants : ton “analyse critique”
    for f in web_info.get("faits_manquants", []) or []:
        if isinstance(f, dict):
            commentaires.append(
                f"Le texte n’évoque pas {f.get('description', '').strip()} "
                f"(mentionné par {f.get('source', 'une autre source')}). "
                f"{f.get('explication', '').strip()}"
            )

    # Divergences de cadrage : ton “analyse narrative”
    for d in web_info.get("divergences_de_cadrage", []) or []:
        if isinstance(d, dict):
            commentaires.append(
                f"Le cadrage diffère : {d.get('resume', '').strip()} "
                f"{d.get('impact', '').strip()}"
            )

    # Synthèse finale (courte)
    synth = web_info.get("synthese", "")
    if synth:
        commentaires.append(synth.strip())

    return " ".join(commentaires[:5]) or "Aucun écart majeur entre le texte et les sources consultées."


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
        raw_content = pre_resp.choices[0].message.content.strip()
        # Parsing JSON robuste avec regex
        try:
            fact_mix = json.loads(raw_content)
        except json.JSONDecodeError:
            # Tenter d'extraire le JSON du texte
            m = re.search(r"\{.*\}", raw_content, re.DOTALL)
            if m:
                fact_mix = json.loads(m.group(0))
            else:
                raise
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
            raw_entities = ent_resp.choices[0].message.content.strip()
            try:
                entities = json.loads(raw_entities)
            except json.JSONDecodeError:
                # Tenter d'extraire le JSON array du texte
                m = re.search(r"\[.*\]", raw_entities, re.DOTALL)
                if m:
                    try:
                        entities = json.loads(m.group(0))
                    except Exception:
                        entities = []
                else:
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
            
            print("🌍 Recherche web activée — entités détectées :", entities)
            recherches = search_web_results(queries, per_query=4)
            print("✅ Recherche web terminée, résultats trouvés :", len(recherches))

            # 3) Fusion IA : comparer texte vs résultats
            synth_prompt = f"""
            Tu es un assistant d'analyse journalistique et de fact-checking avancé.
            Ta mission est d’évaluer le texte fourni en le confrontant à des sources d’information fiables du web.
            Tu dois adopter une approche nuancée, capable de détecter :
            - les faits complémentaires,
            - les omissions,
            - les divergences de cadrage,
            - et les interprétations différentes ou contraires.

            TEXTE À ANALYSER :
            {text}

            SOURCES WEB :
            {json.dumps(recherches, ensure_ascii=False, indent=2)}

            Tu répondras en JSON structuré, selon le format suivant :

            {{
              "faits_manquants": [
                {{
                  "description": "Décris un fait, une donnée, un acteur ou un point de vue pertinent non mentionné dans le texte, mais présent dans les sources.",
                  "source": "<nom du média ou acteur>",
                  "url": "<lien vers la source>",
                  "explication": "Explique comment cette omission ou ce complément modifierait la compréhension du texte (ex: change l’équilibre, nuance une affirmation, apporte un contexte contradictoire, etc.)."
                }}
              ],
              "contradictions": [
                {{
                  "affirmation_du_texte": "Phrase, idée ou ton du texte à confronter.",
                  "correction_ou_nuance": "Énonce ce que disent les sources web (faits, citations, chiffres, etc.) qui contredisent ou relativisent l'affirmation.",
                  "source": "<média ou acteur>",
                  "url": "<lien>"
                }}
              ],
              "divergences_de_cadrage": [
                {{
                  "resume": "Décris un écart d'angle, de ton ou de narration entre le texte et les sources (par ex : l’article met l’accent sur X alors que les sources insistent sur Y).",
                  "impact": "Explique en quoi ce cadrage différent influence la perception du lecteur."
                }}
              ],
              "impact_global": "<faible|moyen|fort>",
              "fiabilite_sources": "Décris brièvement la crédibilité, diversité et cohérence des sources trouvées.",
              "synthese": "Rédige une synthèse fluide (3–6 phrases) qui explique comment le texte se positionne par rapport aux faits établis et aux autres récits du web. Sois analytique, nuancé et journalistique — ni moralisateur ni mécanique."
            }}

            Règles de style :
            - Adopte un ton journalistique neutre, comme dans une rubrique de fact-checking du Monde, Reuters ou AFP.
            - Évite les jugements (“faux”, “mensonger”) sauf si la contradiction est flagrante.
            - Sois capable d’intégrer plusieurs angles (scientifique, politique, social) selon le sujet.
            - Si les sources ne permettent pas de confirmer ni d’infirmer, dis-le explicitement.
            - Ne dupliques pas les extraits ; reformule clairement.
            """


            synth_resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Tu es un fact-checker journalistique expert et neutre."},
                    {"role": "user", "content": synth_prompt}
                ],
                temperature=0.3
            )

            content = synth_resp.choices[0].message.content.strip()
            try:
                web_summary = json.loads(content)
            except Exception:
                m = re.search(r"\{.*\}", content, re.DOTALL)
                web_summary = json.loads(m.group(0)) if m else {
                    "faits_manquants": [],
                    "contradictions": [],
                    "impact": "faible",
                    "fiabilite_sources": "Réponse non structurée.",
                    "synthese": "Le modèle n’a pas pu formater correctement la réponse."
                }

            return web_summary


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
    Tu es **De Facto**, un analyste journalistique spécialisé dans la compréhension critique de l'information.  
    Ta mission : aider un lecteur à **comprendre ce qu’un texte dit, omet et sous-entend**, en t’appuyant sur les faits vérifiables et les sources web.

    ---

    ### 🎯 Objectif général
    Fournir une **analyse journalistique claire, utile et engageante**, qui révèle ce que l’utilisateur aurait *intérêt à savoir* après avoir lu cet article.

    Tu dois produire :
    - des **sous-notes riches et explicatives** (justesse, complétude, ton, sophismes)
    - une **synthèse fluide et percutante**, rédigée dans le style d’un article bref de fact-checking.

    ---

    ### 🧩 Structure de sortie (STRICT JSON)
    Réponds uniquement en JSON au format suivant :
    {{
      "score_global": <int>,
      "couleur_global": "<emoji>",
      "axes": {{
        "fond": {{
          "justesse": {{
            "note": <int>,
            "couleur": "<emoji>",
            "justification": "<2–3 phrases d’analyse précises, avec exemples>",
            "citation": "<<=20 mots ou null>"
          }},
          "completude": {{
            "note": <int>,
            "couleur": "<emoji>",
            "justification": "<2–3 phrases sur les omissions ou contrepoints manquants>",
            "citation": "<<=20 mots ou null>"
          }}
        }},
        "forme": {{
          "ton": {{
            "note": <int>,
            "couleur": "<emoji>",
            "justification": "<2–3 phrases sur le ton, les choix lexicaux, l’orientation implicite>",
            "citation": "<<=20 mots ou null>"
          }},
          "sophismes": {{
            "note": <int>,
            "couleur": "<emoji>",
            "justification": "<2–3 phrases sur la rigueur argumentative, ou absence de sophismes>",
            "citation": "<<=20 mots ou null>"
          }}
        }}
      }},
      "commentaire": "<2 phrases fortes, journalistiques, synthétisant le verdict global>",
      "resume": "<3–6 phrases de synthèse fluide et captivante>",
      "confiance_analyse": <int>,
      "explication_confiance": "<phrase sur la fiabilité de l’analyse>",
      "hypothese_interpretative": "<1 phrase sur la logique médiatique ou éditoriale du texte>",
      "limites_analyse_ia": ["<texte>", "..."],
      "limites_analyse_contenu": ["<texte>", "..."],
      "recherches_effectuees": ["<résumé court>", "..."],
      "methode": {{
        "principe": "De Facto évalue un texte selon deux axes : FOND (justesse, complétude) et FORME (ton, sophismes).",
        "criteres": {{
          "fond": "Justesse (véracité, rigueur, vérification) et complétude (angles et voix absentes).",
          "forme": "Ton (neutralité ou orientation implicite) et sophismes (raisonnements biaisés)."
        }},
        "avertissement": "Analyse expérimentale — l’IA peut commettre des erreurs."
      }}
    }}

    ---

    ### 🧠 Directives détaillées pour chaque axe

    #### 🔹 Justesse
    - Vérifie les faits, dates, chiffres et citations avec les sources web.
    - Si des contradictions existent, mentionne-les clairement.
    - Reformule les écarts sans jugement moral (“inexact”, “erroné”), mais avec précision journalistique.
    - Exemple :  
      > « L’article évoque la nomination de Revel mais omet sa période à la CNAM, pourtant confirmée par Le Monde. »

    #### 🔹 Complétude
    - Repère les points de vue, réactions ou contextes absents du texte.
    - Utilise les données du web pour citer les éléments manquants.
    - Explique **en quoi ces absences modifient la perception** du lecteur.
    - Exemple :  
      > « Le texte ignore les critiques de l’opposition, ce qui donne l’impression d’un consensus. »

    #### 🔹 Ton
    - Analyse le choix des mots, adjectifs, formules, citations.
    - Détermine s’il existe une orientation implicite (valorisante, ironique, dramatique…).
    - Exemple :  
      > « L’expression “profil technique” véhicule une image valorisante et apaise la dimension politique. »

    #### 🔹 Sophismes
    - Évalue la rigueur du raisonnement.
    - Décris s’il y a des généralisations abusives, corrélations hâtives ou simplifications.
    - Si le texte est solide, écris-le aussi clairement.
    - Exemple :  
      > « L’auteur confond corrélation et causalité en reliant la popularité au seul changement de Premier ministre. »

    Chaque justification doit contenir **2 à 3 phrases denses**, avec au moins un exemple concret ou citation courte du texte.

    ---

    ### 📰 Synthèse finale (commentaire + résumé)
    - Le **commentaire** (2 phrases) donne le **verdict clair et journalistique**.  
      > “Globalement crédible mais partiel : l’article informe correctement mais néglige certains aspects clés.”
    - Le **résumé** (3 à 6 phrases) raconte l’histoire du texte :
      - Ce que le texte dit,  
      - Ce qu’il omet,  
      - Ce que d’autres sources révèlent,  
      - Ce que cela change dans la perception du lecteur.

    Le ton doit être fluide, professionnel et engageant — comme une courte chronique de médiation de l’info.

    ---

    ### 🌍 Compléments factuels issus du Web
    Voici les informations disponibles issues de la recherche contextuelle :
    {json.dumps(web_info, ensure_ascii=False, indent=2)}

    Utilise ces données pour :
    - confirmer ou nuancer la justesse,
    - identifier les faits manquants ou points de vue opposés,
    - renforcer la crédibilité de ton analyse.

    ---

    ### ⚔️ Instructions finales
    1. Structure ta réponse uniquement en JSON (pas de texte libre autour).
    2. Appuie-toi sur les éléments concrets du texte et des sources web.
    3. Évite les formulations vagues (“le texte manque de détails”).
    4. Ta mission est de **révéler ce que le lecteur n’avait pas perçu** — le rendre plus lucide.

    ---

    ### 🧾 Texte à analyser :
    {text}
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

        # 🔍 Intégration narrative du contexte web
        commentaire_web = formate_commentaires_web(web_info)
        if "commentaire" in result and isinstance(result["commentaire"], str):
            result["commentaire"] += " " + commentaire_web
        else:
            result["commentaire"] = commentaire_web

        # Bonus : renforce le résumé avec la synthèse web si disponible
        if web_info.get("synthese"):
            if "resume" in result and isinstance(result["resume"], str):
                result["resume"] += " " + web_info["synthese"]
            else:
                result["resume"] = web_info["synthese"]

        
        print("🧠 Synthèse web contextuelle :", json.dumps(web_info, ensure_ascii=False, indent=2))
        
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
