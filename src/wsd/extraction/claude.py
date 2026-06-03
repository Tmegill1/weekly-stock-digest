import json
import anthropic
from wsd.config import Settings

_EXTRACTION_PROMPT = """You are extracting a structured financial event from an SEC filing section.

Filing section text:
{text}

Return a JSON object with these exact fields, or the string null if no clear event can be identified:
{{
  "event_code": one of [{valid_codes}],
  "sentiment": "positive" or "negative" or "neutral",
  "magnitude": null or a number (deal value in $M, EPS beat %, etc.),
  "details": {{}}
}}

Return only valid JSON or the word null. No explanation, no markdown.
"""

_8K_CODES = [
    "acquisition_announced", "merger_announced", "divestiture_announced",
    "ceo_change", "cfo_change", "executive_change_other",
    "buyback_announced", "dividend_change",
    "guidance_raised", "guidance_lowered", "guidance_initiated",
]

_GUIDANCE_CODES = ["guidance_raised", "guidance_lowered", "guidance_initiated"]


def extract_event_from_text(
    section_text: str,
    valid_codes: list[str],
    settings: Settings,
) -> dict | None:
    """Call Claude Haiku to extract a structured event from free text. Returns dict or None."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    prompt = _EXTRACTION_PROMPT.format(
        text=section_text[:3000],
        valid_codes=", ".join(f'"{c}"' for c in valid_codes),
    )
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.lower() == "null":
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, Exception) as exc:
        print(f"  WARNING: Claude extraction failed: {exc}")
        return None


def extract_8k_event(section_text: str, settings: Settings) -> dict | None:
    return extract_event_from_text(section_text, _8K_CODES, settings)


def extract_guidance_event(section_text: str, settings: Settings) -> dict | None:
    return extract_event_from_text(section_text, _GUIDANCE_CODES, settings)
