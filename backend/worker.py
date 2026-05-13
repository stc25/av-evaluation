import logging
import os

from rq import Worker

from queueing import RQ_QUEUE, get_queue_connection

LOG_LEVEL = getattr(logging, os.environ.get('APP_LOG_LEVEL', 'INFO').strip().upper(), logging.INFO)

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)


def main() -> None:
    connection = get_queue_connection()
    worker = Worker([RQ_QUEUE], connection=connection)
    worker.work()


if __name__ == '__main__':
    main()
