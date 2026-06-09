# Cambridge OIDC Login Workflow for the Django Stack

This document describes a potential workflow for adding Cambridge University account login to the new Django stack.

The intended login policy is:

- users do not receive invite emails
- users do not set local passwords
- users authenticate through Cambridge Entra ID / Raven OpenID Connect
- any valid University account can log in
- Django creates or updates a local app profile after successful authentication
- new users default to the `student` role

The current Flask stack can continue running separately while this is built in `Docker-django-stack/`.

## 1. Target User Flow

The student-facing login flow should be:

```text
User opens app
  -> clicks "Sign in with Cambridge"
  -> Django redirects to Cambridge OIDC
  -> user signs in with University account
  -> Cambridge redirects back to Django callback URL
  -> Django validates the OIDC response
  -> Django creates or updates local User record
  -> Django starts a normal session
  -> user lands on AV Evaluation dashboard
```

No email invite is needed.

No local password is needed for students.

The Django admin can still have local superuser access for emergency administration, but this should be treated as an admin-only fallback rather than the normal login path.

## 2. Required Cambridge OIDC Setup

Before coding the integration, register the Django app with the Cambridge / UIS OIDC process.

You will need:

- OIDC client ID
- OIDC client secret
- Cambridge tenant ID
- redirect URI for local development
- redirect URI for production
- logout redirect URI, if required

Cambridge tenant ID:

```text
49a50445-bdfa-4b79-ade3-547b4f3986e9
```

OIDC discovery document:

```text
https://login.microsoftonline.com/49a50445-bdfa-4b79-ade3-547b4f3986e9/.well-known/openid-configuration
```

Suggested local redirect URI:

```text
http://localhost:8090/oidc/callback/
```

Suggested production redirect URI:

```text
https://your-production-domain.cam.ac.uk/oidc/callback/
```

Production redirect URIs should use HTTPS.

## 3. Recommended Django Library

Use `mozilla-django-oidc` for the first implementation.

It is a good fit because:

- the app only needs one institutional OIDC provider
- Django continues to own the local session
- custom user creation and role assignment can be handled in one auth backend
- it avoids adding a larger social-login framework before it is needed

Add to `Docker-django-stack/backend/requirements.txt`:

```text
mozilla-django-oidc
```

If the stack already has a compiled requirements process, add it to the input file and regenerate the locked output.

## 4. Environment Variables

Add these values to `Docker-django-stack/.env.example`:

```text
CAMBRIDGE_OIDC_CLIENT_ID=
CAMBRIDGE_OIDC_CLIENT_SECRET=
CAMBRIDGE_OIDC_DISCOVERY_URL=https://login.microsoftonline.com/49a50445-bdfa-4b79-ade3-547b4f3986e9/.well-known/openid-configuration
CAMBRIDGE_OIDC_SCOPES=openid profile email
CAMBRIDGE_OIDC_VERIFY_SSL=true
CAMBRIDGE_OIDC_CREATE_USERS=true
CAMBRIDGE_OIDC_DEFAULT_ROLE=student
```

For local development, copy `.env.example` to `.env` and fill in the real client values:

```bash
cd /home/saimon/projects/av-evaluation/Docker-django-stack
cp .env.example .env
```

Do not commit real secrets.

## 5. Django Settings

Add the OIDC app to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    ...
    "mozilla_django_oidc",
    "users",
    "submissions",
    "processing",
    "notifications",
]
```

Add the authentication backends:

```python
AUTHENTICATION_BACKENDS = [
    "users.auth.CambridgeOIDCAuthenticationBackend",
    "django.contrib.auth.backends.ModelBackend",
]
```

Keep `ModelBackend` so local superusers can still use the Django admin if needed.

Add OIDC settings:

```python
OIDC_RP_CLIENT_ID = os.getenv("CAMBRIDGE_OIDC_CLIENT_ID", "")
OIDC_RP_CLIENT_SECRET = os.getenv("CAMBRIDGE_OIDC_CLIENT_SECRET", "")
OIDC_OP_DISCOVERY_ENDPOINT = os.getenv(
    "CAMBRIDGE_OIDC_DISCOVERY_URL",
    "https://login.microsoftonline.com/49a50445-bdfa-4b79-ade3-547b4f3986e9/.well-known/openid-configuration",
)
OIDC_RP_SCOPES = os.getenv("CAMBRIDGE_OIDC_SCOPES", "openid profile email")
OIDC_VERIFY_SSL = os.getenv("CAMBRIDGE_OIDC_VERIFY_SSL", "true").lower() == "true"

LOGIN_URL = "oidc_authentication_init"
LOGIN_REDIRECT_URL = "submissions:dashboard"
LOGOUT_REDIRECT_URL = "/"
```

Recommended cookie settings:

```python
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
```

For production:

```python
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

For local HTTP development on `localhost:8090`, those secure-cookie values can be `False`.

## 6. URL Configuration

Add OIDC routes to `config/urls.py`:

```python
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("", include("submissions.urls")),
    path("accounts/", include("users.urls")),
]
```

`mozilla-django-oidc` provides routes such as:

```text
/oidc/authenticate/
/oidc/callback/
```

The app login button can point to:

```text
/oidc/authenticate/
```

## 7. User Model Requirements

The local user model should store OIDC identity details separately from email.

Suggested fields:

```python
class User(AbstractBaseUser, PermissionsMixin):
    class Roles(models.TextChoices):
        STUDENT = "student", "Student"
        ADMIN = "admin", "Admin"

    email = models.EmailField(blank=True)
    upn = models.CharField(max_length=255, unique=True, null=True, blank=True)
    oidc_subject = models.CharField(max_length=255, unique=True, null=True, blank=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=20, choices=Roles.choices, default=Roles.STUDENT)
    cohort_id = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
```

Use a stable OIDC identifier for account linking.

Preferred linking order:

1. `sub` claim, stored as `oidc_subject`
2. `upn` claim, stored as `upn`
3. email only as a display/contact field, not as the primary identity

Do not assume the UPN always looks like a CRSid or always ends in `cam.ac.uk`.

## 8. Custom OIDC Backend

Create `users/auth.py`:

```python
from django.conf import settings
from django.contrib.auth import get_user_model
from mozilla_django_oidc.auth import OIDCAuthenticationBackend


class CambridgeOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    def create_user(self, claims):
        User = get_user_model()

        subject = claims.get("sub")
        upn = claims.get("upn") or claims.get("preferred_username") or ""
        email = claims.get("email") or upn

        user = User.objects.create(
            oidc_subject=subject,
            upn=upn or None,
            email=email or "",
            first_name=claims.get("given_name", ""),
            last_name=claims.get("family_name", ""),
            role=getattr(User.Roles, "STUDENT", "student"),
            is_active=True,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return user

    def update_user(self, user, claims):
        changed_fields = []

        mappings = {
            "first_name": claims.get("given_name", ""),
            "last_name": claims.get("family_name", ""),
            "email": claims.get("email") or claims.get("upn") or claims.get("preferred_username") or "",
        }

        for field, value in mappings.items():
            if value and getattr(user, field) != value:
                setattr(user, field, value)
                changed_fields.append(field)

        upn = claims.get("upn") or claims.get("preferred_username")
        if upn and user.upn != upn:
            user.upn = upn
            changed_fields.append("upn")

        if changed_fields:
            user.save(update_fields=changed_fields)

        return user

    def filter_users_by_claims(self, claims):
        User = get_user_model()
        subject = claims.get("sub")
        upn = claims.get("upn") or claims.get("preferred_username")

        if subject:
            users = User.objects.filter(oidc_subject=subject)
            if users.exists():
                return users

        if upn:
            return User.objects.filter(upn=upn)

        return User.objects.none()
```

This backend allows anyone who successfully authenticates with Cambridge OIDC to get a local user account.

## 9. Login Page

Create a simple Django login page that makes Cambridge login the obvious path.

Suggested routes:

```text
/accounts/login/
/accounts/logout/
```

The login page should contain one primary action:

```html
<a href="{% url 'oidc_authentication_init' %}">Sign in with Cambridge</a>
```

Avoid showing local username/password fields to normal users. If local admin login remains enabled, keep it under `/admin/`.

## 10. Authorisation Policy

The first version can allow every valid Cambridge-authenticated identity into the app.

Default policy:

```text
new OIDC user -> role=student -> dashboard/upload access
```

Admin role should not be assigned automatically.

Admin promotion should be manual:

```text
Django admin -> Users -> select user -> role=admin -> is_staff=true if admin-site access is required
```

Optional later restrictions:

- only allow members of a specific Entra group
- only allow current students
- only allow users with a known CRSid pattern
- use a University Student API lookup before account creation
- allow all University accounts but gate upload access behind a cohort assignment

If any of those rules are added later, implement them in the OIDC backend before creating the user session.

## 11. Docker Compose Changes

The `django-web` service needs the OIDC environment variables.

Example:

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
    depends_on:
      - django-db
      - redis

  django-worker:
    build:
      context: ./backend
    command: celery -A config worker -l info
    env_file:
      - .env
    depends_on:
      - django-db
      - redis
```

The worker does not normally use OIDC directly, but sharing the same `.env` is acceptable for development.

## 12. Local Development Test

Start the stack:

```bash
cd /home/saimon/projects/av-evaluation/Docker-django-stack
docker compose up --build
```

Run migrations:

```bash
docker compose exec django-web python manage.py migrate
```

Create an emergency local admin:

```bash
docker compose exec django-web python manage.py createsuperuser
```

Open:

```text
http://localhost:8090/accounts/login/
```

Click:

```text
Sign in with Cambridge
```

Expected local result:

```text
Cambridge login succeeds
  -> callback returns to Django
  -> local User is created
  -> role is student
  -> user reaches dashboard
```

Check user creation:

```bash
docker compose exec django-web python manage.py shell
```

Then:

```python
from django.contrib.auth import get_user_model
User = get_user_model()
User.objects.values("id", "email", "upn", "oidc_subject", "role", "is_active")
```

## 13. Acceptance Checklist

The OIDC login implementation is ready for the next stage when:

- `http://localhost:8090/accounts/login/` shows the Cambridge login action
- clicking login redirects to Cambridge OIDC
- the callback URL is accepted by the Cambridge app registration
- OIDC token validation succeeds
- a new local Django user is created automatically
- the new user has `role=student`
- no local password is created for the OIDC user
- returning users are linked to the same local account
- logout clears the local Django session
- Django admin remains accessible to a local superuser
- the upload API recognises the OIDC-authenticated Django session

## 14. Production Notes

Before production deployment:

- use HTTPS callback URLs only
- set `SESSION_COOKIE_SECURE=true`
- set `CSRF_COOKIE_SECURE=true`
- set `DEBUG=false`
- store OIDC client secret outside version control
- confirm `ALLOWED_HOSTS`
- confirm `CSRF_TRUSTED_ORIGINS`
- document who can manually promote users to admin
- decide whether "any University account" remains acceptable long term

If the app later needs to restrict access to current students only, do not rely on the fact that a user authenticated with Cambridge OIDC. Add a separate authorisation rule using group membership, a known allowlist, or a trusted University API.
