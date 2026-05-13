# Production Installation Guide

This guide explains how to deploy the current app from this repository onto a remote server running Docker so that:

- the app is reachable over `HTTPS`
- only ports `80` and `443` are exposed to the internet
- MariaDB is private to the Docker network
- uploaded media and database state are persisted in Docker volumes
- the Flask app runtime does not depend on host Python or host system packages

This guide assumes:

- you have a public domain name for the app
- your server already has Docker and Docker Compose installed
- you will use the files in this `Docker-Stack` folder
- Ollama is hosted remotely and reachable from the app container over the network

## Runtime Scope

Everything in the application runtime is containerized except Ollama:

- `caddy` handles inbound `80` and `443`
- `app` runs the Flask application under Gunicorn inside Docker
- `worker` processes queued submissions inside Docker
- `mariadb` runs inside Docker
- `valkey` provides the internal queue backend inside Docker
- uploaded media is stored in Docker volumes

The Docker host does **not** need local Python, a local virtual environment, or host-installed FFmpeg for the app to run.

The Python application container intentionally uses `python:3.12-slim-bookworm`, not Alpine. That is the correct production base image for this dependency set because `faster-whisper`, `ctranslate2`, `av`, and FFmpeg tooling are substantially more reliable on a glibc-based image than on Alpine `musl`.

## 1. Server Preparation

Clone the repository onto the server:

```bash
git clone <your-repo-url> av-evaluation
cd av-evaluation
```

Confirm Docker is available:

```bash
docker --version
docker compose version
```

## 2. DNS

Point your domain name at the public IP of the server.

Example:

- `app.example.com -> <server public IP>`

Do this before starting Caddy with HTTPS enabled.

## 3. Firewall and Network Security

Only expose:

- `80/tcp`
- `443/tcp`

Do **not** expose:

- MariaDB port `3306`
- Flask/Gunicorn internal port `8080`

If using `ufw`, the typical setup is:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 3306/tcp
sudo ufw deny 8080/tcp
sudo ufw enable
sudo ufw status
```

If using a cloud firewall or security group, configure it the same way:

- allow inbound `80`
- allow inbound `443`
- deny or omit all other app/database ports

## 4. Enter the Docker Stack Folder

```bash
cd Docker-Stack
```

## 5. Create a Production Environment File

Copy the example file:

```bash
cp .env.production.example .env.production
```

Edit it:

```bash
nano .env.production
```

At minimum, set these values.

The example file already includes the supported runtime and debug environment variables for the current stack. Treat `.env.production.example` as the template and keep your real secrets only in `.env.production`.

### Required security and runtime settings

```text
SECRET_KEY=<long-random-secret>
CADDY_SITE_ADDRESS=app.example.com
CADDY_EMAIL=you@example.com
ALLOWED_ORIGINS=https://app.example.com
SESSION_COOKIE_SECURE=true
```

### MariaDB settings

```text
MARIADB_DATABASE=av_evaluation
MARIADB_USER=app_user
MARIADB_PASSWORD=<strong-app-db-password>
MARIADB_ROOT_PASSWORD=<strong-root-db-password>
DATABASE_URL=mariadb://app_user:<strong-app-db-password>@mariadb:3306/av_evaluation
```

Important:

- `DATABASE_URL` must match `MARIADB_DATABASE`, `MARIADB_USER`, and `MARIADB_PASSWORD`
- if you change the DB username or password, update `DATABASE_URL` as well

### Ollama settings

Use a private or trusted endpoint. Do not expose your Ollama API publicly unless you have independently secured it.

Example:

```text
OLLAMA_URL=http://10.0.0.25:11434/api/generate
OLLAMA_MODEL=qwen2.5:latest
```

Set `OLLAMA_URL` to the remote Ollama endpoint that this server can reach over the network. Do not rely on `host.docker.internal` in this production setup.

### Suggested worker/runtime settings

```text
PORT=8080
UPLOADS_DIR=/data/uploads
WHISPER_MODEL_SIZE=medium
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
VALKEY_URL=redis://valkey:6379/0
RQ_QUEUE=submissions
QUEUE_SYNC=false
APP_DEBUG=false
APP_LOG_LEVEL=INFO
GUNICORN_LOG_LEVEL=info
APP_WORKERS=2
APP_THREADS=4
```

### Optional debug settings for testing

For temporary diagnostics during testing, you can increase logging with:

```text
APP_DEBUG=true
APP_LOG_LEVEL=DEBUG
GUNICORN_LOG_LEVEL=debug
APP_WORKERS=1
```

What those do:

- `APP_DEBUG=true`
  - enables Flask debug-style exception propagation inside the app
- `APP_LOG_LEVEL=DEBUG`
  - raises Python application logging to `DEBUG`
- `GUNICORN_LOG_LEVEL=debug`
  - raises Gunicorn logging verbosity
- `APP_WORKERS=1`
  - makes logs easier to follow while debugging

Use those values only while debugging. Turn them back down for normal production operation.

### Local HTTP test profile

If you want to test the Docker stack locally over plain HTTP instead of real HTTPS, use values like:

```text
CADDY_SITE_ADDRESS=:80
ALLOWED_ORIGINS=http://localhost,http://127.0.0.1
SESSION_COOKIE_SECURE=false
APP_DEBUG=true
APP_LOG_LEVEL=DEBUG
GUNICORN_LOG_LEVEL=debug
```

Why:

- `SESSION_COOKIE_SECURE=true` prevents login cookies from working over plain HTTP
- `CADDY_SITE_ADDRESS=:80` is for local or temporary non-TLS testing only

Do not keep those HTTP test values in a real internet-facing deployment.

### Real HTTPS production profile

For a real deployment with automatic Caddy certificates, use values like:

```text
CADDY_SITE_ADDRESS=app.example.com
ALLOWED_ORIGINS=https://app.example.com
SESSION_COOKIE_SECURE=true
APP_DEBUG=false
APP_LOG_LEVEL=INFO
GUNICORN_LOG_LEVEL=info
```

## 6. Review the Important Security Model

This stack is secure by default in these ways:

- only Caddy publishes ports to the host
- the `app` service is only exposed internally on the Docker network
- the `worker` service is only exposed internally on the Docker network
- the `mariadb` service is only exposed internally on the Docker network
- the `valkey` service is only exposed internally on the Docker network
- Ollama is accessed as an outbound remote dependency rather than exposed through this stack
- uploads are stored in a Docker volume, not in a public web root
- Flask session cookies are marked `Secure` when `SESSION_COOKIE_SECURE=true`

Do not add `ports:` mappings to:

- `app`
- `worker`
- `mariadb`
- `valkey`

That would weaken the deployment.

## 7. Build and Start the Stack

Run:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

Check status:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Check logs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f
```

For focused application debugging:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f app
```

For focused worker debugging:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f worker
```

For focused reverse-proxy debugging:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f caddy
```

## 8. HTTPS Behavior

Caddy will automatically obtain and renew TLS certificates when:

- `CADDY_SITE_ADDRESS` is set to a real domain name
- DNS is already pointing at the server
- ports `80` and `443` are reachable from the internet

If those conditions are met, your app should become available at:

- `https://app.example.com`

If you leave `CADDY_SITE_ADDRESS=:80`, the stack will not be configured for public automatic HTTPS.

For a real production deployment, do **not** leave `CADDY_SITE_ADDRESS=:80`.
Set it to the real public hostname instead.

If you are intentionally testing over plain HTTP on a local or private machine, set:

- `CADDY_SITE_ADDRESS=:80`
- `SESSION_COOKIE_SECURE=false`
- `ALLOWED_ORIGINS=http://localhost,http://127.0.0.1`

## 9. Create the Initial Admin User

After the stack is up, create the first admin account inside the app container.

Run:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec app \
  python seed_admin.py admin '<strong-admin-password>' admin
```

You can then sign in through the web UI.

## 10. Verify the Deployment

Check that the app is serving over HTTPS:

```bash
curl -I https://app.example.com
```

Check that the response includes TLS/security behavior:

- valid HTTPS certificate
- `strict-transport-security` header

Confirm that only `80` and `443` are listening publicly on the host:

```bash
ss -ltnp
```

You should not see public listeners for:

- `3306`
- `8080`

You can also inspect container status:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

If the `app` service fails to start, check these first:

- `DATABASE_URL` matches `MARIADB_DATABASE`, `MARIADB_USER`, and `MARIADB_PASSWORD`
- `OLLAMA_URL` is reachable from the app container
- `VALKEY_URL` points at the internal `valkey` service or another reachable queue endpoint
- `SESSION_COOKIE_SECURE` is not left at `true` during plain-HTTP local testing
- `CADDY_SITE_ADDRESS` matches whether you are doing local HTTP testing or real HTTPS deployment

## 11. Upgrades

To deploy updated code from the repository:

```bash
cd /path/to/av-evaluation
git pull
cd Docker-Stack
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

## 12. Backups

You should back up:

- MariaDB data
- uploaded media

The relevant Docker volumes are:

- `mariadb_data`
- `uploads_data`

List volumes:

```bash
docker volume ls
```

At a minimum, ensure those volumes are included in your host backup strategy.

## 13. Useful Commands

Restart:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart
```

Stop:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

Stop without deleting volumes:

- this preserves database state and uploads

Rebuild after config or code changes:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

## 14. Troubleshooting

### HTTPS certificate is not issued

Check:

- DNS is correct
- `CADDY_SITE_ADDRESS` is a real domain
- ports `80` and `443` are open publicly
- no other service is already bound to `80` or `443`

Then inspect:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs caddy
```

### App starts but feedback generation fails

Check:

- `OLLAMA_URL` is reachable from the app container
- the configured `OLLAMA_MODEL` exists on the Ollama server

Inspect logs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs app
```

### Database connection fails

Check:

- `DATABASE_URL`
- `MARIADB_USER`
- `MARIADB_PASSWORD`
- `MARIADB_DATABASE`
- `DATABASE_URL` matches the MariaDB username/password/database values exactly

Inspect:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs mariadb
docker compose --env-file .env.production -f docker-compose.prod.yml logs app
```

### Uploads work but old data is missing

Make sure you did not remove Docker volumes. Persistent state is stored in:

- `mariadb_data`
- `uploads_data`

## 15. Security Recommendations

- use a long random `SECRET_KEY`
- keep `SESSION_COOKIE_SECURE=true`
- use strong unique passwords for `MARIADB_PASSWORD` and `MARIADB_ROOT_PASSWORD`
- keep `OLLAMA_URL` on a private network if possible
- do not publish `3306` or `8080`
- keep the server OS patched
- keep Docker images updated
- back up both DB and upload volumes

## 16. Result

After following this guide, the deployment should have:

- public access only on `80` and `443`
- HTTPS termination at Caddy
- private MariaDB on the Docker network
- the current Flask app running under Gunicorn
- persistent uploads and database state
