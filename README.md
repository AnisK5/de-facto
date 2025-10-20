# 🧠 De Facto – Baromètre de Fiabilité

**De Facto** (ou *Rationality Barometer*) est une application web d’analyse argumentative.  
Elle évalue la **rigueur**, la **neutralité** et la **qualité logique** d’un texte (article, post, thread, etc.),  
afin de promouvoir un discours public plus rationnel et nuancé.

---

## 🎯 Mission

De Facto n’évalue pas un média ou un auteur,  
mais la **fiabilité intrinsèque du contenu** :

- **Justesse** → solidité des faits et cohérence logique  
- **Complétude** → pluralité des points de vue, contextualisation  
- **Ton** → neutralité lexicale, absence de charge émotionnelle  
- **Sophismes** → détection d’erreurs de raisonnement

> Objectif : rendre la pensée critique accessible, visuelle et partageable.

---

## ⚙️ Architecture technique

**Backend**
- Framework : Flask (Python)
- Modèle IA : OpenAI GPT-4o-mini
- Hébergement : Render (prod) / Replit (dev)
- Fichier principal : `backend/server.py`
- Routes :
  - `/analyze` → API d’analyse
  - `/frontend` → interface web servie directement

**Frontend**
- Technologies : HTML / CSS / JavaScript pur
- Interface : score global + sous-scores + citations
- Design : rapide, transparent, orienté partage

---

## 📁 Structure du projet
de-facto/
├── backend/
│ ├── server.py # Backend Flask (analyse IA)
│ ├── requirements.txt # Dépendances Python
│ └── contexte.mp # Source méthodologique du projet
├── frontend/
│ ├── index.html # Interface utilisateur
│ ├── script.js # Logique client (requêtes / affichage)
│ └── style.css # Styles et couleurs
├── .replit # Configuration Replit (dev rapide)
└── README.md


---

## 🚀 Lancer le projet

### En local

```bash
# Installation
cd backend
pip install -r requirements.txt

# Lancement du serveur
python3 server.py
