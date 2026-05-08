# AV Evaluation

AV Evaluation is a web application for practicing academic presentations. A user signs in, uploads or records a presentation, and receives AI-generated feedback on structure, tone, clarity, cohesion, and language.

The app is built as a single Flask service that:

- serves the static frontend from `frontend/`
- exposes authentication, admin, and upload APIs
- stores users, transcripts, and feedback in SQLite for local development or MariaDB in the Docker deployment
- transcribes audio/video with `faster-whisper`
- sends the transcript to Ollama for feedback generation

## Features

- Username/password sign-in with session cookies
- Upload support for `MP3`, `MP4`, and recorded `WebM`
- File size validation:
  - `MP3`: up to `30 MB`
  - `MP4`: up to `300 MB`
- In-browser webcam recording with a `15` minute limit and `1` minute warning
- Inline playback before submission
- Transcript and feedback persistence with submission history
- Admin page for:
  - creating users
  - listing users
  - deleting a single user
  - deleting all users in a cohort
  - reviewing user submissions and stored media

## Project Structure

```text
.
├── backend/
│   ├── app.py
│   ├── run_dev.py
│   ├── auth.py
│   ├── admin.py
│   ├── upload.py
│   ├── database.py
│   ├── seed_admin.py
│   └── requirements.txt
├── Docker stack/
│   ├── docker-compose.prod.yml
│   ├── INSTALL.md
│   └── Docker-proposal-new.md
├── frontend/
│   ├── index.html
│   ├── admin.html
│   ├── app.js
│   ├── admin.js
│   └── app.css
```

The current application code lives in `backend/` and `frontend/`. Production deployment files live in `Docker stack/`.

## How It Works

1. A user signs in through the frontend.
2. The browser uploads an `MP3`, `MP4`, or recorded `WebM` file to `POST /api/upload`.
3. The backend writes the upload to a temporary file.
4. `faster-whisper` transcribes the file.
5. The transcript is sent to Ollama using the configured local model.
6. The generated markdown feedback is returned to the frontend.
7. The transcript and feedback are stored in SQLite.
8. The submission metadata, transcript, feedback, and stored media path are saved for later review.

## Prerequisites

- Python `3.12+`
- Ollama installed and running locally
- An Ollama model available locally
- Internet access the first time `faster-whisper` downloads its model files

## Recommended Local Runtime

This repository was verified in:

- distro: `Ubuntu-24.04`
- Python: `python3`

Use WSL Python for local development.

## Local Setup

### 1. Create a virtual environment and install dependencies

```bash
cd /home/saimon/projects/av-evaluation/backend
python3 -m venv .venv-wsl
. .venv-wsl/bin/activate
pip install -r requirements.txt
```

### 2. Check that Ollama is running

```bash
ollama list
```

If the default model `qwen2.5:latest` is not installed, either pull it or override `OLLAMA_MODEL` at runtime with a model that already exists locally.

Example:

```bash
ollama pull qwen2.5:latest
```

or run the app with:

```bash
OLLAMA_MODEL=gemma4:e2b
```

### 3. Create an initial admin user

```bash
cd /home/saimon/projects/av-evaluation/backend
APP_DB_PATH=/home/saimon/projects/av-evaluation/backend/instance/dev-app.db \
./.venv-wsl/bin/python seed_admin.py admin changeme
```

This creates the SQLite database if needed and inserts the first admin account.

### 4. Start the backend

```bash
cd /home/saimon/projects/av-evaluation/backend
APP_DB_PATH=/home/saimon/projects/av-evaluation/backend/instance/dev-app.db \
OLLAMA_MODEL=gemma4:e2b \
./.venv-wsl/bin/python run_dev.py
```

Then open:

- app: [http://localhost:8080](http://localhost:8080)
- admin page: [http://localhost:8080/admin.html](http://localhost:8080/admin.html)

## Default Local Login

If you created the sample admin above:

- username: `admin`
- password: `changeme`

Change that password immediately if you use this outside local development.

## Configuration

The application is configured entirely through environment variables.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8080` | Port used by the Flask server. |
| `SECRET_KEY` | `dev-secret-change-in-production` | Flask session signing key. Must be changed for non-dev use. |
| `ALLOWED_ORIGINS` | `http://localhost:8080,http://127.0.0.1:8080` | Comma-separated CORS origin allowlist. |
| `APP_DB_PATH` | `backend/instance/app.db` | SQLite database file path. Useful for separate dev/test databases. |
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama generate endpoint. |
| `OLLAMA_MODEL` | `qwen2.5:latest` | Ollama model name used to generate feedback. |
| `WHISPER_MODEL_SIZE` | `medium` | `faster-whisper` model size. Smaller models are faster but less accurate. |
| `WHISPER_DEVICE` | `auto` | Device selection for `faster-whisper`. |
| `WHISPER_COMPUTE_TYPE` | `int8` | Compute mode for `faster-whisper`. |

## Example Configuration

Run on a different port and database:

```bash
PORT=8090 \
APP_DB_PATH=/home/saimon/projects/av-evaluation/backend/instance/local-8090.db \
OLLAMA_MODEL=qwen2.5:latest \
./.venv-wsl/bin/python run_dev.py
```

Run with a smaller transcription model:

```bash
WHISPER_MODEL_SIZE=small \
WHISPER_COMPUTE_TYPE=int8 \
./.venv-wsl/bin/python run_dev.py
```

## Data Storage

Local development stores two tables in SQLite, and the Docker deployment stores the same logical data in MariaDB:

- `users`
- `submissions`

Each submission stores:

- `submission_id`
- `user_id`
- transcript text
- feedback markdown
- submission timestamp

Uploaded media files are kept so users and admins can review prior submissions.

## Admin Capabilities

Authenticated admins can:

- view all users
- create standard users or admins
- assign a `cohort_id`
- delete a user and their submissions
- delete all users in a cohort except the currently signed-in admin

## API Summary

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/auth/login` | `POST` | Sign in |
| `/api/auth/logout` | `POST` | Sign out |
| `/api/auth/me` | `GET` | Return the current session user |
| `/api/upload` | `POST` | Upload a presentation and get feedback |
| `/api/admin/users` | `GET` | List users |
| `/api/admin/users` | `POST` | Create a user |
| `/api/admin/users/<user_id>` | `DELETE` | Delete one user |
| `/api/admin/users/cohort/<cohort_id>` | `DELETE` | Delete all users in a cohort |

## Notes

- The frontend is served by Flask from the same origin as the API.
- The frontend expects markdown feedback and sanitizes it before rendering.
- Large uploads can take time because upload, transcription, and Ollama generation all happen in one request.
- The first transcription request may be slower while the Whisper model is downloaded or loaded.

## Troubleshooting

### `Could not connect to the AI model`

Make sure Ollama is running and that `OLLAMA_URL` points to the correct endpoint.

### `Transcription failed`

Common causes:

- the Whisper model download has not completed
- the uploaded file is corrupt or unsupported
- the selected device/compute type is not suitable for the machine

Try:

```bash
WHISPER_DEVICE=cpu WHISPER_COMPUTE_TYPE=int8 ./.venv-wsl/bin/python run_dev.py
```

### SQLite database is locked

Use the WSL Python environment from the Linux workspace path.

### Login works but uploads fail

Check both:

- Ollama availability
- whether the selected `OLLAMA_MODEL` exists locally in `ollama list`
