from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_admin_user
from app.models import User
from app.schemas import CreateUserRequest, UserOut
from app.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(_admin: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc())
    return list(db.execute(stmt).scalars().all())


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    _admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> User:
    user = User(
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        cohort_id=payload.cohort_id.strip(),
        is_admin=payload.is_admin,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc
    db.refresh(user)
    return user
