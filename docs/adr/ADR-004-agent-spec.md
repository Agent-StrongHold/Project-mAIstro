---
id: ADR-004
title: AgentSpec + AgentOutput envelopes
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-002
  - maistro-engine#ADR-005
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: [boundary]
tests: []
layer: Agents
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-004: AgentSpec + AgentOutput envelopes

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T1  
**Depends on:** ADR-002

---

## Context

maistro-engine's conductor currently exchanges raw strings with agents and has no uniform result envelope. Error handling is ad-hoc and there is no structured way to propagate trace IDs, timing, or error categorization across agent calls.

`Project_mAIstro/conductor/orchestrator/agents/agent_spec.py` defines `AgentSpec` (what to send) and `AgentOutput` (what comes back) — a typed, observable, retry-safe contract.

## Decision

Port `AgentSpec` and `AgentOutput` into `src/maistro/agents/spec/agent_spec.py`. Port `Lane`, `AgentRole` (extended), `ErrorType`, `RECOVERABLE_ERRORS`, `DEFAULT_TOOLS`.

Extend existing `src/maistro/agents/types.py:AgentRole` by replacing the `CONDUCTOR/PLANNER/CODER/REVIEWER/SCOUT` enum with the full set. The old `ConductorOutput`/`PlanOutput`/`CodeOutput`/`ReviewOutput` in `types.py` are kept for backward compatibility with existing tests and are deprecated in favour of `schemas.py` models (ADR-005).

**Not ported:** `project_id` (gateway prefix-cache concept — local-inference only), `exemplar_*` fields (ExemplarLibrary not in scope for T1), `parallel_generations > 1` paths (Ultra Think, T9).

## Interface

```python
# src/maistro/agents/spec/agent_spec.py

class Lane(StrEnum):
    LIVE = "live-chat"
    BACKGROUND = "background-task"

class AgentRole(StrEnum):
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    SCOUT = "scout"
    ARCHITECT = "architect"
    EXTRACTOR = "extractor"
    VALIDATOR = "validator"
    INTENT_ROUTER = "intent_router"
    ARTIFACT = "artifact"
    CONVERSATION = "conversation"

class ErrorType(StrEnum):
    TIMEOUT = "timeout"
    PARSE_FAILURE = "parse_failure"
    MODEL_ERROR = "model_error"
    LOW_SCORE = "low_score"
    SAFETY_VIOLATION = "safety_violation"
    TOOL_VIOLATION = "tool_violation"
    DEPENDENCY_FAILED = "dependency_failed"

RECOVERABLE_ERRORS: frozenset[ErrorType]
DEFAULT_TOOLS: dict[AgentRole, list[str]]

class AgentSpec(BaseModel):
    agent_id: str               # auto-generated hex-8
    role: AgentRole
    task_id: str
    subtask_id: str
    description: str
    attempt: int = 1
    context: dict[str, str] = {}
    upstream_outputs: dict[str, str] = {}
    tier: int = 2
    model_override: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    prompt_name: str | None = None
    prompt_label: str = "production"
    prompt_variables: dict[str, str] = {}
    recipe_name: str | None = None
    result_type: str | None = None
    tools_allowed: list[str] = []
    write_scopes: list[str] = []
    lane: Lane = Lane.BACKGROUND
    langfuse_trace_id: str | None = None
    langfuse_parent_span_id: str | None = None
    tenant_id: str = "default"
    parent_agent_id: str | None = None

    def with_defaults(self) -> AgentSpec: ...  # fills tools_allowed + prompt_name from role

class AgentOutput(BaseModel):
    agent_id: str
    role: AgentRole
    task_id: str
    subtask_id: str
    attempt: int = 1
    success: bool = True
    output: str = ""
    output_parsed: dict | None = None
    error: str | None = None
    error_type: ErrorType | None = None
    recoverable: bool = True
    escalation_reason: str | None = None
    variant_used: str | None = None
    model_used: str | None = None
    tier_used: int | None = None
    tokens_used: dict[str, int] = {}
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    langfuse_span_id: str | None = None

    def mark_complete(self) -> None: ...
    def mark_error(self, error: str, error_type: ErrorType, *, escalation_reason: str | None = None) -> None: ...
```

## Acceptance criteria

- [ ] `AgentSpec.with_defaults()` fills `tools_allowed` from `DEFAULT_TOOLS[role]` when empty
- [ ] `AgentSpec.with_defaults()` fills `prompt_name` from role action map when None
- [ ] `AgentOutput.mark_error()` sets `recoverable=False` for non-recoverable error types
- [ ] `AgentOutput.mark_complete()` sets `completed_at` and `duration_ms > 0`
- [ ] `ErrorType.SAFETY_VIOLATION` is not in `RECOVERABLE_ERRORS`
- [ ] `AgentSpec` round-trips through JSON (pydantic serialize/deserialize)
- [ ] `agent_id` is unique across two `AgentSpec()` instantiations

## Test plan

| Test | Covers |
|---|---|
| `test_agent_spec_defaults_fills_tools` | `with_defaults()` tool whitelist per role |
| `test_agent_spec_defaults_fills_prompt_name` | `with_defaults()` prompt_name convention |
| `test_agent_spec_agent_id_unique` | auto-generated IDs are distinct |
| `test_agent_output_mark_error_recoverable` | recoverable error types |
| `test_agent_output_mark_error_non_recoverable` | non-recoverable error types |
| `test_agent_output_mark_complete_sets_duration` | timing logic |
| `test_agent_spec_json_roundtrip` | serialization |
| `test_recoverable_errors_set_contents` | RECOVERABLE_ERRORS = {TIMEOUT, PARSE_FAILURE, MODEL_ERROR, LOW_SCORE} |

## Out of scope

`project_id`, `exemplar_*`, `parallel_generations` fields (T9). Exemplar injection (T9).

## Source references

- `Project_mAIstro/conductor/orchestrator/agents/agent_spec.py`
