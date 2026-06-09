# Django Development Stack Install Guide

This guide describes how to start a parallel Django implementation of the AV Evaluation app without disturbing the current Flask stack.

The goal for this development stack is:

- keep the existing Flask app available while Django is built
- run Django independently on `http://localhost:8090`
- use email-based student login with invite links
- preserve the current upload, transcription, feedback, and comparison behavior
- prepare the codebase for a worker container that handles long-running AV processing

## 1. Create `Docker-django-stack/`

From the repository root:

```bash
cd /home/saimon/projects/av-evaluation
mkdir -p Docker-django-stack
cd Docker-django-stack
```

Suggested initial layout:

```text
Docker-django-stack/
  Install.md
  docker-compose.yml
  .env.example
  backend/
    Dockerfile
    requirements.txt
    manage.py
    config/
    users/
    submissions/
    processing/
    notifications/
```

Keep this folder separate from the existing `Docker-Stack/` folder. The current production Flask deployment should continue to use `Docker-Stack/`.

## 2. Scaffold the Django Project Inside It

Create a Python virtual environment for local scaffolding:

```bash
cd /home/saimon/projects/av-evaluation/Docker-django-stack
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install "Django>=5.2,<6" celery redis psycopg[binary] python-dotenv requests av faster-whisper
```

Create the Django project:

```bash
mkdir backend
django-admin startproject config backend
cd backend
python manage.py startapp users
python manage.py startapp submissions
python manage.py startapp processing
python manage.py startapp notifications
```

Add the local apps to `config/settings.py`:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "users",
    "submissions",
    "processing",
    "notifications",
]
```

Add development host settings:

```python
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]
STATIC_URL = "static/"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
```

Acceptance check:

```bash
python manage.py check
```

## 3. Build Email Login First

Create a custom email-based user model before running the first migration.

In `users/models.py`, define a `User` model based on `AbstractBaseUser` and `PermissionsMixin`. It should include:

- `email`
- `first_name`
- `last_name`
- `role`
- `cohort_id`
- `is_active`
- `is_staff`
- `date_joined`

Use roles such as:

```python
class Roles(models.TextChoices):
    STUDENT = "student", "Student"
    ADMIN = "admin", "Admin"
```

Set:

```python
USERNAME_FIELD = "email"
```

Then add this to `config/settings.py`:

```python
AUTH_USER_MODEL = "users.User"
LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "submissions:dashboard"
LOGOUT_REDIRECT_URL = "users:login"
```

Implement these routes in `users/urls.py`:

```text
/accounts/login/
/accounts/logout/
/accounts/password-reset/
/accounts/reset/<uidb64>/<token>/
```

Use Django's built-in auth views where possible:

- `LoginView`
- `LogoutView`
- `PasswordResetView`
- `PasswordResetConfirmView`
- `PasswordResetDoneView`
- `PasswordResetCompleteView`

For student invites, follow this behavior:

1. Admin creates a student user with an email address.
2. The user is saved with `set_unusable_password()`.
3. A `post_save` signal detects the new unusable-password user.
4. The signal sends a password-set email using Django's password-reset token generator.
5. Student clicks the link, sets their password, then logs in with email.

Development email settings:

```python
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = BASE_DIR.parent / "tmp_emails"
DEFAULT_FROM_EMAIL = "no-reply@localhost"
PASSWORD_RESET_TIMEOUT = 86400
```

Acceptance checks:

```bash
python manage.py makemigrations users
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8090
```

Then verify that login works at:

```text
http://localhost:8090/accounts/login/
```

## 4. Add Models for Submissions and Comparisons

Create Django models that replace the current manual SQL tables.

Suggested `submissions/models.py`:

```python
class Submission(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Source(models.TextChoices):
        UPLOAD = "upload", "Upload"
        RECORDED = "recorded", "Recorded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    original_filename = models.CharField(max_length=255, blank=True)
    media = models.FileField(upload_to="submissions/%Y/%m/%d/", blank=True)
    duration_seconds = models.FloatField(default=0)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.UPLOAD)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    error_message = models.TextField(blank=True)
    transcript = models.TextField(blank=True)
    feedback = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
```

Suggested `Comparison` model:

```python
class Comparison(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    older_submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="+")
    latest_submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="+")
    older_filename = models.CharField(max_length=255, blank=True)
    latest_filename = models.CharField(max_length=255, blank=True)
    comparison_feedback = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
```

Register both models in `submissions/admin.py`.

Acceptance check:

```bash
python manage.py makemigrations submissions
python manage.py migrate
python manage.py check
```

## 5. Port the Upload API from Flask

Create Django views that match the current Flask API shape so the existing frontend can be adapted with minimal disruption.

Target endpoints:

```text
GET  /api/submissions/
GET  /api/submissions/<uuid:submission_id>/
POST /api/upload/
POST /api/submissions/compare/
GET  /api/comparisons/
GET  /api/comparisons/<uuid:comparison_id>/
```

Port behavior from the current Flask upload route:

- require authenticated user
- accept `MP3`, `M4A`, `MP4`, and `WebM`
- enforce file size limits
- validate media duration
- enforce the 15 minute recording limit
- save a queued `Submission`
- trigger background processing
- return `202 Accepted` while queued

Keep response JSON close to the current frontend contract:

```json
{
  "submission_id": "...",
  "original_filename": "...",
  "has_media": true,
  "duration_seconds": 123.4,
  "submission_source": "upload",
  "status": "queued",
  "error_message": null,
  "transcript": null,
  "feedback": null,
  "submitted_at": "..."
}
```

Acceptance checks:

```bash
python manage.py runserver 0.0.0.0:8090
curl -I http://localhost:8090/api/submissions/
```

The unauthenticated response should be a login redirect or `403`, depending on whether you implement template views or JSON-only API decorators.

## 6. Move Whisper and Ollama Code into Django Services

Move the reusable logic from the current Flask backend into `processing/services.py`.

Functions to preserve:

- allowed extension checks
- max file size checks
- duration extraction using `ffprobe` and PyAV
- remote transcription via `TRANSCRIPTION_URL`
- local transcription via `faster-whisper`
- feedback generation via Ollama
- comparison generation via Ollama

Recommended service functions:

```python
def get_media_duration_seconds(file_path: str) -> float:
    ...

def transcribe(file_path: str) -> str:
    ...

def generate_feedback(transcript: str) -> str:
    ...

def compare_transcripts(older_transcript: str, latest_transcript: str) -> str:
    ...

def process_submission(submission_id) -> None:
    ...
```

Move runtime settings into Django settings:

```python
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:latest")
TRANSCRIPTION_URL = os.getenv("TRANSCRIPTION_URL", "")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "medium")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
MAX_DURATION_SECONDS = 15 * 60
```

Acceptance check:

```bash
python manage.py shell
```

Then import the service module:

```python
from processing import services
```

The import should succeed without loading the Whisper model until transcription is actually requested.

## 7. Add a Worker Container for Long-Running Processing

Use a worker so uploads return quickly and transcription/feedback generation does not block the web request.

Recommended development stack:

- `django-web`
- `django-worker`
- `django-db`
- `redis`

Create `backend/config/celery.py`:

```python
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("av_evaluation")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

In `backend/config/__init__.py`:

```python
from .celery import app as celery_app

__all__ = ("celery_app",)
```

In `submissions/tasks.py`:

```python
from celery import shared_task
from processing.services import process_submission

@shared_task
def process_submission_task(submission_id: str):
    process_submission(submission_id)
```

Add Celery settings:

```python
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
```

Draft `docker-compose.yml`:

```yaml
services:
  django-web:
    build:
      context: ./backend
    command: python manage.py runserver 0.0.0.0:8000
    ports:
      - "8090:8000"
    env_file:
      - .env
    volumes:
      - ./backend:/app
      - django_media:/app/media
    depends_on:
      - django-db
      - redis

  django-worker:
    build:
      context: ./backend
    command: celery -A config worker -l info
    env_file:
      - .env
    volumes:
      - ./backend:/app
      - django_media:/app/media
    depends_on:
      - django-db
      - redis

  django-db:
    image: postgres:16
    environment:
      POSTGRES_DB: av_evaluation
      POSTGRES_USER: av_user
      POSTGRES_PASSWORD: av_password
    volumes:
      - django_db:/var/lib/postgresql/data

  redis:
    image: redis:7

volumes:
  django_db:
  django_media:
```

The upload view should queue work with:

```python
process_submission_task.delay(str(submission.id))
```

Acceptance check:

```bash
docker compose up --build
```

The web and worker containers should both start without crashing.

## 8. Test Django Independently on Port `8090`

Create `.env` from `.env.example`:

```bash
cd /home/saimon/projects/av-evaluation/Docker-django-stack
cp .env.example .env
```

Minimum development values:

```text
DEBUG=true
SECRET_KEY=dev-django-secret-change-me
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
DATABASE_URL=postgres://av_user:av_password@django-db:5432/av_evaluation
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
DEFAULT_FROM_EMAIL=no-reply@localhost
EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend
EMAIL_FILE_PATH=/app/tmp_emails
OLLAMA_URL=http://host.docker.internal:11434/api/generate
OLLAMA_MODEL=qwen2.5:latest
TRANSCRIPTION_URL=
WHISPER_MODEL_SIZE=medium
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

Start the stack:

```bash
docker compose up --build
```

Run migrations:

```bash
docker compose exec django-web python manage.py migrate
```

Create an admin user:

```bash
docker compose exec django-web python manage.py createsuperuser
```

Open:

```text
http://localhost:8090/
http://localhost:8090/admin/
http://localhost:8090/accounts/login/
```

Development acceptance checklist:

- Django responds on `http://localhost:8090`
- admin login works
- admin can create a student user
- student invite email is written to `tmp_emails`
- password-set link allows the student to create a password
- student can log in with email
- authenticated student can reach the upload API
- upload creates a queued submission
- worker picks up the submission task

At this point the Django stack is independent from the current Flask stack and can be developed without changing the existing production deployment.
