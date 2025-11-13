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
# 🧩 PIPELINE EXPÉRIMENTAL — version structurée et robuste
# ======================================================

def extract_global_message(client, text):
    """Étape 0 — Analyse le message global et l’impression que retient un lecteur moyen."""
    prompt = f"""
    Lis ce texte comme le ferait un lecteur moyen (non expert).
    Décris :
    1️⃣ Ce que le lecteur retient (message global implicite ou explicite)
    2️⃣ Le ton général (neutre, élogieux, alarmiste, ironique, critique…)
    3️⃣ L’intention perçue (informer, convaincre, valoriser, critiquer, désamorcer, dramatiser…)
    4️⃣ Le niveau de confiance perçu (fort, moyen, faible)
    5️⃣ L’impression émotionnelle laissée (apaisante, persuasive, tendue…)

    Réponds uniquement en JSON :
    {{
      "message_global": "<ce qu’un lecteur retient>",
      "ton_general": "<neutre|positif|critique|alarmiste|ironique|élogieux>",
      "intention_perçue": "<informer|convaincre|valoriser|critiquer|désamorcer|dramatiser>",
      "niveau_de_confiance": "<fort|moyen|faible>",
      "resume_emotionnel": "<description brève>"
    }}

    Texte :
    {text[:4000]}
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un analyste cognitif spécialisé dans la réception médiatique. Tu décris ce que le lecteur moyen retient d’un texte."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.35
        )
        raw = resp.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group(0)) if m else {}
    except Exception as e:
        print("⚠️ extract_global_message error:", e)
        return {}


def summarize_text(client, text):
    """Étape 1 — Résume le texte et sépare faits / opinions avec ancrage (citations courtes)."""
    prompt = f"""
    Résume le texte suivant de manière neutre, puis liste :
    - Les faits (affirmations vérifiables),
    - Les opinions (jugements, interprétations).

    Pour chaque fait, joins un court extrait du texte (≤15 mots) pour ancrer la preuve.

    Réponds **uniquement** en JSON :
    {{
      "resume": "<résumé général>",
      "faits": [{{"texte": "<fait>", "extrait_article": "<citation courte>"}}],
      "opinions": ["<opinion>", ...]
    }}

    Texte :
    {text[:4000]}
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un journaliste neutre. Sépare faits et opinions avec extraits précis."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        raw = resp.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(match.group(0)) if match else {"resume": "", "faits": [], "opinions": []}
    except Exception as e:
        print("⚠️ summarize_text error:", e)
        return {"resume": "", "faits": [], "opinions": []}


def consolidate_web_facts(client, web_hits):
    """Étape 2 — Transforme les résultats web en faits vérifiables (avec extrait source)."""
    prompt = f"""
    À partir de ces extraits web, liste uniquement les faits vérifiables et neutres (événements, chiffres, décisions, citations importantes).
    Pour chaque fait, donne la source et un court extrait (≤15 mots).

    Réponds en JSON :
    {{
      "faits_web": [{{"fait": "...", "source": "...", "url": "...", "extrait_source": "..."}}]
    }}

    Extraits web :
    {json.dumps(web_hits, ensure_ascii=False, indent=2)}
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es un fact-checker. Tu identifies uniquement les faits neutres et sourcés."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        raw = resp.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(match.group(0)) if match else {"faits_web": []}
    except Exception as e:
        print("⚠️ consolidate_web_facts error:", e)
        return {"faits_web": []}


def compare_text_with_web(client, summary, web_facts):
    """Étape 3 — Compare le texte et les faits web : omissions, contradictions, cadrages."""
    prompt = f"""
    Compare les faits du texte avec ceux des sources web.
    Identifie :
    - les faits manquants (éléments absents du texte mais confirmés ailleurs),
    - les contradictions (texte vs sources),
    - les divergences de cadrage (différences d’angle narratif).

    Pour chaque entrée, donne un extrait du texte et un extrait de source pour appuyer l’analyse.

    Réponds uniquement en JSON :
    {{
      "faits_manquants": [{{"manque": "...", "pourquoi_cela_compte": "...", "source": "...", "url": "...", "extrait_source": "..."}}],
      "contradictions": [{{"affirmation_du_texte": "...", "contrepoint": "...", "source": "...", "url": "...", "extrait_source": "..."}}],
      "divergences_de_cadrage": [{{"resume": "...", "impact": "..."}}],
      "impact": "<faible|moyen|fort>"
    }}

    FAITS DU TEXTE :
    {json.dumps(summary, ensure_ascii=False, indent=2)}

    FAITS DU WEB :
    {json.dumps(web_facts, ensure_ascii=False, indent=2)}
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Tu es un analyste comparatif entre texte et sources web."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        raw = resp.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(match.group(0)) if match else {"faits_manquants": [], "contradictions": [], "divergences_de_cadrage": [], "impact": "faible"}
    except Exception as e:
        print("⚠️ compare_text_with_web error:", e)
        return {"faits_manquants": [], "contradictions": [], "divergences_de_cadrage": [], "impact": "faible"}


def evaluate_text(client, summary, web_facts, diffs, global_msg=None):
    """
    Étape 4 — Évalue le texte sur 4 axes avec pédagogie.
    Chaque sous-score est concret, illustré et explique l’effet sur le lecteur.
    """
    msg_context = (global_msg or {}).get("message_global", "")

    rubric = {
    "justesse": {
        "0":   "Affirmations fausses ou trompeuses.",
        "25":  "Plusieurs imprécisions notables.",
        "50":  "Faits globalement exacts mais simplifiés.",
        "75":  "Faits exacts, rares imprécisions mineures.",
        "100": "Faits parfaitement justes et sourcés."
    },
    "completude": {
        "0":   "Omissions critiques changeant complètement le sens.",
        "25":  "Omissions majeures qui biaisent fortement la compréhension.",
        "50":  "Certains points manquent et orientent partiellement la lecture.",
        "75":  "Informations bien couvertes, quelques absences secondaires.",
        "100": "Texte très complet, équilibre des points de vue."
    },
    "ton": {
        "0":   "Langage clairement orienté ou affectif.",
        "25":  "Vocabulaire influençant la perception du lecteur.",
        "50":  "Ton neutre mais légères orientations lexicales.",
        "75":  "Ton factuel et mesuré.",
        "100": "Neutralité exemplaire, vocabulaire sobre."
    },
    "sophismes": {
        "0":   "Raisonnement illogique ou manipulateur.",
        "25":  "Causalités fausses ou raccourcis notables.",
        "50":  "Quelques simplifications qui altèrent la rigueur.",
        "75":  "Raisonnement globalement solide.",
        "100": "Logique rigoureuse, distinctions claires entre faits et interprétations."
    }
    }

    prompt = f"""
    Tu es **De Facto**, un journaliste-analyste pédagogue.
    Pour chaque axe, tu dois écrire comme si tu expliquais ton évaluation à un lecteur non expert.
    Chaque sous-note doit répondre à trois questions :
      1️⃣ Qu’est-ce que le texte dit ou montre ? (observation concrète)
      2️⃣ Peux-tu donner un exemple précis du texte ?
      3️⃣ Qu’est-ce que ça fait au lecteur ? (effet sur sa compréhension ou perception)

    ⚙️ Structure attendue pour chaque axe :
    {{
      "note": <0|25|50|75|100>,
      "anchor_matched": <0|25|50|75|100>,
      "severity_for_reader": "<faible|moyenne|élevée>",
      "justification": "Rédaction pédagogique expliquant le constat + exemple + effet sur le lecteur.",
      "citation": "Extrait court illustratif."
    }}

    ⚖️ Barème utilisé :
    {json.dumps(rubric, ensure_ascii=False, indent=2)}

    Contexte perçu par le lecteur : "{msg_context}"

    Matières disponibles :
    - Résumé et faits du texte : {json.dumps(summary, ensure_ascii=False, indent=2)}
    - Faits web : {json.dumps(web_facts, ensure_ascii=False, indent=2)}
    - Écarts détectés : {json.dumps(diffs, ensure_ascii=False, indent=2)}

    ⚠️ Règles :
    - Sois concret, clair et explicatif.
    - Ne dis pas “le texte est biaisé” mais “le texte donne l’impression que…”.
    - Donne toujours un exemple de formulation ou d’extrait.
    - Explique à chaque fois pourquoi cela compte pour le lecteur.
    - Évite le jargon et les phrases vagues (“le contexte est tendu” sans exemple).
    - Réponds uniquement en JSON, avec la structure :
      {{
    "axes": {{
      "fond": {{
        "justesse": {{...}},
        "completude": {{...}}
      }},
      "forme": {{
        "ton": {{...}},
        "sophismes": {{...}}
      }}
    }}
      }}
    """

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                "role": "system",
                "content": (
                    "Tu es un journaliste-analyste pédagogique, clair et concret. "
                    "Tu illustres chaque constat avec un exemple et expliques son impact sur le lecteur."
                )
            },
                {"role": "user", "content": prompt}
        ],
            temperature=0.25
        )
        raw = resp.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {"axes": {}}
        return parsed
    except Exception as e:
        print("⚠️ evaluate_text error:", e)
        return {"axes": {}}



def synthesize_from_axes(client, evaluation):
    """
    Synthèse explicative et pédagogique (3 blocs). N'indique jamais de score.
    """
    prompt = f"""
    Tu es un journaliste pédagogue. Explique au lecteur non expert, clairement et avec exemples,
    ce qu’il retient du texte, ce qui manque, et l’effet global sur sa compréhension.
    
    ✍️ Structure OBLIGATOIRE (3 blocs, 2-4 phrases chacun) :
    1) Ce que le texte dit et fait croire (message retenu + ton + comment c'est amené).
       Exemple: « L’article présente X comme un choix 'technique' et neutre; le lecteur retient l’idée d’efficacité. »
    
    2) Ce qui manque / est simplifié, et pourquoi ça compte (exemples concrets + effet sur ce que croit le lecteur).
       Exemple: « Le texte ne mentionne pas [critique/contre-exemple]. Sans cela, le lecteur pense à un consensus. »
    
    3) Effet global sur la compréhension (perception induite et limites).
       Exemple: « En insistant sur [élément] et en évitant [contrepoint], l’article donne une impression de stabilité, mais gomme les enjeux politiques. »
    
    ⚠️ Interdits:
    - NE JAMAIS mentionner de chiffres de note ou de score.
    - Pas de jargon. Pas d’abstractions vagues (« contexte tendu ») sans exemple.
    
    Matière:
    {json.dumps(evaluation, ensure_ascii=False, indent=2)}
    """

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Tu écris comme un journaliste-explicateur: clair, concret, avec exemples. Jamais de score."},
                {"role": "user", "content": prompt}
        ],
            temperature=0.35
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("⚠️ synthesize_from_axes error:", e)
        return "Synthèse non disponible."



def compute_global_score(evals_axes, diffs_impact: str, densite_faits: int) -> int:
    """
    Calcule un score global déterministe à partir des notes par axe.
    Pondérations: Justesse 0.4, Complétude 0.3, Ton 0.15, Sophismes 0.15.
    Ajustements:
      - Impact 'fort' : -10 si Justesse < 60 ou Complétude < 60
      - Impact 'moyen': -5  si Justesse < 60 ou Complétude < 60
      - Densité factuelle: +5 si >60 ; -5 si <30
    Renvoie un entier 0–100.
    """
    try:
        j = int(evals_axes["fond"]["justesse"]["note"])
        c = int(evals_axes["fond"]["completude"]["note"])
        t = int(evals_axes["forme"]["ton"]["note"])
        s = int(evals_axes["forme"]["sophismes"]["note"])
    except Exception:
        return 50  # fallback sûr

    base = (0.4 * j) + (0.3 * c) + (0.15 * t) + (0.15 * s)

    # Impact du manque sur compréhension
    impact = (diffs_impact or "faible").lower().strip()
    if (j < 60 or c < 60):
        if impact == "fort":
            base -= 10
        elif impact == "moyen":
            base -= 5

    # Densité factuelle (ton ancien réglage, mais ici centralisé)
    if densite_faits > 60:
        base += 5
    elif densite_faits < 30:
        base -= 5

    return max(0, min(100, round(base)))

# ======================================================
# 🌍 Recherche Web contextuelle (externe à analyze)
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
        # 1️⃣ Extraction d'entités
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
        m = re.search(r"\[.*\]", raw_entities, re.DOTALL)
        entities = json.loads(m.group(0)) if m else []
        entities = [e for e in entities if isinstance(e, str) and e.strip()]

        if not entities:
            return {
                "recherches_effectuees": [],
                "faits_manquants": [],
                "contradictions": [],
                "divergences_de_cadrage": [],
                "impact": "faible",
                "fiabilite_sources": "Aucune source consultable (pas d'entités détectées).",
                "synthese": "Aucune entité détectée — enrichissement impossible."
            }

        # 2️⃣ Recherche web
        queries = []
        for ent in entities[:5]:
            queries += [f"{ent} actualité", f"{ent} controverse", f"{ent} critiques"]
        print("🌍 Recherche web sur :", entities)
        recherches = search_web_results(queries, per_query=4)

        # 3️⃣ Synthèse IA
        synth_prompt = f"""
        Compare le texte suivant avec les sources ci-dessous :
        - Identifie les faits manquants, contradictions et divergences de cadrage.
        Réponds uniquement en JSON :
        {{
          "faits_manquants": [{{"description": "...", "source": "...", "url": "..."}}],
          "contradictions": [{{"affirmation_du_texte": "...", "correction_ou_nuance": "...", "source": "...", "url": "..."}}],
          "divergences_de_cadrage": [{{"resume": "...", "impact": "..."}}],
          "impact": "<faible|moyen|fort>",
          "fiabilite_sources": "<description>",
          "synthese": "<résumé journalistique clair>"
        }}

        TEXTE :
        {text}

        SOURCES :
        {json.dumps(recherches, ensure_ascii=False, indent=2)}
        """
        synth_resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Tu es un fact-checker journalistique neutre et explicatif."},
                {"role": "user", "content": synth_prompt}
            ],
            temperature=0.3
        )
        content = synth_resp.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", content, re.DOTALL)
        result = json.loads(m.group(0)) if m else {}
        result["recherches_effectuees"] = recherches
        return result

    except Exception as e:
        print("⚠️ web_context_research failed:", e)
        return {
            "recherches_effectuees": [],
            "faits_manquants": [],
            "contradictions": [],
            "divergences_de_cadrage": [],
            "impact": "faible",
            "fiabilite_sources": "Recherche contextuelle non disponible.",
            "synthese": "Recherche contextuelle non disponible."
        }


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
    # ======================================================
    # 🧠 Étape 3 — Nouveau pipeline structuré (analyse complète)
    # ======================================================

    try:
        signal.alarm(60)

        # --- Étape 0 : Message global perçu par le lecteur
        global_msg = extract_global_message(client, text)

        # --- Étape 1 : Résumé explicatif et extraction d’affirmations vérifiables
        summary = summarize_text(client, text)


        # --- Étape 2 : Recherche Web (sur entités principales)
        entities = [f["texte"] for f in summary.get("faits", [])[:3]] if summary.get("faits") else []
        web_hits = search_web_results(entities)

        # --- Étape 3 : Consolidation des faits trouvés
        web_facts = consolidate_web_facts(client, web_hits)

        # --- Étape 4 : Comparaison entre le texte et le web
        diffs = compare_text_with_web(client, summary, web_facts)

        # --- Pondération intelligente de l’impact selon le message perçu
        if global_msg and "message_global" in global_msg:
            mg = global_msg["message_global"].lower()
            if "consensus" in mg or "apaisé" in mg or "unanimité" in mg:
                if len(diffs.get("faits_manquants", [])) > 0:
                    diffs["impact"] = "fort"
            elif "controverse" in mg or "division" in mg or "critique" in mg:
                diffs["impact"] = "moyen"

        
        # --- Étape 5 : Évaluation finale (notes sur 4 axes)
        evals = evaluate_text(client, summary, web_facts, diffs, global_msg)

        # Calcul du score global séparé et déterministe
        try:
            axes_struct = evals.get("axes", {})
            final_score = compute_global_score(axes_struct, diffs.get("impact"), densite_faits)
        except Exception:
            final_score = 50

        # Remplir les champs de sortie normalisés
        evals["score_global"] = final_score
        evals["couleur_global"] = color_for(final_score)


        # --- Étape 6 : Synthèse finale à partir des sous-notes
        evals["resume"] = synthesize_from_axes(client, evals)

        # --- Ajouts pour compatibilité avec l’ancien front
        evals["message_global"] = global_msg
        evals["recherches_effectuees"] = web_hits
        evals["faits_web"] = web_facts
        evals["diffs"] = diffs
        evals["type_texte"] = type_texte
        evals["densite_faits"] = densite_faits
        evals["web_context"] = web_info
        evals["commentaire_web"] = formate_commentaires_web(web_info)


        # --- Pondération douce du score global selon densité factuelle
        if "score_global" in evals:
            sg = int(evals["score_global"])
            if densite_faits > 60:
                sg = min(sg + 5, 100)
            elif densite_faits < 30:
                sg = max(sg - 5, 0)
            evals["score_global"] = sg
            evals["couleur_global"] = color_for(sg)

        # --- Ajout du log local (comme avant)
        try:
            log_item = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "input_len": len(text),
                "type_texte": type_texte,
                "densite_faits": densite_faits,
                "score_global": evals.get("score_global"),
                "axes": evals.get("axes", {}),
                "resume": evals.get("resume"),
                "commentaire": evals.get("commentaire"),
            }
            with open("logs.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_item, ensure_ascii=False) + "\n")
        except Exception as e:
            print("ℹ️ Échec écriture logs.jsonl :", e)

        signal.alarm(0)
        print("✅ Pipeline terminé.")
        return jsonify(evals)

    except TimeoutError:
        return jsonify({"error": "Analyse trop longue (timeout)."}), 500
    except Exception as e:
        print("❌ Erreur pipeline :", e)
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
