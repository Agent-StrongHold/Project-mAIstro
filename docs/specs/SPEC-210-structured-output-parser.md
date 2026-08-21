---
id: SPEC-210
title: "StructuredOutputParser: typed LLM output extraction, validation, and retry context"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate:
  - maistro-engine#ADR-005
  - maistro-engine#ADR-008
implements:
  - maistro-engine#ADR-008
related:
  - maistro-engine#SPEC-209
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/agents/spec/test_structured_output.py
layer: Tools
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-210: StructuredOutputParser: typed LLM output extraction, validation, and retry context

## Context

LLM responses arrive as raw strings. When a typed output is expected (e.g.
`ScoutOutput` from SPEC-209), the system needs a principled way to tell the
model the exact shape required, extract a JSON payload from whatever the
model actually returns (pure JSON, markdown-fenced, or embedded in prose),
validate it against the target Pydantic model, and — on failure — produce a
re-prompt message a retry loop can feed back to the model.

## Goals

- Inject a JSON-schema instruction block into a system prompt for any
  `BaseModel` subclass.
- Parse raw LLM text into a validated model instance, tolerating the three
  common response shapes (pure JSON, fenced JSON, JSON embedded in prose).
- Produce a human-readable retry message from either a Pydantic
  `ValidationError` (field-level detail) or a `ValueError` (no JSON found).

## Non-goals

- Automatic retry orchestration/looping — this parser produces the retry
  context string; the caller (agent runtime) decides whether/how to retry.
- Streaming/partial-JSON parsing.

## Decision

`StructuredOutputParser` in `src/maistro/agents/spec/structured_output.py`:

```python
class StructuredOutputParser:
    def __init__(self, max_retries: int = 2) -> None: ...
    def inject_schema(self, system_prompt: str, result_type: type[BaseModel]) -> str: ...
    def parse(self, raw: str, result_type: type[T]) -> T: ...
    def format_retry_context(self, error: ValidationError | ValueError) -> str: ...
```

- `inject_schema` appends a `## Required Output Format` block containing the
  model's `model_json_schema()` as a fenced JSON block, with an instruction
  not to emit text before/after the JSON.
- `parse` extraction order (via `_extract_json`, regex-based):
  1. Markdown-fenced ` ```json ... ``` ` block (`_JSON_BLOCK_RE`).
  2. First `{...}` object found in the text (`_JSON_OBJECT_RE`).
  3. Raises `ValueError` (including the first 200 chars of raw output) if
     neither matches.
  Once text is extracted, `result_type.model_validate_json(extracted)` is
  called — a shape mismatch raises Pydantic's `ValidationError`.
- `format_retry_context`: for `ValidationError`, renders one bullet per error
  with its field path (`loc`), message, and `type`; for `ValueError`, returns
  the error string with an instruction to respond with JSON only.

`max_retries` is stored on the instance for callers to consult; the parser
itself does not loop.

## Acceptance criteria

- [x] `inject_schema` appends schema JSON block to the system prompt
- [x] `parse` succeeds on pure JSON output
- [x] `parse` succeeds on markdown-fenced JSON
- [x] `parse` succeeds on JSON embedded in prose
- [x] `parse` raises `ValueError` when no JSON found
- [x] `parse` raises `ValidationError` when JSON doesn't match schema
- [x] `format_retry_context(ValidationError)` includes field name and error type
- [x] `format_retry_context(ValueError)` includes the error string

## Testing

Covered by `tests/agents/spec/test_structured_output.py`:

| Test | Covers |
|---|---|
| `test_inject_schema_appends_block` | schema injected |
| `test_parse_pure_json` | extraction strategy: pure JSON |
| `test_parse_markdown_json_block` | extraction strategy: fenced JSON |
| `test_parse_embedded_json` | extraction strategy: JSON in prose |
| `test_parse_no_json_raises_value_error` | failure mode |
| `test_parse_wrong_shape_raises_validation_error` | shape mismatch |
| `test_retry_context_validation_error` | error formatting |
| `test_retry_context_value_error` | error formatting |

## Open questions

- None — design is implemented and stable as of this writing.

## References

- [ADR-005: Pydantic schemas + SCHEMA_REGISTRY](../adr/ADR-005-schemas.md)
- [ADR-008: StructuredOutputParser](../adr/ADR-008-structured-output-parser.md)
- `packages/maistro-core/src/maistro/agents/spec/structured_output.py`
