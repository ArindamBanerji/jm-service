FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy engine + service
COPY jm_core.py jm_service.py ./

# SQLite data will be stored in a volume
VOLUME /app/data
ENV JM_DB_PATH=/app/data/jm_tenants.db

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/v1/health')" || exit 1

CMD ["uvicorn", "jm_service:app", "--host", "0.0.0.0", "--port", "8100"]
