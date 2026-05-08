from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Job, Submission
from app.services.feedback_openai import generate_feedback
from app.services.storage import delete_upload
from app.services.transcription import transcribe_media


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def process_upload_job(job_id: str) -> None:
    db: Session = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return

        job.status = "processing"
        job.started_at = utc_now()
        db.commit()

        transcript = transcribe_media(job.upload_path)
        feedback = generate_feedback(transcript)

        submission = Submission(
            user_id=job.user_id,
            transcript=transcript,
            feedback=feedback,
        )
        db.add(submission)
        db.flush()

        job.status = "completed"
        job.submission_id = submission.submission_id
        job.finished_at = utc_now()
        db.commit()
    except Exception as exc:
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = utc_now()
            db.commit()
        raise
    finally:
        job = db.get(Job, job_id)
        if job is not None and job.upload_path:
            delete_upload(job.upload_path)
        db.close()
