from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    secret_key: str = "change-me"
    database_url: str = "postgresql+psycopg://app_user:app_password@postgres:5432/av_evaluation"
    redis_url: str = "redis://redis:6379/0"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str | None = None
    whisper_model_size: str = "medium"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    upload_tmp_dir: Path = Path("/tmp/uploads")
    max_upload_mb_mp3: int = 30
    max_upload_mb_mp4: int = 300
    log_level: str = "INFO"
    cors_origins: str = Field(default="http://localhost")
    session_cookie_name: str = "av_eval_session"
    rq_queue_name: str = "default"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_tmp_dir.mkdir(parents=True, exist_ok=True)
    return settings
