from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import get_settings


def save_upload(file: UploadFile) -> Path:
    settings = get_settings()
    suffix = Path(file.filename or "upload.bin").suffix
    target = settings.upload_tmp_dir / f"{uuid.uuid4()}{suffix}"
    with target.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    return target


def delete_upload(path: str | Path) -> None:
    target = Path(path)
    if target.exists():
        target.unlink()
