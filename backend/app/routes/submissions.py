from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Submission, User
from app.schemas import SubmissionOut

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


@router.get("/{submission_id}", response_model=SubmissionOut)
def get_submission(
    submission_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Submission:
    submission = db.get(Submission, submission_id)
    if submission is None or submission.user_id != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    return submission
