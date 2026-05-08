from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_serializer() -> URLSafeSerializer:
    settings = get_settings()
    return URLSafeSerializer(settings.secret_key, salt="av-evaluation-session")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_session_token(payload: dict[str, str | bool]) -> str:
    return get_serializer().dumps(payload)


def decode_session_token(token: str) -> dict[str, str | bool] | None:
    try:
        data = get_serializer().loads(token)
    except BadSignature:
        return None
    return data if isinstance(data, dict) else None
