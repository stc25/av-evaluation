from __future__ import annotations

from rq import Connection, Worker

from app.config import get_settings
from app.worker.queue import get_redis_connection


def main() -> None:
    settings = get_settings()
    connection = get_redis_connection()
    with Connection(connection):
        worker = Worker([settings.rq_queue_name])
        worker.work()


if __name__ == "__main__":
    main()
