"""StructuredOutputParser — typed LLM output validation (ADR-008)."""

from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class StructuredOutputParser:
    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    def inject_schema(self, system_prompt: str, result_type: type[BaseModel]) -> str:
        schema_str = json.dumps(result_type.model_json_schema(), indent=2)
        instruction = (
            "\n\n## Required Output Format\n"
            "You MUST respond with valid JSON matching this schema. "
            "Do NOT include any text before or after the JSON.\n"
            f"```json\n{schema_str}\n```"
        )
        return system_prompt + instruction

    def parse(self, raw: str, result_type: type[T]) -> T:
        extracted = _extract_json(raw)
        if extracted is None:
            raise ValueError(
                f"Could not extract JSON from response. Raw output starts with: {raw[:200]!r}"
            )
        return result_type.model_validate_json(extracted)

    def format_retry_context(self, error: ValidationError | ValueError) -> str:
        if isinstance(error, ValidationError):
            details = [
                f"  - {' → '.join(str(x) for x in e['loc'])}: {e['msg']} (type: {e['type']})"
                for e in error.errors()
            ]
            return (
                "Your previous response had validation errors. "
                "Please fix these issues and respond with valid JSON only:\n" + "\n".join(details)
            )
        return (
            f"Your previous response could not be parsed as JSON. "
            f"Error: {error}\n"
            f"Please respond with ONLY valid JSON matching the required schema."
        )


def _extract_json(text: str) -> str | None:
    text = text.strip()
    if text.startswith(("{", "[")):
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass
    m = _JSON_BLOCK_RE.search(text)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass
    m = _JSON_OBJECT_RE.search(text)
    if m:
        candidate = m.group(0)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass
    return None
