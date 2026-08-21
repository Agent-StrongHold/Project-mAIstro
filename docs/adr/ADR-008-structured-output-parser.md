---
id: ADR-008
title: StructuredOutputParser
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-005
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: [boundary]
tests: []
layer: Tools
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-008: StructuredOutputParser

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T1  
**Depends on:** ADR-005

---

## Context

LLM responses are raw strings. When a typed output is expected (e.g. `ScoutOutput`), the system currently has no principled way to validate or retry. Pydantic AI introduced the concept of injecting a JSON schema into the prompt so the model knows the exact shape required, then validating the response and retrying with error context.

## Decision

Port `StructuredOutputParser` into `src/maistro/agents/spec/structured_output.py`.

## Interface

```python
class StructuredOutputParser:
    def __init__(self, max_retries: int = 2) -> None: ...
    def inject_schema(self, system_prompt: str, result_type: type[BaseModel]) -> str: ...
    def parse(self, raw: str, result_type: type[BaseModel]) -> BaseModel: ...
    def format_retry_context(self, error: ValidationError | ValueError) -> str: ...
```

- `inject_schema`: appends `## Required Output Format\n\`\`\`json\n<schema>\n\`\`\`` to the system prompt
- `parse`: tries (1) direct JSON parse, (2) markdown code block, (3) first `{...}` in text; raises `ValueError` if none works, `ValidationError` if shape doesn't match
- `format_retry_context`: formats Pydantic validation errors as a re-prompt message

## Acceptance criteria

- [ ] `inject_schema` appends schema JSON block to the system prompt
- [ ] `parse` succeeds on pure JSON output
- [ ] `parse` succeeds on markdown-fenced JSON (` ```json ... ``` `)
- [ ] `parse` succeeds on JSON embedded in prose
- [ ] `parse` raises `ValueError` when no JSON found
- [ ] `parse` raises `ValidationError` when JSON doesn't match schema
- [ ] `format_retry_context(ValidationError)` includes field name and error type
- [ ] `format_retry_context(ValueError)` includes the error string

## Test plan

| Test | Covers |
|---|---|
| `test_inject_schema_appends_block` | schema injected |
| `test_parse_pure_json` | strategy 1 |
| `test_parse_markdown_json_block` | strategy 2 |
| `test_parse_embedded_json` | strategy 3 |
| `test_parse_no_json_raises_value_error` | failure mode |
| `test_parse_wrong_shape_raises_validation_error` | shape mismatch |
| `test_retry_context_validation_error` | error formatting |
| `test_retry_context_value_error` | error formatting |

## Source references

- `Project_mAIstro/conductor/orchestrator/agents/structured_output.py`
