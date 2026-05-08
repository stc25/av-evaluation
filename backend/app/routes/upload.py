from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Job, User
from app.schemas import UploadResponse
from app.services.storage import save_upload
from app.worker.queue import enqueue_upload_job

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {"mp3", "mp4"}


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UploadResponse:
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only MP3 and MP4 files are accepted")

    saved_path = save_upload(file)
    job = Job(
        user_id=current_user.user_id,
        status="queued",
        upload_path=str(saved_path),
        filename=filename,
        content_type=file.content_type,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    enqueue_upload_job(job.job_id)
    return UploadResponse(job_id=job.job_id, status=job.status)
