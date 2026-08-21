"""Coverage for maistro.agents.spec.structured_output (was 0%).

Exercises JSON extraction across raw/fenced/embedded-text forms, parse()
success/failure, schema injection, and retry-context formatting for both
ValidationError and plain ValueError inputs.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ValidationError

from maistro.agents.spec.structured_output import StructuredOutputParser, _extract_json


class _Thing(BaseModel):
    name: str
    count: int = 0


# ─── _extract_json ───────────────────────────────────────────────────────────


def test_extract_json_raw_object() -> None:
    assert _extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_raw_array() -> None:
    assert _extract_json("[1, 2, 3]") == "[1, 2, 3]"


def test_extract_json_strips_surrounding_whitespace_before_check() -> None:
    assert _extract_json('  \n{"a": 1}\n  ') == '{"a": 1}'


def test_extract_json_fenced_with_json_label() -> None:
    text = '```json\n{"a": 1}\n```'
    assert _extract_json(text) == '{"a": 1}'


def test_extract_json_fenced_without_label() -> None:
    text = '```\n{"a": 1}\n```'
    assert _extract_json(text) == '{"a": 1}'


def test_extract_json_object_embedded_in_prose() -> None:
    text = 'Here is the result:\n{"a": 1}\nThanks!'
    assert _extract_json(text) == '{"a": 1}'


def test_extract_json_invalid_raw_falls_through_to_other_strategies() -> None:
    # Starts with "{" but isn't valid JSON on its own; no fence; the greedy
    # _JSON_OBJECT_RE still matches because the malformed prefix has braces.
    text = '{not json} but here: {"a": 1}'
    # The greedy regex `\{.*\}` spans from the first "{" to the last "}",
    # producing '{not json} but here: {"a": 1}' which is itself not valid
    # JSON -- so this should fail to extract.
    assert _extract_json(text) is None


def test_extract_json_no_json_anywhere_returns_none() -> None:
    assert _extract_json("just plain text, no braces") is None


def test_extract_json_fenced_block_with_invalid_json_falls_through() -> None:
    # Fenced content isn't valid JSON, and no bare {...} exists either.
    text = "```\nnot valid json\n```"
    assert _extract_json(text) is None


def test_extract_json_prefers_fenced_block_over_loose_object_when_both_present() -> None:
    text = 'noise {"loose": 1} more noise\n```json\n{"fenced": 2}\n```'
    assert _extract_json(text) == '{"fenced": 2}'


def test_extract_json_empty_string_returns_none() -> None:
    assert _extract_json("") is None


# ─── StructuredOutputParser.parse() ──────────────────────────────────────────


def test_parse_success() -> None:
    parser = StructuredOutputParser()
    result = parser.parse('{"name": "x", "count": 3}', _Thing)
    assert result == _Thing(name="x", count=3)


def test_parse_success_from_fenced_block() -> None:
    parser = StructuredOutputParser()
    raw = '```json\n{"name": "y"}\n```'
    result = parser.parse(raw, _Thing)
    assert result.name == "y"
    assert result.count == 0


def test_parse_raises_value_error_when_no_json_extractable() -> None:
    parser = StructuredOutputParser()
    with pytest.raises(ValueError, match="Could not extract JSON"):
        parser.parse("no json here", _Thing)


def test_parse_error_message_includes_truncated_raw_prefix() -> None:
    parser = StructuredOutputParser()
    long_text = "x" * 300
    with pytest.raises(ValueError) as exc_info:
        parser.parse(long_text, _Thing)
    # Raw output is truncated to 200 chars in the error message.
    assert "x" * 200 in str(exc_info.value)
    assert "x" * 201 not in str(exc_info.value)


def test_parse_raises_validation_error_for_schema_mismatch() -> None:
    parser = StructuredOutputParser()
    with pytest.raises(ValidationError):
        parser.parse('{"count": 3}', _Thing)  # missing required "name"


# ─── inject_schema() ──────────────────────────────────────────────────────────


def test_inject_schema_appends_schema_block() -> None:
    parser = StructuredOutputParser()
    result = parser.inject_schema("You are an assistant.", _Thing)
    assert result.startswith("You are an assistant.")
    assert "Required Output Format" in result
    assert "```json" in result
    schema_json = json.dumps(_Thing.model_json_schema(), indent=2)
    assert schema_json in result


def test_inject_schema_does_not_mutate_original_prompt() -> None:
    parser = StructuredOutputParser()
    original = "base prompt"
    parser.inject_schema(original, _Thing)
    assert original == "base prompt"


# ─── format_retry_context() ──────────────────────────────────────────────────


def test_format_retry_context_for_validation_error() -> None:
    parser = StructuredOutputParser()
    try:
        _Thing.model_validate({"count": "not-an-int"})
    except ValidationError as e:
        message = parser.format_retry_context(e)
    assert "validation errors" in message
    assert "name" in message  # missing required field reported
    assert "count" in message  # type mismatch field reported


def test_format_retry_context_for_plain_value_error() -> None:
    parser = StructuredOutputParser()
    err = ValueError("could not parse")
    message = parser.format_retry_context(err)
    assert "could not be parsed as JSON" in message
    assert "could not parse" in message
    assert "ONLY valid JSON" in message


def test_max_retries_default_and_override() -> None:
    assert StructuredOutputParser().max_retries == 2
    assert StructuredOutputParser(max_retries=5).max_retries == 5
