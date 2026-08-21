"""Tests for StructuredOutputParser (ADR-008)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from maistro.agents.spec.structured_output import StructuredOutputParser


class _Simple(BaseModel):
    name: str
    count: int


class TestInjectSchema:
    def test_appends_schema_block(self) -> None:
        parser = StructuredOutputParser()
        result = parser.inject_schema("Be helpful.", _Simple)
        assert "Required Output Format" in result
        assert "```json" in result
        assert '"name"' in result  # field appears in schema

    def test_original_prompt_preserved(self) -> None:
        parser = StructuredOutputParser()
        result = parser.inject_schema("System instructions here.", _Simple)
        assert result.startswith("System instructions here.")


class TestParse:
    def test_pure_json(self) -> None:
        parser = StructuredOutputParser()
        result = parser.parse('{"name": "Alice", "count": 3}', _Simple)
        assert result.name == "Alice"
        assert result.count == 3

    def test_markdown_fenced_json(self) -> None:
        parser = StructuredOutputParser()
        raw = '```json\n{"name": "Bob", "count": 7}\n```'
        result = parser.parse(raw, _Simple)
        assert result.name == "Bob"

    def test_embedded_json_in_prose(self) -> None:
        parser = StructuredOutputParser()
        raw = 'Here is the output: {"name": "Carol", "count": 1} as requested.'
        result = parser.parse(raw, _Simple)
        assert result.name == "Carol"

    def test_no_json_raises_value_error(self) -> None:
        parser = StructuredOutputParser()
        with pytest.raises(ValueError, match="Could not extract JSON"):
            parser.parse("Sorry, I cannot help with that.", _Simple)

    def test_wrong_shape_raises_validation_error(self) -> None:
        parser = StructuredOutputParser()
        with pytest.raises(ValidationError):
            parser.parse('{"name": "X"}', _Simple)  # missing required 'count'


class TestFormatRetryContext:
    def test_validation_error_includes_field(self) -> None:
        parser = StructuredOutputParser()
        try:
            _Simple.model_validate({"name": "X"})
        except ValidationError as exc:
            context = parser.format_retry_context(exc)
            assert "count" in context

    def test_value_error_includes_message(self) -> None:
        parser = StructuredOutputParser()
        context = parser.format_retry_context(ValueError("no json found"))
        assert "no json found" in context
