# ─────────────────────────────────────────────────────────────
# ALARM SERVER — Docker Image
# ─────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Dossier de travail
WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copier requirements et installer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY app/ ./app/

# Créer le dossier data pour SQLite
RUN mkdir -p /app/data

# Port exposé
EXPOSE 8080

# Variables d'environnement par défaut
ENV PORT=8080
ENV JWT_SECRET_KEY=change-me-in-production
ENV TOKEN_EXPIRE_MINUTES=60

# Lancement
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
