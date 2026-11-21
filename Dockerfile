FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
       libgobject-2.0-0 libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application and migration packages
COPY *.py ./
COPY label_health/ label_health/
COPY db/ db/
COPY frontend/dist/ frontend/dist/
COPY docker-entrypoint.sh ./
RUN mkdir -p /data && chmod +x docker-entrypoint.sh

# SQLite data will be stored in a volume
VOLUME /data
ENV JM_DB_PATH=/data/jm_tenants.db
ENV LS_CONFIG_PATH=/data/ls_config.json

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:' + os.getenv('PORT', '8000') + '/v1/health')" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
