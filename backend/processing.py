import json
import logging
import os
import re
import subprocess
import uuid

import av
import requests
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'mp3', 'mp4', 'webm', 'm4a'}
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_MP4_BYTES = 300 * 1024 * 1024
MAX_DURATION_SECONDS = 15 * 60

OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://131.111.168.123:11434/api/generate')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:latest')
TRANSCRIPTION_URL = os.environ.get('TRANSCRIPTION_URL', '').strip()
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

COMPARISON_PROMPT = (
    'You are an experienced presentation coach comparing two postgraduate research '
    'presentation transcripts. The speakers are non-native English speakers (IELTS 8-9 level) '
    'presenting their intended research to fellow postgraduate students across different disciplines.\n\n'
    'Assess only the transcript text. Do not evaluate vocal delivery, pronunciation, slides, body language, '
    'timing, or audience interaction.\n\n'
    'Treat the first transcript as the older presentation and the second transcript as the latest presentation.\n'
    'Do not use any part of the filenames in the response. Refer to them only as "the older presentation" '
    'and "the latest presentation".\n\n'
    'Your task is to:\n'
    '1. Compare the latest presentation against the older presentation baseline.\n'
    '2. Judge whether the latest presentation is stronger overall.\n'
    '3. Identify the main areas of improvement, if any.\n'
    '4. Identify any regressions where the latest presentation is weaker.\n'
    '5. Provide concise, actionable advice focused primarily on the weaker submission.\n\n'
    'Assess the submissions using these criteria:\n'
    '- **Structure:** overall organization and flow\n'
    '- **Tone & Style:** appropriateness for an interdisciplinary postgraduate audience\n'
    '- **Clarity:** how clearly ideas and research intentions are communicated\n'
    '- **Cohesion:** logical connections between sections and ideas\n'
    '- **Language:** grammar, vocabulary, and academic style accuracy\n\n'
    'Output requirements:\n'
    '- Maximum 400 words\n'
    '- Use markdown with clear headings\n'
    '- Do not include any preamble or concluding remarks\n'
    '- Begin directly with the progress comparison\n'
    '- Use only these headings:\n'
    '  - `Progress Comparison`\n'
    '  - `Suggestions for Improvement`\n\n'
    'In the `Progress Comparison` section:\n'
    '- state clearly whether the latest presentation is stronger overall\n'
    '- explain the main reasons for that judgment\n'
    '- note whether the latest presentation improves on the older presentation\n'
    '- mention any clear regressions in the latest presentation\n\n'
    'In the `Suggestions for Improvement` section:\n'
    '- provide 2-3 specific, actionable suggestions\n'
    '- focus primarily on the weaker transcript\n'
    '- if both are of very similar quality, give suggestions that would strengthen both\n\n'
    'Older Presentation ({earlier_label}):\n'
    '{earlier_transcript}\n\n'
    'Latest Presentation ({later_label}):\n'
    '{later_transcript}'
)

_whisper_model = None


class SubmissionProcessingError(Exception):
    pass


def get_max_bytes_for_extension(ext: str) -> int:
    return MAX_AUDIO_BYTES if ext in {'mp3', 'm4a'} else MAX_MP4_BYTES


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
                'format=duration:stream=duration',
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
    except json.JSONDecodeError as exc:
        raise ValueError('ffprobe did not return valid JSON') from exc

    duration = _extract_duration_from_ffprobe_payload(payload)
    if duration is None:
        duration = _extract_duration_with_pyav(file_path)

    if duration is None or duration <= 0:
        raise ValueError('Media duration must be greater than zero')

    return duration


def _parse_duration_value(raw_value):
    try:
        duration = float(raw_value)
    except (TypeError, ValueError):
        return None
    if duration <= 0:
        return None
    return duration


def _extract_duration_from_ffprobe_payload(payload: dict) -> float | None:
    format_duration = _parse_duration_value(payload.get('format', {}).get('duration'))
    if format_duration is not None:
        return format_duration

    stream_durations = [
        duration
        for duration in (
            _parse_duration_value(stream.get('duration'))
            for stream in payload.get('streams', [])
        )
        if duration is not None
    ]
    if stream_durations:
        return max(stream_durations)

    return None


def _extract_duration_with_pyav(file_path: str) -> float | None:
    try:
        with av.open(file_path) as container:
            if container.duration:
                duration = float(container.duration / av.time_base)
                if duration > 0:
                    return duration

            stream_durations = []
            for stream in container.streams:
                if stream.duration is not None and stream.time_base is not None:
                    duration = float(stream.duration * stream.time_base)
                    if duration > 0:
                        stream_durations.append(duration)

            if stream_durations:
                return max(stream_durations)
    except Exception:
        return None

    return None


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


def transcribe_remote(file_path: str) -> str:
    file_name = os.path.basename(file_path)

    try:
        with open(file_path, 'rb') as handle:
            resp = requests.post(
                TRANSCRIPTION_URL,
                files={'file': (file_name, handle)},
                timeout=1800,
            )
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise SubmissionProcessingError(
            'Could not connect to the remote transcription service. Please try again later.'
        ) from exc

    try:
        payload = resp.json()
    except ValueError as exc:
        raise SubmissionProcessingError(
            'Remote transcription service returned an invalid response.'
        ) from exc

    transcript = (payload.get('transcript') or '').strip()
    if not transcript:
        raise SubmissionProcessingError(
            'Remote transcription service returned no transcript.'
        )

    elapsed = payload.get('elapsed_seconds')
    model = payload.get('model') or 'remote'
    if elapsed is not None:
        logger.info(
            'Remote transcription completed file=%s model=%s elapsed_seconds=%s',
            file_name,
            model,
            elapsed,
        )
    else:
        logger.info(
            'Remote transcription completed file=%s model=%s',
            file_name,
            model,
        )

    return transcript


def transcribe(file_path: str) -> str:
    if TRANSCRIPTION_URL:
        return transcribe_remote(file_path)

    model = get_whisper_model()
    segments, _info = model.transcribe(
        file_path,
        language='en',
        beam_size=1,
        vad_filter=True,
    )
    return ' '.join(segment.text.strip() for segment in segments if segment.text).strip()


def get_feedback(transcript: str) -> str:
    prompt = FEEDBACK_PROMPT.format(transcript=transcript)
    return _generate_with_ollama(prompt)


def _clean_comparison_label(label: str) -> str:
    cleaned = re.sub(r'\s+', ' ', label).strip()
    return cleaned or 'Submission'


def compare_transcripts(
    earlier_transcript: str,
    later_transcript: str,
    earlier_label: str,
    later_label: str,
) -> str:
    prompt = COMPARISON_PROMPT.format(
        earlier_label=_clean_comparison_label(earlier_label),
        later_label=_clean_comparison_label(later_label),
        earlier_transcript=earlier_transcript,
        later_transcript=later_transcript,
    )
    return _generate_with_ollama(prompt)


def _generate_with_ollama(prompt: str) -> str:
    resp = requests.post(
        OLLAMA_URL,
        json={'model': OLLAMA_MODEL, 'prompt': prompt, 'stream': False},
        timeout=300,
    )
    resp.raise_for_status()
    raw = resp.json()['response']
    return re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
