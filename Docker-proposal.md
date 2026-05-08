# Docker Production Proposal

## Objective

Convert the current development-oriented Flask application into a production deployment that:

- runs in Docker containers
- uses MariaDB instead of SQLite
- serves the frontend and API behind Nginx
- supports either Ollama or OpenAI for feedback generation
- moves long-running transcription and inference work out of web requests
- standardizes the runtime on Python 3.12

## Current State

The current application is designed for local development:

- Flask serves both the frontend and API
- SQLite stores users and submissions
- transcription and feedback generation happen synchronously in the request path
- the Flask development server is used directly
- inference logic is tied closely to the current provider call pattern

This is not suitable for production because:

- SQLite is not appropriate for concurrent multi-container production use
- long-running requests will tie up web workers
- the development server should not be internet-facing
- there is no migration workflow for schema changes
- the runtime is not yet standardized for reproducible builds

## Python Runtime Standardization

Use Python 3.12 everywhere.

Recommendation:

- local development uses `pyenv`
- virtual environments are created from the `pyenv` Python, not the system Python
- Docker images use a Python 3.12 base image

### Recommended local workflow

```bash
pyenv install 3.12.9
pyenv local 3.12.9
python --version
python -m venv .venv
```

Do not create the project virtual environment from a system-installed Python interpreter.

### Why Python 3.12

Python 3.12 is a good fit for the required production stack, including:

- Flask 3.x
- Gunicorn
- SQLAlchemy 2.x
- Alembic
- PyMySQL
- Redis client libraries
- `faster-whisper`
- `ctranslate2`
- `av`
- OpenAI Python SDK 1.x

### Container base image

Use:

- `python:3.12-slim-bookworm`

That gives a reproducible Python runtime without depending on OS package Python inside the image.

## Recommended Production Architecture

For a first production deployment, use these containers:

1. `nginx`
2. `api` running Flask under Gunicorn
3. `worker` for transcription and feedback jobs
4. `redis` for the background job queue
5. `mariadb` for relational storage

Optional but strongly recommended:

6. `backup` job container for database dumps
7. `adminer` or `phpmyadmin` only in non-production admin environments
8. `ollama` only if inference will run on infrastructure you control and the host has the required CPU/GPU capacity

## Inference Provider Recommendation

The production design should not hardwire the application to Ollama only. It should support two providers behind one internal interface:

1. Ollama
2. OpenAI

### Recommended application abstraction

Create a provider layer such as:

- `llm/providers/base.py`
- `llm/providers/ollama.py`
- `llm/providers/openai.py`

The worker should call one internal interface, for example:

```python
feedback = llm_client.generate_feedback(transcript)
```

instead of embedding provider-specific HTTP calls directly in the upload logic.

### When to use OpenAI

Choose OpenAI if:

- you want the simplest production operations
- you do not want to run local model infrastructure
- external API dependence is acceptable
- you want elastic capacity without GPU operations

### When to use Ollama

Choose Ollama if:

- data must remain on infrastructure you control
- you already operate suitable inference hosts
- additional operational complexity is acceptable

### My recommendation

For a first production rollout:

- default to OpenAI for feedback generation
- keep Ollama as an alternate provider

That reduces operational burden while preserving a path to self-hosted inference later.

## Recommended Container Responsibilities

### `nginx`

Responsibilities:

- serve static frontend assets
- reverse proxy `/api/*` to the API container
- enforce request body limits
- terminate TLS
- add cache headers for static assets
- optionally add rate limiting on login and upload endpoints

Why:

- Nginx is better than Flask at static delivery, buffering, connection handling, and TLS termination

### `api`

Responsibilities:

- authentication
- admin endpoints
- upload metadata validation
- job creation
- job status retrieval
- session handling

Implementation recommendation:

- run Flask behind Gunicorn
- do not use `app.run(...)` in production

Suggested command:

```bash
gunicorn -w 4 -k gthread --threads 4 -b 0.0.0.0:8000 "app:create_app()"
```

### `worker`

Responsibilities:

- consume upload-processing jobs
- perform transcription
- call the configured inference provider
- store transcript and feedback in MariaDB
- clean up temporary files

Why:

- transcription and LLM generation are slow operations
- background workers prevent web requests from blocking for minutes
- this is the biggest production improvement for this app

Recommended queue:

- Redis + RQ for simplicity

Alternative:

- Redis + Celery if more complex workflows are expected later

### `redis`

Responsibilities:

- queue broker
- transient job state

### `mariadb`

Responsibilities:

- store users
- store submissions
- support concurrent reads and writes from API and worker containers

Why MariaDB:

- operationally simple
- widely supported
- a good fit for the current schema and expected workload

## Recommended Request Workflow

### Login Flow

1. Browser requests frontend from Nginx
2. Browser submits login to `/api/auth/login`
3. Nginx proxies to `api`
4. `api` reads the user from MariaDB
5. `api` returns a session cookie

### Upload and Feedback Flow

1. User uploads `MP3` or `MP4`
2. Nginx accepts the upload and proxies to `api`
3. `api` validates session, extension, and size
4. `api` stores the temporary upload in shared ephemeral storage
5. `api` creates a job in Redis
6. `api` returns a `job_id` immediately
7. `worker` picks up the job
8. `worker` transcribes the media
9. `worker` calls the configured inference provider
10. `worker` stores transcript and feedback in MariaDB
11. Browser polls `/api/jobs/<job_id>` or uses server-sent events
12. Browser renders the returned markdown safely

This is better than the current synchronous design because it:

- prevents reverse proxy and Gunicorn timeouts
- supports retries
- isolates slow inference from user-facing request threads
- makes horizontal scaling possible

## Database Migration Recommendation

The current database layer is raw `sqlite3` with inline schema creation. For MariaDB, replace it with:

- SQLAlchemy ORM or SQLAlchemy Core
- Alembic for migrations
- PyMySQL or MariaDB Connector/Python

### Recommended target

- `DATABASE_URL` environment variable
- SQLAlchemy engine + scoped session
- Alembic migration scripts committed to the repo

Example:

```text
mysql+pymysql://app_user:strong_password@mariadb:3306/av_evaluation
```

### Proposed schema

#### `users`

- `user_id` `CHAR(36)` primary key
- `username` `VARCHAR(255)` unique not null
- `password_hash` `VARCHAR(255)` not null
- `cohort_id` `VARCHAR(255)` not null default `''`
- `is_admin` `BOOLEAN` not null default `0`
- `created_at` `DATETIME(6)` not null

Indexes:

- unique index on `username`
- index on `cohort_id`

#### `submissions`

- `submission_id` `CHAR(36)` primary key
- `user_id` `CHAR(36)` not null
- `transcript` `LONGTEXT`
- `feedback` `LONGTEXT`
- `submitted_at` `DATETIME(6)` not null

Indexes:

- index on `user_id`
- index on `submitted_at`

Foreign key:

- `submissions.user_id -> users.user_id ON DELETE CASCADE`

## Application Changes Required

### 1. Replace SQLite access

Refactor [`backend/database.py`](/home/saimon/projects/av-evaluation/backend/database.py:1) to:

- read `DATABASE_URL`
- create a pooled MariaDB connection layer
- remove file-path-based DB configuration

### 2. Add migrations

Add:

- `alembic.ini`
- `migrations/`
- migration scripts for the initial schema

### 3. Move long-running work out of request handlers

Refactor [`backend/upload.py`](/home/saimon/projects/av-evaluation/backend/upload.py:80) so that:

- the upload endpoint creates a job instead of doing transcription inline
- a job-status endpoint returns state and result

Recommended endpoints:

- `POST /api/upload`
- `GET /api/jobs/<job_id>`

Optional:

- `GET /api/submissions/<submission_id>`

### 4. Add inference provider abstraction

Refactor inference code so the worker selects a provider from configuration rather than calling a single hardcoded backend.

Recommended environment variables:

- `LLM_PROVIDER=openai` or `LLM_PROVIDER=ollama`
- `OLLAMA_URL`
- `OLLAMA_MODEL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_BASE_URL`

OpenAI should use the official SDK rather than raw HTTP where possible.

### 5. Production session and cookie settings

Current settings in [`backend/app.py`](/home/saimon/projects/av-evaluation/backend/app.py:26) should be hardened:

- strong `SECRET_KEY`
- `SESSION_COOKIE_SECURE=True`
- `SESSION_COOKIE_HTTPONLY=True`
- `SESSION_COOKIE_SAMESITE='Lax'` or `'Strict'`

If you later scale API replicas horizontally, consider:

- server-side session storage using Redis

### 6. Split frontend delivery from Flask

Today Flask serves files from `frontend/`. In production, prefer:

- Nginx serves `index.html`, `app.js`, `admin.js`, and `app.css`
- Flask handles only `/api/*`

### 7. Improve configuration model

Standardize these environment variables:

- `APP_ENV=production`
- `DATABASE_URL`
- `SECRET_KEY`
- `ALLOWED_ORIGINS`
- `LLM_PROVIDER`
- `OLLAMA_URL`
- `OLLAMA_MODEL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_BASE_URL`
- `WHISPER_MODEL_SIZE`
- `WHISPER_DEVICE`
- `WHISPER_COMPUTE_TYPE`
- `REDIS_URL`
- `MAX_UPLOAD_MB_MP3`
- `MAX_UPLOAD_MB_MP4`
- `LOG_LEVEL`

### 8. Add health endpoints

Add:

- `/health/live`
- `/health/ready`

Readiness should verify:

- database connectivity
- Redis connectivity
- optionally connectivity to the configured inference provider

### 9. Add production dependency sets

Introduce a production dependency file that is explicitly validated on Python 3.12.

Recommended packages:

- `flask`
- `flask-cors`
- `gunicorn`
- `sqlalchemy`
- `alembic`
- `pymysql`
- `redis`
- `rq`
- `faster-whisper`
- `requests`
- `openai`

Recommendation:

- keep development and production requirements separate if needed
- pin versions after a test pass under Python 3.12

## Proposed Docker Layout

Suggested files:

```text
docker/
├── nginx/
│   ├── nginx.conf
│   └── conf.d/
│       └── default.conf
├── api/
│   ├── Dockerfile
│   └── entrypoint.sh
├── worker/
│   ├── Dockerfile
│   └── entrypoint.sh
└── mariadb/
    └── init/
```

Repo additions:

```text
docker-compose.prod.yml
.env.production
.python-version
backend/
├── requirements-prod.txt
├── migrations/
└── ...
```

`.python-version` should pin a Python 3.12 release, for example:

```text
3.12.9
```

## Proposed Services in `docker-compose.prod.yml`

### `nginx`

- exposes `80` and `443`
- mounts TLS certificates or integrates with a certificate manager
- depends on `api`

### `api`

- built from `backend/`
- based on `python:3.12-slim-bookworm`
- runs Gunicorn
- connects to `mariadb` and `redis`
- no public port exposed directly

### `worker`

- built from the same codebase as `api`
- based on `python:3.12-slim-bookworm`
- runs the queue consumer
- connects to `redis`, `mariadb`, and the configured inference provider

### `redis`

- internal only
- persistent volume optional

### `mariadb`

- internal only
- persistent named volume required
- backup job strongly recommended

### `ollama`

Use this only when `LLM_PROVIDER=ollama`.

Use one of two patterns:

1. external managed or separately operated Ollama host
2. dedicated `ollama` container on a GPU-enabled machine

### `openai`

OpenAI is normally not a container in this stack.

Instead:

- the worker uses the OpenAI API directly
- credentials are injected through secrets or environment variables

Use this when:

- `LLM_PROVIDER=openai`
- `OPENAI_API_KEY` is available

## Example Production Flow by Container

```text
Browser
  -> Nginx
    -> API container
      -> Redis job queue
      -> MariaDB

Worker container
  -> Redis job queue
  -> Ollama endpoint or OpenAI API
  -> MariaDB
```

## Nginx Recommendations

Configure Nginx to:

- serve `/` and static assets directly
- proxy `/api/` to `api:8000`
- allow large request bodies for uploads
- enforce sane timeouts
- set security headers
- gzip text assets

Important settings:

- `client_max_body_size 310m;`
- proxy read timeout sized for upload acceptance, not inference completion
- static asset caching for `app.js`, `admin.js`, and `app.css`

## Storage Recommendations

### MariaDB

Use a persistent named Docker volume:

- `mariadb_data`

### Upload processing

Because uploads are deleted after processing, use either:

- a shared ephemeral volume between `api` and `worker`, or
- direct handoff to object storage if cleaner scaling is needed later

For version 1, recommend:

- shared Docker volume for temporary upload files

If the app grows, move to:

- S3-compatible storage such as MinIO or cloud object storage

## Security Recommendations

### Secrets

Do not hardcode:

- DB passwords
- MariaDB root password
- Flask `SECRET_KEY`
- `OPENAI_API_KEY`

Use:

- Docker secrets if available
- otherwise injected environment variables from a secure deployment system

### Network exposure

Expose publicly:

- only `nginx`

Keep internal:

- `api`
- `worker`
- `redis`
- `mariadb`

### Auth hardening

Add:

- rate limiting on login
- account lockout or progressive slowdown after repeated failures
- audit logging for admin actions

## Operational Recommendations

### Health checks

Add health checks for:

- `nginx`
- `api`
- `worker`
- `redis`
- `mariadb`

### Backups

At minimum:

- nightly MariaDB dump
- retention policy
- restore test procedure

### Monitoring

At minimum:

- centralized container logs
- request error monitoring
- queue depth monitoring
- DB disk usage monitoring

## Deployment Workflow Recommendation

### Phase 1: Application Refactor

1. Replace SQLite with SQLAlchemy + MariaDB support
2. Add Alembic migrations
3. Introduce background job processing
4. Split API and static frontend responsibilities
5. Add health endpoints and production config
6. Add inference provider abstraction for Ollama and OpenAI

### Phase 2: Runtime Standardization

1. Add `.python-version`
2. Standardize on `pyenv` Python 3.12 locally
3. Validate dependency installation on Python 3.12
4. Pin production dependency versions after validation

### Phase 3: Containerization

1. Build the production app image
2. Build the worker image from the same codebase
3. Add Nginx config and image
4. Create `docker-compose.prod.yml`
5. Add persistent volumes and environment files

### Phase 4: Database Migration

1. Create the initial MariaDB schema via Alembic
2. Export existing SQLite data
3. Transform and import into MariaDB
4. Validate row counts and sample records

### Phase 5: Production Validation

1. Test login
2. Test admin user creation
3. Test upload and async processing
4. Test large file handling
5. Test OpenAI failure scenarios if that provider is enabled
6. Test Ollama failure scenarios if that provider is enabled
7. Test DB backup and restore

### Phase 6: Cutover

1. Deploy the stack
2. Run migrations
3. Seed the first admin user
4. Update DNS and TLS
5. Monitor logs and queue depth closely

## Recommended Seed/Admin Workflow

Replace the current SQLite seed script with:

- a CLI command that uses the MariaDB connection layer

Example:

```bash
python manage.py create-admin --username admin --password 'strong-password'
```

This command should run in the `api` container against MariaDB.

## Suggested Minimal Production Stack

If you want the smallest acceptable production stack, use:

1. `nginx`
2. `api` with Gunicorn
3. `worker`
4. `redis`
5. `mariadb`
6. external OpenAI API or external Ollama service

This is the best balance of simplicity and correctness.

## Suggested Future Enhancements

- object storage for uploads and generated artifacts
- server-sent events or WebSocket job progress
- Prometheus metrics
- centralized logging
- admin audit trail
- per-user submission history UI
- retention policies for transcripts and feedback

## Final Recommendation

For production, do not containerize the app as a single Flask process with SQLite.

Instead:

- use Nginx for web serving and reverse proxying
- run Flask behind Gunicorn in an `api` container
- move transcription and inference work into a `worker` container
- use Redis as the queue broker
- use MariaDB for persistent relational storage
- standardize development on `pyenv` Python 3.12
- standardize containers on Python 3.12
- prefer OpenAI as the default production inference provider
- keep Ollama as an alternate provider for self-hosted inference

That architecture matches the behavior of this application and gives you a deployment that is much easier to scale, secure, and operate.
