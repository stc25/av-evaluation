import json
import logging
import os
import re
import subprocess
import uuid

import requests
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'mp3', 'mp4', 'webm'}
MAX_MP3_BYTES = 30 * 1024 * 1024
MAX_MP4_BYTES = 300 * 1024 * 1024
MAX_DURATION_SECONDS = 15 * 60

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


class SubmissionProcessingError(Exception):
    pass


def get_max_bytes_for_extension(ext: str) -> int:
    return MAX_MP3_BYTES if ext == 'mp3' else MAX_MP4_BYTES


def ensure_uploads_dir() -> None:
    os.makedirs(UPLOADS_DIR, exist_ok=True)


def build_stored_filename(original_filename: str, ext: str) -> str:
    safe_stem = os.path.splitext(os.path.basename(original_filename))[0]
    safe_stem = re.sub(r'[^A-Za-z0-9._-]+', '-', safe_stem).strip('._-')
    if not safe_stem:
        safe_stem = 'submission'
    return f'{uuid.uuid4()}-{safe_stem[:80]}.{ext}'


def get_media_duration_seconds(file_path: str) -> float:
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


def normalise_submission_source(raw_source: str | None) -> str:
    if raw_source == 'recorded':
        return 'recorded'
    return 'upload'


def get_whisper_model() -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
    return _whisper_model


def transcribe(file_path: str) -> str:
    model = get_whisper_model()
    segments, _info = model.transcribe(file_path)
    return ' '.join(segment.text.strip() for segment in segments if segment.text).strip()


def get_feedback(transcript: str) -> str:
    prompt = FEEDBACK_PROMPT.format(transcript=transcript)
    resp = requests.post(
        OLLAMA_URL,
        json={'model': OLLAMA_MODEL, 'prompt': prompt, 'stream': False},
        timeout=300,
    )
    resp.raise_for_status()
    raw = resp.json()['response']
    return re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
