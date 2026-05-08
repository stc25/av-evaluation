FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY ["Docker stack/backend/requirements-prod.txt", "/tmp/requirements-prod.txt"]

RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements-prod.txt

COPY backend /app/backend
COPY frontend /app/frontend
COPY ["Docker stack/backend/docker_wsgi.py", "/app/backend/docker_wsgi.py"]
COPY ["Docker stack/docker/scripts", "/opt/docker-scripts"]

RUN mkdir -p /data/uploads \
    && chmod +x /opt/docker-scripts/*.sh

EXPOSE 8080
