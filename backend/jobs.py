import logging
import os
from typing import Any

import requests

from database import get_db
from processing import SubmissionProcessingError, UPLOADS_DIR, get_feedback, transcribe

logger = logging.getLogger(__name__)


def _set_submission_status(
    submission_id: str,
    status: str,
    *,
    transcript: str | None = None,
    feedback: str | None = None,
    error_message: str | None = None,
) -> None:
    with get_db() as conn:
        conn.execute(
            '''UPDATE submissions
               SET status = ?, transcript = ?, feedback = ?, error_message = ?
               WHERE submission_id = ?''',
            (status, transcript, feedback, error_message, submission_id),
        )


def _load_submission(submission_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            '''SELECT submission_id, stored_filename
               FROM submissions
               WHERE submission_id = ?''',
            (submission_id,),
        ).fetchone()
    return dict(row) if row else None


def process_submission_job(submission_id: str) -> None:
    submission = _load_submission(submission_id)
    if not submission:
        logger.warning('Submission %s was not found for background processing', submission_id)
        return

    stored_filename = submission.get('stored_filename') or ''
    file_path = os.path.join(UPLOADS_DIR, stored_filename)
    _set_submission_status(submission_id, 'processing')

    try:
        if not stored_filename or not os.path.exists(file_path):
            raise SubmissionProcessingError(
                'The stored media file could not be found. Please upload the presentation again.'
            )

        transcript = transcribe(file_path)
        if not transcript:
            raise SubmissionProcessingError(
                'No speech was detected in the file. Please check your audio and try again.'
            )

        feedback = get_feedback(transcript)
        _set_submission_status(
            submission_id,
            'completed',
            transcript=transcript,
            feedback=feedback,
            error_message=None,
        )
    except SubmissionProcessingError as exc:
        logger.warning('Submission %s failed during processing: %s', submission_id, exc)
        _set_submission_status(submission_id, 'failed', error_message=str(exc))
    except requests.exceptions.ConnectionError:
        message = 'Could not connect to the AI model. Please try again later.'
        logger.warning('Submission %s could not reach Ollama', submission_id)
        _set_submission_status(submission_id, 'failed', error_message=message)
    except requests.exceptions.Timeout:
        message = 'The AI model took too long to respond. Please try again later.'
        logger.warning('Submission %s timed out while waiting for Ollama', submission_id)
        _set_submission_status(submission_id, 'failed', error_message=message)
    except Exception as exc:
        logger.error('Unexpected submission processing error for %s: %s', submission_id, exc, exc_info=True)
        _set_submission_status(
            submission_id,
            'failed',
            error_message='Feedback generation failed. Please try again later.',
        )
