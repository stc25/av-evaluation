from __future__ import annotations

from redis import Redis
from rq import Queue

from app.config import get_settings


def get_redis_connection() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url)


def get_queue() -> Queue:
    settings = get_settings()
    return Queue(settings.rq_queue_name, connection=get_redis_connection())


def enqueue_upload_job(job_id: str) -> None:
    queue = get_queue()
    queue.enqueue("app.worker.tasks.process_upload_job", job_id)
