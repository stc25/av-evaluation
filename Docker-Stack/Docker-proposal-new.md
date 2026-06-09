# Docker-Stack: Production-Oriented Runtime for the Current App

## Purpose

This `Docker-Stack` folder now contains a production-oriented Docker setup for the **current Flask application**.

It upgrades the runtime from the earlier transitional SQLite-based container setup to a stack that uses:

- `Caddy`
- the current `Flask` app under `Gunicorn`
- `MariaDB`
- `Valkey`
- one background `worker`
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
         -> Valkey
         -> persistent uploads volume
         -> remote Ollama endpoint
         -> faster-whisper + ffprobe inside the app container
    -> worker container
         -> MariaDB
         -> Valkey
         -> persistent uploads volume
         -> remote Ollama endpoint
         -> faster-whisper + ffprobe inside the app container
```

The Python application runtime is fully containerized. It does not rely on host Python, host virtual environments, or host-installed FFmpeg.

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
- stores submissions immediately with queued/processing/completed/failed status
- reads and writes data in MariaDB
- stores uploaded media in a persistent Docker volume

### `worker`

Responsibilities:

- consumes queued submission jobs
- runs `faster-whisper`
- calls Ollama through `OLLAMA_URL`
- writes transcript, feedback, and failure state back to MariaDB

Base image recommendation:

- keep the app on `python:3.12-slim-bookworm`
- do not switch this app container to Alpine

Reason:

- `faster-whisper`, `ctranslate2`, `av`, and FFmpeg tooling are more dependable on a glibc-based image than on Alpine `musl`
- Alpine would increase build/runtime risk for little operational gain in this stack

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
- `status`
- `error_message`
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
- `VALKEY_URL`
  - queue backend URL, typically `redis://valkey:6379/0`
- `RQ_QUEUE`
  - queue name for submission jobs
- `QUEUE_SYNC`
  - should be `false` in Docker so the worker handles processing asynchronously
- `APP_DEBUG`
  - enables Flask debug-style exception propagation for controlled testing
- `APP_LOG_LEVEL`
  - Python application log level such as `INFO` or `DEBUG`
- `GUNICORN_LOG_LEVEL`
  - Gunicorn log level such as `info` or `debug`
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

Recommended defaults for normal production:

```text
APP_DEBUG=false
APP_LOG_LEVEL=INFO
GUNICORN_LOG_LEVEL=info
```

Recommended temporary values while debugging:

```text
APP_DEBUG=true
APP_LOG_LEVEL=DEBUG
GUNICORN_LOG_LEVEL=debug
APP_WORKERS=1
```

This stack uses controlled debug logging. It does not rely on exposing Flask's interactive debugger publicly.

## Volumes

The stack now uses:

- `mariadb_data`
  - MariaDB data directory
- `valkey`
  - queue backend service for `RQ`
- `uploads_data`
  - uploaded media files
- `caddy_data`
- `caddy_config`

This replaces the earlier single SQLite-oriented app volume.

## Ollama Connectivity

This stack expects **remote Ollama**.

Use this approach:

1. point `OLLAMA_URL` at a remote Ollama server that is reachable from the Docker host network

## Current App Boot Path in Docker

This stack uses:

- `backend/docker_wsgi.py`

It loads `backend/app.py` explicitly by file path and exposes a WSGI `app` object for Gunicorn. That keeps the production entrypoint explicit and decoupled from local development helpers.

The app entrypoint:

- creates upload directories if needed
- starts Gunicorn
- serves the Flask app on port `8080`

## How to Run

From inside the `Docker-Stack` folder:

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
- `VALKEY_URL`
- `OLLAMA_URL`
- `OLLAMA_MODEL`

Example:

```text
DATABASE_URL=mariadb://app_user:strong-password@mariadb:3306/av_evaluation
VALKEY_URL=redis://valkey:6379/0
OLLAMA_URL=http://ollama.example.internal:11434/api/generate
```

For real HTTPS production, also make sure:

```text
CADDY_SITE_ADDRESS=cnlp.langcen.cam.ac.uk
ALLOWED_ORIGINS=https://cnlp.langcen.cam.ac.uk
SESSION_COOKIE_SECURE=true
```

For local HTTP testing instead, use:

```text
CADDY_SITE_ADDRESS=:80
ALLOWED_ORIGINS=http://localhost,http://127.0.0.1
SESSION_COOKIE_SECURE=false
APP_DEBUG=true
APP_LOG_LEVEL=DEBUG
GUNICORN_LOG_LEVEL=debug
```

That distinction matters because secure session cookies will not work over plain HTTP.

## Current Operational Shape

This stack is now stronger than the earlier SQLite-based runtime because it uses:

- MariaDB instead of SQLite
- a separate DB container
- a Valkey-backed queue
- a worker container
- persistent uploads separate from DB state
- a real reverse proxy in front of Gunicorn

The biggest remaining limitations are:

- no object storage
- no retry/backoff strategy around queued jobs
- no horizontal scaling strategy for long-running inference

Operationally, the stack is easier to diagnose than before because:

- Gunicorn access logs go to container stdout
- Gunicorn error logs go to container stderr
- Flask logging can be raised with `APP_LOG_LEVEL`
- startup behavior can be made more verbose with `APP_DEBUG` and `GUNICORN_LOG_LEVEL`
- worker-side queue processing can be diagnosed separately from the web app

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

The `Docker-Stack` folder now supports a more production-ready deployment of the **current Flask app** with:

- Caddy
- Gunicorn
- Flask
- MariaDB
- Valkey
- one worker container
- persistent uploads
- external Ollama
- `ffprobe`-based duration validation

It is the correct production-oriented runtime for the current application without requiring the larger FastAPI/worker rewrite first.
