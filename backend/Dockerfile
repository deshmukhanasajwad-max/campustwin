FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev curl postgresql postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY frontend ./frontend
COPY data ./data
COPY backend/start.sh ./start.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Starts an embedded PostgreSQL when DATABASE_URL is unset; honours $PORT (Render).
CMD ["sh", "/app/start.sh"]
