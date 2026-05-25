# 🤖 Discord RAG Bot

Bot Discord intelligent qui indexe des documents et répond aux questions en se basant sur le contenu indexé, grâce au RAG (Retrieval-Augmented Generation).

## 🛠️ Stack Technique

| Composant | Technologie |
|-----------|-------------|
| Bot | discord.py v2.x |
| LLM | OpenRouter (google/gemini-3.1-flash-lite) |
| Embeddings | Gemini Embedding 2 Preview |
| Vector Store | ChromaDB (local) |
| PDF | PyMuPDF |
| Déploiement | Docker Compose |

## 🚀 Déploiement (VPS avec Docker)

### 1. Cloner le repo
```bash
git clone https://github.com/VOTRE_USER/Rag_discord.git
cd Rag_discord
```

### 2. Configurer les variables d'environnement
```bash
cp .env.example .env
nano .env
```
Remplissez les valeurs :
- `DISCORD_TOKEN` — Token du bot Discord
- `OPENROUTER_API_KEY` — Clé API OpenRouter

### 3. Configurer le bot Discord
1. Allez sur [Discord Developer Portal](https://discord.com/developers/applications)
2. Créez une application et un bot
3. Activez les **Privileged Gateway Intents** :
   - ✅ Message Content Intent
4. Invitez le bot avec ce lien (remplacez `CLIENT_ID`) :
   ```
   https://discord.com/oauth2/authorize?client_id=CLIENT_ID&permissions=277025770560&scope=bot%20applications.commands
   ```

### 4. Lancer avec Docker Compose
```bash
docker compose up -d --build
```

### Commandes utiles
```bash
# Voir les logs en temps réel
docker compose logs -f

# Redémarrer le bot
docker compose restart

# Arrêter le bot
docker compose down

# Reconstruire après mise à jour du code
docker compose up -d --build
```

---

## 📦 Installation locale (développement)

### 1. Créer un environnement virtuel
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate     # Windows
```

### 2. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 3. Configurer et lancer
```bash
cp .env.example .env
# Éditez .env avec vos clés
python bot.py
```

---

## 💬 Utilisation

### Configuration initiale
Dans Discord, utilisez la commande :
```
/setup input_channel:#données output_channel:#questions
```
Configure les deux canaux : un pour indexer des données, un pour poser des questions.

### Indexer des documents
Dans le canal d'entrée, envoyez des messages au format :
```
[Catégorie] Titre du document
Contenu du message...
```

**Exemples :**
```
[Documentation] Guide d'installation Docker
Pour installer Docker sur Ubuntu :
1. Mettre à jour les paquets
2. Installer les dépendances
3. Ajouter le dépôt Docker
```

```
[FAQ] Réinitialisation du mot de passe
Rendez-vous sur la page de connexion,
cliquez sur « Mot de passe oublié »
et suivez les instructions.
```

Vous pouvez aussi joindre des fichiers (PDF, .txt, .md, .py, etc.)

### Poser des questions
- **Commande slash** : `/ask question: Comment installer Docker ?`
- **Message libre** : Tapez directement votre question dans le canal de sortie

### Commandes
| Commande | Description | Permission |
|----------|-------------|------------|
| `/setup` | Configurer les canaux d'entrée/sortie | Gérer le serveur |
| `/status` | Voir l'état du bot | Gérer le serveur |
| `/reindex` | Ré-indexer l'historique d'un canal | Gérer le serveur |
| `/help_format` | Guide du format d'indexation | Aucune |
| `/ask` | Poser une question au bot | Aucune |

## 📁 Structure du projet
```
Rag_discord/
├── bot.py                  # Point d'entrée principal
├── config.py               # Configuration centralisée
├── Dockerfile              # Image Docker
├── docker-compose.yml      # Orchestration Docker
├── cogs/
│   ├── indexer.py          # Indexation temps réel
│   ├── rag.py              # Commande /ask et pipeline RAG
│   └── admin.py            # Commandes d'administration
├── services/
│   ├── openrouter_client.py # Client OpenRouter (LLM + Embeddings)
│   ├── vectorstore.py      # Gestion ChromaDB
│   ├── chunker.py          # Parsing et découpage des messages
│   └── attachments.py      # Extraction de texte des pièces jointes
├── .env.example            # Template de configuration
├── requirements.txt
└── README.md
```

## 📄 Licence

MIT
