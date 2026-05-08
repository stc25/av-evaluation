from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import admin, auth, health, jobs, submissions, upload

settings = get_settings()

app = FastAPI(title="AV Evaluation API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(upload.router)
app.include_router(jobs.router)
app.include_router(submissions.router)


@app.get("/api")
def api_root() -> dict[str, str]:
    return {"status": "ok"}
