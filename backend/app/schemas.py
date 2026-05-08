from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    user_id: str
    username: str
    cohort_id: str
    is_admin: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    cohort_id: str = ""
    is_admin: bool = False


class JobOut(BaseModel):
    job_id: str
    status: str
    filename: str
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    submission_id: str | None

    model_config = ConfigDict(from_attributes=True)


class UploadResponse(BaseModel):
    job_id: str
    status: str


class SubmissionOut(BaseModel):
    submission_id: str
    user_id: str
    transcript: str | None
    feedback: str | None
    submitted_at: datetime

    model_config = ConfigDict(from_attributes=True)
