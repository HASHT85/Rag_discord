FROM python:3.12-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier et installer les dépendances en premier (cache Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY . .

# Lancer le bot
CMD ["python", "bot.py"]
