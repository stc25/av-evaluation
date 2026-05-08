from __future__ import annotations

from functools import lru_cache

from faster_whisper import WhisperModel

from app.config import get_settings


@lru_cache
def get_whisper_model() -> WhisperModel:
    settings = get_settings()
    return WhisperModel(
        settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


def transcribe_media(file_path: str) -> str:
    model = get_whisper_model()
    segments, _info = model.transcribe(file_path)
    return " ".join(segment.text.strip() for segment in segments if segment.text).strip()
