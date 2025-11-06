import importlib.util, sys, json, re, os
from openai import OpenAI

# Charger ton module principal sans lancer Flask
spec = importlib.util.spec_from_file_location("server", "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules["server"] = server
spec.loader.exec_module(server)
print("✅ Module chargé")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

text = "Emmanuel Macron a annoncé un plan économique en 2025 pour soutenir l’industrie française."

# --- Étape 1 : extraction d'entités
ent_prompt = f"""
Extrait les principales entités nommées (personnes, lieux, organisations, événements, lois, chiffres clés)
du texte suivant :
{text}

Réponds uniquement en JSON : ["entité1", "entité2", ...]
"""
ent_resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "Tu es un extracteur d'entités journalistiques."},
        {"role": "user", "content": ent_prompt}
    ],
    temperature=0
)
raw_entities = ent_resp.choices[0].message.content.strip()
try:
    entities = json.loads(raw_entities)
except Exception:
    m = re.search(r"\[.*\]", raw_entities, re.DOTALL)
    entities = json.loads(m.group(0)) if m else []

print("🔎 Entités détectées :", entities)

# --- Étape 2 : recherche web
recherches = server.search_web_results(entities, per_query=2)
print(f"🌍 {len(recherches)} ensembles de résultats collectés")

# --- Étape 3 : synthèse factuelle avec GPT-4o
synth_prompt = f"""
Compare le texte suivant :
{text}

Avec ces résultats de recherche fiables :
{json.dumps(recherches, ensure_ascii=False, indent=2)}

Réponds STRICTEMENT en JSON :
{{
  "faits_manquants": [{{"texte": "<fait ajouté>", "source": "<média>", "url": "<url ou null>"}}],
  "contradictions": ["<phrase>", "..."],
  "impact": "<faible|moyen|fort>",
  "fiabilite_sources": "<phrase courte>",
  "synthese": "<2 phrases de résumé>"
}}
"""

synth_resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "Tu es un fact-checker journalistique neutre et précis."},
        {"role": "user", "content": synth_prompt}
    ],
    temperature=0.3
)

print("\n🧠 Synthèse générée :")
print(synth_resp.choices[0].message.content)
