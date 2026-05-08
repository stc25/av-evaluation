#!/bin/sh
set -eu

PORT="${PORT:-8080}"
APP_DB_PATH="${APP_DB_PATH:-/data/app.db}"
UPLOADS_DIR="${UPLOADS_DIR:-/data/uploads}"
APP_WORKERS="${APP_WORKERS:-2}"
APP_THREADS="${APP_THREADS:-4}"

mkdir -p "$(dirname "${APP_DB_PATH}")" "${UPLOADS_DIR}"

exec gunicorn \
  --bind "0.0.0.0:${PORT}" \
  --workers "${APP_WORKERS}" \
  --threads "${APP_THREADS}" \
  --timeout 600 \
  docker_wsgi:app
