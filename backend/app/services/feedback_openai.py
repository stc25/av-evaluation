from __future__ import annotations

from openai import OpenAI

from app.config import get_settings

FEEDBACK_PROMPT = """You are an experienced presentation coach evaluating a postgraduate research presentation.
The speaker is a non-native English speaker (IELTS 8-9 level) presenting their intended research to fellow postgraduate students across different disciplines.

Provide a concise evaluation (maximum 300 words) covering:

1. Structure
2. Tone & Style
3. Clarity
4. Cohesion
5. Language

After the evaluation, provide 2-3 specific, actionable suggestions for improvement.

Format your response using markdown with clear headings. Do not include any preamble or concluding remarks.

TRANSCRIPT:
{transcript}
"""


def get_client() -> OpenAI:
    settings = get_settings()
    kwargs = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return OpenAI(**kwargs)


def generate_feedback(transcript: str) -> str:
    settings = get_settings()
    client = get_client()
    response = client.responses.create(
        model=settings.openai_model,
        input=FEEDBACK_PROMPT.format(transcript=transcript),
    )
    return response.output_text.strip()
