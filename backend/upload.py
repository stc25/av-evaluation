import logging
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone

import requests
from faster_whisper import WhisperModel
from flask import Blueprint, jsonify, request, session

from auth import login_required
from database import get_db

logger = logging.getLogger(__name__)

upload_bp = Blueprint('upload', __name__)

ALLOWED_EXTENSIONS = {'mp3', 'mp4', 'webm'}
MAX_MP3_BYTES = 30 * 1024 * 1024
MAX_MP4_BYTES = 300 * 1024 * 1024
MAX_DURATION_SECONDS = 15 * 60

#OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434/api/generate')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://131.111.168.123:11434/api/generate')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:latest')
WHISPER_MODEL_SIZE = os.environ.get('WHISPER_MODEL_SIZE', 'medium')
WHISPER_DEVICE = os.environ.get('WHISPER_DEVICE', 'auto')
WHISPER_COMPUTE_TYPE = os.environ.get('WHISPER_COMPUTE_TYPE', 'int8')
UPLOADS_DIR = os.environ.get(
    'UPLOADS_DIR',
    os.path.join(os.path.dirname(__file__), 'instance', 'uploads'),
)

FEEDBACK_PROMPT = (
    'You are an experienced presentation coach evaluating a postgraduate research '
    'presentation. The speaker is a non-native English speaker (IELTS 8-9 level) '
    'presenting their intended research to fellow postgraduate students across '
    'different disciplines.\n\n'
    'Provide a concise evaluation (maximum 300 words) covering:\n\n'
    '1. **Structure**: Assess the overall organization and flow of the presentation\n'
    '2. **Tone & Style**: Evaluate appropriateness for an interdisciplinary '
    'postgraduate audience\n'
    '3. **Clarity**: Analyze how clearly ideas and research intentions are communicated\n'
    '4. **Cohesion**: Examine logical connections between sections and ideas\n'
    '5. **Language**: Evaluate grammar, vocabulary, and academic style accuracy\n\n'
    'After the evaluation, provide 2-3 specific, actionable suggestions for improvement.\n\n'
    'Format your response using markdown with clear headings. Do not include any '
    'preamble or concluding remarks - begin directly with the evaluation.\n\n'
    'TRANSCRIPT:\n\n'
    '{transcript}'
)

_whisper_model = None


def _get_whisper_model() -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
    return _whisper_model


def _transcribe(file_path: str) -> str:
    model = _get_whisper_model()
    segments, _info = model.transcribe(file_path)
    return ' '.join(segment.text.strip() for segment in segments if segment.text).strip()


def _get_feedback(transcript: str) -> str:
    prompt = FEEDBACK_PROMPT.format(transcript=transcript)
    resp = requests.post(
        OLLAMA_URL,
        json={'model': OLLAMA_MODEL, 'prompt': prompt, 'stream': False},
        timeout=300,
    )
    resp.raise_for_status()
    raw = resp.json()['response']
    return re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()


def _ensure_uploads_dir() -> None:
    os.makedirs(UPLOADS_DIR, exist_ok=True)


def _build_stored_filename(original_filename: str, ext: str) -> str:
    safe_stem = os.path.splitext(os.path.basename(original_filename))[0]
    safe_stem = re.sub(r'[^A-Za-z0-9._-]+', '-', safe_stem).strip('._-')
    if not safe_stem:
        safe_stem = 'submission'
    return f'{uuid.uuid4()}-{safe_stem[:80]}.{ext}'


def _get_media_duration_seconds(file_path: str) -> float:
    try:
        proc = subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-show_entries',
                'format=duration',
                '-print_format',
                'json',
                file_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError('ffprobe is not installed on the server') from exc

    if proc.returncode != 0:
        raise ValueError(proc.stderr.strip() or 'ffprobe could not read the media file')

    try:
        payload = json.loads(proc.stdout)
        duration_raw = payload.get('format', {}).get('duration')
        duration = float(duration_raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError('ffprobe did not return a valid media duration') from exc

    if duration <= 0:
        raise ValueError('Media duration must be greater than zero')

    return duration


def _normalise_submission_source(raw_source: str | None) -> str:
    if raw_source == 'recorded':
        return 'recorded'
    return 'upload'


@upload_bp.route('/submissions', methods=['GET'])
@login_required
def list_submissions():
    with get_db() as conn:
        rows = conn.execute(
            '''SELECT submission_id, original_filename, stored_filename,
                      duration_seconds, submission_source, submitted_at
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
            'submitted_at': row['submitted_at'],
        }
        for row in rows
    ])


@upload_bp.route('/submissions/<submission_id>', methods=['GET'])
@login_required
def get_submission(submission_id):
    with get_db() as conn:
        row = conn.execute(
            '''SELECT submission_id, user_id, original_filename, stored_filename,
                      duration_seconds, submission_source, transcript, feedback,
                      submitted_at
               FROM submissions
               WHERE submission_id = ?''',
            (submission_id,)
        ).fetchone()

    if not row or row['user_id'] != session['user_id']:
        return jsonify({'error': 'Submission not found'}), 404

    return jsonify({
        'submission_id': row['submission_id'],
        'original_filename': row['original_filename'],
        'has_media': bool(row['stored_filename']),
        'duration_seconds': row['duration_seconds'],
        'submission_source': row['submission_source'],
        'transcript': row['transcript'],
        'feedback': row['feedback'],
        'submitted_at': row['submitted_at'],
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
        return jsonify({'error': 'Only MP3, MP4, and WebM files are accepted'}), 415

    max_bytes = MAX_MP3_BYTES if ext == 'mp3' else MAX_MP4_BYTES
    max_mb = max_bytes // (1024 * 1024)
    submission_source = _normalise_submission_source(request.form.get('submission_source'))

    content_length = request.content_length
    if content_length and content_length > max_bytes:
        return jsonify({'error': f'{ext.upper()} files must be under {max_mb} MB'}), 413

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=f'.{ext}')
    os.close(tmp_fd)

    stored_filename = ''
    duration_seconds = 0.0

    try:
        file.save(tmp_path)

        actual_size = os.path.getsize(tmp_path)
        if actual_size > max_bytes:
            return jsonify({'error': f'{ext.upper()} files must be under {max_mb} MB'}), 413

        try:
            duration_seconds = _get_media_duration_seconds(tmp_path)
        except RuntimeError as exc:
            logger.error('Media duration validation unavailable: %s', exc)
            return jsonify({
                'error': 'Media duration validation is unavailable on the server.'
            }), 500
        except ValueError as exc:
            logger.warning('Media duration validation failed: %s', exc)
            return jsonify({
                'error': 'Could not determine media duration. Please upload a standard MP3, MP4, or WebM file.'
            }), 422

        if duration_seconds > MAX_DURATION_SECONDS:
            return jsonify({
                'error': 'Recordings must be 15 minutes or less.'
            }), 422

        try:
            transcript = _transcribe(tmp_path)
        except Exception as exc:
            logger.error('Transcription error: %s', exc, exc_info=True)
            return jsonify({
                'error': 'Transcription failed. Please check your audio and try again.'
            }), 500

        if not transcript:
            return jsonify({
                'error': 'No speech detected in the file. Please check your audio.'
            }), 422

        try:
            feedback = _get_feedback(transcript)
        except requests.exceptions.ConnectionError:
            return jsonify({
                'error': 'Could not connect to the AI model. Please ensure Ollama is running.'
            }), 503
        except requests.exceptions.Timeout:
            return jsonify({
                'error': 'The AI model took too long to respond. Please try again.'
            }), 504
        except Exception as exc:
            logger.error('Ollama error: %s', exc, exc_info=True)
            return jsonify({'error': 'Failed to generate feedback. Please try again.'}), 500

        submission_id = str(uuid.uuid4())
        submitted_at = datetime.now(timezone.utc).isoformat()
        _ensure_uploads_dir()
        stored_filename = _build_stored_filename(file.filename, ext)
        shutil.copy2(tmp_path, os.path.join(UPLOADS_DIR, stored_filename))

        try:
            with get_db() as conn:
                conn.execute(
                    '''INSERT INTO submissions
                       (submission_id, user_id, original_filename, stored_filename,
                        duration_seconds, submission_source, transcript, feedback,
                        submitted_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        submission_id,
                        session['user_id'],
                        file.filename,
                        stored_filename,
                        duration_seconds,
                        submission_source,
                        transcript,
                        feedback,
                        submitted_at,
                    )
                )
        except Exception:
            try:
                os.unlink(os.path.join(UPLOADS_DIR, stored_filename))
            except OSError:
                pass
            raise

        return jsonify({
            'submission_id': submission_id,
            'original_filename': file.filename,
            'has_media': True,
            'duration_seconds': duration_seconds,
            'submission_source': submission_source,
            'feedback': feedback,
            'submitted_at': submitted_at,
        })

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
