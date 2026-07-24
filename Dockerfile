FROM python:3.12-slim

WORKDIR /app

# Installer git et dépendances système si besoin
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*

# Copier et installer les dépendances en premier (cache Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY . .

# Lancer le bot
CMD ["python", "bot.py"]
