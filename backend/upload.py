import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

import requests
from flask import Blueprint, jsonify, request, session

from auth import login_required
from database import get_db
from processing import (
    ALLOWED_EXTENSIONS,
    MAX_DURATION_SECONDS,
    UPLOADS_DIR,
    build_stored_filename,
    compare_transcripts,
    ensure_uploads_dir,
    get_max_bytes_for_extension,
    get_media_duration_seconds,
    normalise_submission_source,
)
from queueing import enqueue_submission_job

logger = logging.getLogger(__name__)

upload_bp = Blueprint('upload', __name__)


def _submission_response(row):
    return {
        'submission_id': row['submission_id'],
        'original_filename': row['original_filename'],
        'has_media': bool(row['stored_filename']),
        'duration_seconds': row['duration_seconds'],
        'submission_source': row['submission_source'],
        'status': row['status'],
        'error_message': row['error_message'],
        'transcript': row['transcript'],
        'feedback': row['feedback'],
        'submitted_at': row['submitted_at'],
    }


def _fetch_submission_for_user(submission_id: str, user_id: str):
    with get_db() as conn:
        row = conn.execute(
            '''SELECT submission_id, user_id, original_filename, stored_filename,
                      duration_seconds, submission_source, status, error_message,
                      transcript, feedback, submitted_at
               FROM submissions
               WHERE submission_id = ?''',
            (submission_id,),
        ).fetchone()

    if not row or row['user_id'] != user_id:
        return None
    return row


def _insert_submission(
    submission_id: str,
    original_filename: str,
    stored_filename: str,
    duration_seconds: float,
    submission_source: str,
    submitted_at: str,
) -> None:
    with get_db() as conn:
        conn.execute(
            '''INSERT INTO submissions
               (submission_id, user_id, original_filename, stored_filename,
                duration_seconds, submission_source, status, error_message,
                transcript, feedback, submitted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                submission_id,
                session['user_id'],
                original_filename,
                stored_filename,
                duration_seconds,
                submission_source,
                'queued',
                None,
                None,
                None,
                submitted_at,
            ),
        )


def _mark_submission_failed(submission_id: str, error_message: str) -> None:
    with get_db() as conn:
        conn.execute(
            '''UPDATE submissions
               SET status = ?, error_message = ?
               WHERE submission_id = ?''',
            ('failed', error_message, submission_id),
        )


@upload_bp.route('/submissions', methods=['GET'])
@login_required
def list_submissions():
    with get_db() as conn:
        rows = conn.execute(
            '''SELECT submission_id, original_filename, stored_filename,
                      duration_seconds, submission_source, status, error_message,
                      submitted_at
               FROM submissions
               WHERE user_id = ?
               ORDER BY submitted_at DESC''',
            (session['user_id'],)
        ).fetchall()

    return jsonify([
        {
            'submission_id': row['submission_id'],
            'original_filename': row['original_filename'],
            'has_media': bool(row['stored_filename']),
            'duration_seconds': row['duration_seconds'],
            'submission_source': row['submission_source'],
            'status': row['status'],
            'error_message': row['error_message'],
            'submitted_at': row['submitted_at'],
        }
        for row in rows
    ])


@upload_bp.route('/submissions/<submission_id>', methods=['GET'])
@login_required
def get_submission(submission_id):
    row = _fetch_submission_for_user(submission_id, session['user_id'])
    if not row:
        return jsonify({'error': 'Submission not found'}), 404
    return jsonify(_submission_response(row))


@upload_bp.route('/submissions/compare', methods=['POST'])
@login_required
def compare_submissions():
    data = request.get_json(silent=True) or {}
    submission_ids = data.get('submission_ids')

    if not isinstance(submission_ids, list) or len(submission_ids) != 2:
        return jsonify({'error': 'Exactly two submission IDs are required.'}), 400

    submission_ids = [str(item).strip() for item in submission_ids]
    if not submission_ids[0] or not submission_ids[1] or submission_ids[0] == submission_ids[1]:
        return jsonify({'error': 'Select two different submissions to compare.'}), 400

    rows = []
    for submission_id in submission_ids:
        row = _fetch_submission_for_user(submission_id, session['user_id'])
        if not row:
            return jsonify({'error': 'One or more submissions could not be found.'}), 404
        rows.append(row)

    rows.sort(key=lambda row: row['submitted_at'] or '')

    missing_transcript = next((row for row in rows if not (row['transcript'] or '').strip()), None)
    if missing_transcript:
        return jsonify({
            'error': 'Both submissions must have completed transcripts before they can be compared.'
        }), 422

    try:
        comparison = compare_transcripts(
            rows[0]['transcript'],
            rows[1]['transcript'],
            rows[0]['original_filename'] or 'Earlier submission',
            rows[1]['original_filename'] or 'Later submission',
        )
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Could not connect to the AI model. Please try again later.'}), 503
    except requests.exceptions.Timeout:
        return jsonify({'error': 'The AI model took too long to respond. Please try again later.'}), 504
    except requests.exceptions.RequestException:
        logger.exception('Failed to compare submissions %s and %s', submission_ids[0], submission_ids[1])
        return jsonify({'error': 'Could not compare the selected submissions. Please try again later.'}), 502

    return jsonify({
        'comparison': comparison,
        'submissions': [
            {
                'submission_id': row['submission_id'],
                'original_filename': row['original_filename'],
                'duration_seconds': row['duration_seconds'],
                'submission_source': row['submission_source'],
                'status': row['status'],
                'submitted_at': row['submitted_at'],
            }
            for row in rows
        ],
    })


@upload_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': 'Only MP3, M4A, MP4, and WebM files are accepted'}), 415

    max_bytes = get_max_bytes_for_extension(ext)
    max_mb = max_bytes // (1024 * 1024)
    submission_source = normalise_submission_source(request.form.get('submission_source'))

    content_length = request.content_length
    if content_length and content_length > max_bytes:
        return jsonify({'error': f'{ext.upper()} files must be under {max_mb} MB'}), 413

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=f'.{ext}')
    os.close(tmp_fd)

    stored_filename = ''

    try:
        file.save(tmp_path)

        actual_size = os.path.getsize(tmp_path)
        if actual_size > max_bytes:
            return jsonify({'error': f'{ext.upper()} files must be under {max_mb} MB'}), 413

        try:
            duration_seconds = get_media_duration_seconds(tmp_path)
        except RuntimeError as exc:
            logger.error('Media duration validation unavailable: %s', exc)
            return jsonify({
                'error': 'Media duration validation is unavailable on the server.'
            }), 500
        except ValueError as exc:
            logger.warning('Media duration validation failed: %s', exc)
            return jsonify({
                'error': 'Could not determine media duration. Please upload a standard MP3, M4A, MP4, or WebM file.'
            }), 422

        if duration_seconds > MAX_DURATION_SECONDS:
            return jsonify({
                'error': 'Recordings must be 15 minutes or less.'
            }), 422

        submission_id = str(uuid.uuid4())
        submitted_at = datetime.now(timezone.utc).isoformat()
        ensure_uploads_dir()
        stored_filename = build_stored_filename(file.filename, ext)
        target_path = os.path.join(UPLOADS_DIR, stored_filename)
        shutil.move(tmp_path, target_path)
        tmp_path = ''

        try:
            _insert_submission(
                submission_id,
                file.filename,
                stored_filename,
                duration_seconds,
                submission_source,
                submitted_at,
            )
        except Exception:
            try:
                os.unlink(target_path)
            except OSError:
                pass
            raise

        try:
            enqueue_submission_job(submission_id)
        except Exception as exc:
            logger.error('Failed to queue submission %s: %s', submission_id, exc, exc_info=True)
            _mark_submission_failed(
                submission_id,
                'The submission could not be queued for processing. Please try again.',
            )
            return jsonify({
                'error': 'Could not queue the submission for processing. Please try again.'
            }), 503

        row = _fetch_submission_for_user(submission_id, session['user_id'])
        if not row:
            return jsonify({'error': 'Submission was created but could not be reloaded.'}), 500

        status_code = 202 if row['status'] in {'queued', 'processing'} else 200
        return jsonify(_submission_response(row)), status_code

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
