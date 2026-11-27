#!/bin/sh
set -eu

python -c "from jm_service import validate_production_config; validate_production_config()"

MAX_RETRIES=5
RETRY=0
until python -c "from db.migrate import run_migration; run_migration()"; do
  RETRY=$((RETRY + 1))
  if [ "$RETRY" -ge "$MAX_RETRIES" ]; then
    echo "Migration failed after $MAX_RETRIES attempts" >&2
    exit 1
  fi
  echo "Migration attempt $RETRY failed, retrying in 2s..." >&2
  sleep 2
done
echo "Migration complete"
exec uvicorn jm_service:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log
