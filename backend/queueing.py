import logging
import os

from redis import Redis
from rq import Queue

logger = logging.getLogger(__name__)

VALKEY_URL = os.environ.get('VALKEY_URL', 'redis://valkey:6379/0')
RQ_QUEUE = os.environ.get('RQ_QUEUE', 'submissions')
QUEUE_SYNC = os.environ.get('QUEUE_SYNC', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}


def get_queue_connection() -> Redis:
    return Redis.from_url(VALKEY_URL)


def get_submission_queue() -> Queue:
    return Queue(RQ_QUEUE, connection=get_queue_connection(), default_timeout=3600)


def enqueue_submission_job(submission_id: str):
    if QUEUE_SYNC:
        from jobs import process_submission_job

        logger.info('QUEUE_SYNC enabled; processing submission %s inline', submission_id)
        process_submission_job(submission_id)
        return None

    queue = get_submission_queue()
    return queue.enqueue('jobs.process_submission_job', submission_id)
