FROM python:3.11-slim

WORKDIR /app

# Install system deps for TgCrypto
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persist the SQLite DB between restarts when using Docker volumes
VOLUME ["/app/data"]
ENV DB_PATH=/app/data/ott_bot.db

EXPOSE 8080

CMD ["python", "-u", "bot.py"]
