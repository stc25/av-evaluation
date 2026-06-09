#!/bin/sh
set -eu

PORT="${PORT:-8080}"
APP_DB_PATH="${APP_DB_PATH:-/data/app.db}"
UPLOADS_DIR="${UPLOADS_DIR:-/data/uploads}"
APP_WORKERS="${APP_WORKERS:-2}"
APP_THREADS="${APP_THREADS:-4}"
APP_DEBUG="${APP_DEBUG:-false}"
APP_LOG_LEVEL="${APP_LOG_LEVEL:-INFO}"
GUNICORN_LOG_LEVEL="${GUNICORN_LOG_LEVEL:-info}"

mkdir -p "$(dirname "${APP_DB_PATH}")" "${UPLOADS_DIR}"

exec gunicorn \
  --bind "0.0.0.0:${PORT}" \
  --workers "${APP_WORKERS}" \
  --threads "${APP_THREADS}" \
  --timeout 600 \
  --log-level "${GUNICORN_LOG_LEVEL}" \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  --env "APP_DEBUG=${APP_DEBUG}" \
  --env "APP_LOG_LEVEL=${APP_LOG_LEVEL}" \
  docker_wsgi:app
