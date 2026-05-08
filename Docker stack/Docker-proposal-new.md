# Docker Stack: Production-Oriented Runtime for the Current App

## Purpose

This `Docker stack` folder now contains a production-oriented Docker setup for the **current Flask application**.

It upgrades the runtime from the earlier transitional SQLite-based container setup to a stack that uses:

- `Caddy`
- the current `Flask` app under `Gunicorn`
- `MariaDB`
- persistent upload storage
- external `Ollama`
- `ffprobe`-based media duration validation

This is the correct next step for running the **current app codebase** with a production-grade relational database rather than SQLite.

## Implemented Architecture

```text
Browser
  -> Caddy
    -> Flask app container
         -> MariaDB
         -> persistent uploads volume
         -> external Ollama endpoint
         -> faster-whisper + ffprobe inside the app container
```

## What Changed

The current app now supports both:

- SQLite for local fallback
- MariaDB through `DATABASE_URL`

The production Docker stack uses **MariaDB by default**.

This required two categories of change:

1. the Flask app database layer was updated so the existing code can talk to MariaDB
2. the Docker stack was updated to run a MariaDB container and configure the app to use it

## Containers in This Stack

### `caddy`

Responsibilities:

- listens on `80` and optionally `443`
- reverse proxies all traffic to the Flask app
- keeps the browser on a single origin
- provides basic security headers

### `app`

Responsibilities:

- serves the current frontend from Flask
- handles auth, admin, uploads, submission history, and media access
- validates duration using `ffprobe`
- runs `faster-whisper`
- calls Ollama through `OLLAMA_URL`
- reads and writes data in MariaDB
- stores uploaded media in a persistent Docker volume

### `mariadb`

Responsibilities:

- stores users
- stores submissions
- provides a production-grade relational persistence layer for the current app

## Database Model

The current app still manages schema directly at startup rather than using Alembic or a migration framework.

That means:

- on startup, the Flask app creates tables if they do not already exist
- the app also applies lightweight column-add migrations for the `submissions` table

For MariaDB, the current schema now includes:

### `users`

- `user_id` `VARCHAR(36)` primary key
- `username` unique
- `password_hash`
- `cohort_id`
- `is_admin`
- `created_at`

### `submissions`

- `submission_id` `VARCHAR(36)` primary key
- `user_id` foreign key
- `original_filename`
- `stored_filename`
- `duration_seconds`
- `submission_source`
- `transcript`
- `feedback`
- `submitted_at`

## Runtime Configuration

Environment variables used by the production Docker stack:

- `PORT`
  - internal Flask bind port
  - default: `8080`
- `SECRET_KEY`
  - Flask session secret
- `ALLOWED_ORIGINS`
  - comma-separated allowed origins for Flask CORS
- `DATABASE_URL`
  - MariaDB connection URL
  - default:
    - `mariadb://app_user:app_password@mariadb:3306/av_evaluation`
- `UPLOADS_DIR`
  - persistent path for uploaded media inside the app container
  - default: `/data/uploads`
- `OLLAMA_URL`
  - full Ollama generate endpoint
- `OLLAMA_MODEL`
- `WHISPER_MODEL_SIZE`
- `WHISPER_DEVICE`
- `WHISPER_COMPUTE_TYPE`
- `APP_WORKERS`
  - Gunicorn worker count
- `APP_THREADS`
  - Gunicorn thread count
- `MARIADB_DATABASE`
- `MARIADB_USER`
- `MARIADB_PASSWORD`
- `MARIADB_ROOT_PASSWORD`
- `CADDY_SITE_ADDRESS`
- `CADDY_EMAIL`

## Volumes

The stack now uses:

- `mariadb_data`
  - MariaDB data directory
- `uploads_data`
  - uploaded media files
- `caddy_data`
- `caddy_config`

This replaces the earlier single SQLite-oriented app volume.

## Ollama Connectivity

This stack still expects **external Ollama**.

Use one of these approaches:

1. point `OLLAMA_URL` at a remote Ollama server
2. run Ollama on the Docker host and use `host.docker.internal`

The app container includes:

```text
host.docker.internal:host-gateway
```

so a host-based Ollama instance can be reached from Linux Docker.

## Current App Boot Path in Docker

This stack uses:

- `backend/docker_wsgi.py`

It loads `backend/app.py` explicitly by file path and exposes a WSGI `app` object for Gunicorn. That keeps the production entrypoint explicit and decoupled from local development helpers.

The app entrypoint:

- creates upload directories if needed
- starts Gunicorn
- serves the Flask app on port `8080`

## How to Run

From inside the `Docker stack` folder:

```bash
docker compose --env-file .env.production.example -f docker-compose.prod.yml up --build
```

The app will then be available at:

- `http://localhost`

## First Configuration Pass

Before running, update at least:

- `SECRET_KEY`
- `DATABASE_URL` if you want different DB credentials or hostnames
- `MARIADB_PASSWORD`
- `MARIADB_ROOT_PASSWORD`
- `OLLAMA_URL`
- `OLLAMA_MODEL`

Example:

```text
DATABASE_URL=mariadb://app_user:strong-password@mariadb:3306/av_evaluation
OLLAMA_URL=http://131.111.168.123:11434/api/generate
```

## Current Operational Shape

This stack is now stronger than the earlier SQLite-based runtime because it uses:

- MariaDB instead of SQLite
- a separate DB container
- persistent uploads separate from DB state
- a real reverse proxy in front of Gunicorn

However, the app still has these current-codebase limitations:

- synchronous request handling for transcription and feedback
- no background queue
- no worker container
- no object storage
- no horizontal scaling strategy for long-running inference

So this stack is a **production-oriented upgrade for the current app**, but not yet the final long-term architecture.

## Future Refactor Target

If the app is later refactored more deeply, the next major architecture would still be:

- `caddy`
- `api`
- `worker`
- `postgres` or `mariadb`
- optionally `redis`
- external inference provider

That would replace:

- synchronous transcription/feedback inside the web request
- direct inline processing in the Flask app

## Summary

The `Docker stack` folder now supports a more production-ready deployment of the **current Flask app** with:

- Caddy
- Gunicorn
- Flask
- MariaDB
- persistent uploads
- external Ollama
- `ffprobe`-based duration validation

It is the correct production-oriented runtime for the current application without requiring the larger FastAPI/worker rewrite first.
