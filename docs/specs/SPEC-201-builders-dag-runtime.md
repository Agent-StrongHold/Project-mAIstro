---
id: SPEC-201
title: "Builders Interactive Session — ReAct Agent Loop with Human-in-the-Loop TUI"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-03
substrate:
  - maistro-engine#SPEC-200
  - maistro-engine#ADR-090
implements:
  - maistro-engine#ADR-090
related:
  - maistro-engine#SPEC-190
  - maistro-engine#ADR-049
  - maistro-engine#ADR-075
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests:
  - packages/maistro-bootstrap/tests/test_builders_turn_record.py
  - packages/maistro-bootstrap/tests/test_builders_agent_loop.py
  - packages/maistro-bootstrap/tests/test_builders_cli.py
  - packages/maistro-bootstrap/tests/test_builders_actions.py
  - packages/maistro-bootstrap/tests/test_builders_models.py
  - packages/maistro-bootstrap/tests/test_builders_quality.py
  - packages/maistro-bootstrap/tests/test_builders_store.py
  - packages/maistro-bootstrap/tests/test_builders_message_board.py
  - packages/maistro-bootstrap/tests/test_builders_dagflow.py
  - packages/maistro-bootstrap/tests/test_builders_spec_session.py
  - packages/maistro-bootstrap/tests/test_builders_edge_coverage.py
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-03
  - status: Implemented
    date: 2026-06-03
---

# SPEC-201: Builders Interactive Session

## Context

ADR-090 defines the Builders stage machine and worker roles. SPEC-200 defines the safety layer.
This spec describes the interactive builders session — a hybrid opencode/Claude Code-style TUI
that takes a task description, routes through a LiteLLM proxy for model access, and runs a ReAct
agent loop (think -> act -> observe) with human-in-the-loop approval gates.

The session produces structured `TurnRecord`s consumable by `maistro-evolve` for prompt, tool, and
topology optimization.

## Design Decisions

### 1. ReAct Agent Loop (not DAG dispatch)

V1 uses a simple ReAct loop rather than a full DAG dispatch engine:

- **TurnRunner** drives turns: system prompt (stage-aware) -> LLM call -> parse action -> execute ->
  observe -> next turn.
- Three autonomy levels: `auto` (no human gating), `supervised` (approve each action),
  `stage_gated` (approve at stage transitions).
- Retry logic: up to 3 retries for invalid LLM responses before failing.
- Quality delta capture per turn (before/after metrics).

The full DAG dispatch (DagNode/DagEdge/DagDispatch) remains defined in `dagflow.py` for future use
but the V1 execution path is the linear ReAct loop.

### 2. LiteLLM Proxy Routing

All LLM calls route through a **LiteLLM proxy** (`localhost:4000`) which provides access to 90+
models across Mistral, Gemini, Cloudflare, Cerebras, Groq, SambaNova, DeepSeek, Cohere, Together,
OpenRouter, Zhipu.

The `ResponsesAPICallable` class:
- Defaults to `http://localhost:4000/v1` (OpenAI-compatible endpoint).
- Uses `chat.completions.create` with native function calling (not `responses.create`, which
  LiteLLM does not proxy).
- Defines a `builder_action` function tool with all 12 supported actions.
- Falls back to `OPENAI_BASE_URL` or `LITELLM_BASE_URL` env vars.

### 3. Textual TUI

Two-pane layout:
- **Left (2fr)**: Chat pane with agent messages, diff rendering, slash commands.
- **Right (1fr)**: Diff viewer with syntax highlighting.
- **Status bar**: Stage indicator, quality metrics.

Key bindings: Ctrl+Q (quit), Ctrl+D (diff), Ctrl+T (test), Ctrl+A (apply), Ctrl+R (reject).

Slash commands: `/diff`, `/test`, `/apply`, `/reject`, `/status`, `/board`, `/quality`, `/exit`.

### 4. CLI Integration

```
maistro-install builders session "fix the login bug"   # Launch TUI
maistro-install builders models                        # Show role mapping
maistro-install builders list                          # List sessions
maistro-install builders board                         # Show Kanban board
maistro-install builders comment CARD_ID BODY          # Comment on card
maistro-install builders move CARD_ID STATUS           # Move card
```

Options: `--config`/`-c`, `--repo`/`-r`, `--autonomy`/`-a`, `--session`/`-s`.

### 5. Data Model

**TurnRecord** — Pydantic model capturing full signal chain per turn:
- prompt, role, model, action, output, quality_before/after, elapsed, tokens, retries

**TurnOutcomeSummary** — aggregated stats for a session.

### 6. No Docker Required for V1

Uses `LocalWorktreeSandbox` (git + filesystem only). No containers, Docker, or Podman needed.

## File Layout

```
packages/maistro-bootstrap/src/maistro_bootstrap/builders/
  __init__.py              # Public exports
  actions.py               # ActionRequest, ActionResult, SUPPORTED_ACTIONS
  agent_loop.py            # TurnRunner — ReAct agent loop
  cli.py                   # Typer CLI subcommands
  dagflow.py               # DagFlow (future DAG dispatch)
  message_board.py         # BoardCard, MessageBoard — Kanban board
  models.py                # BuilderModelRoles, LiteLLMModel
  quality.py               # QualityGateReport
  responses_callable.py    # ResponsesAPICallable — LiteLLM proxy wiring
  sandbox.py               # LocalWorktreeSandbox
  session.py               # BuilderSession
  spec_session.py          # SpecSession
  store.py                 # SessionStore
  tui.py                   # BuildersTUI — Textual TUI
  turn_record.py           # TurnRecord, TurnOutcomeSummary
```

## Acceptance Criteria

- **AC-1**: TurnRecord and TurnOutcomeSummary Pydantic models with full signal capture.
- **AC-2**: TurnRunner with role-to-model mapping, stage-aware prompts, retry logic, 3 autonomy levels.
- **AC-3**: BuildersTUI with two-pane layout, key bindings, slash commands, async worker.
- **AC-4**: CLI integration with session/models/list/board/comment/move subcommands.
- **AC-5**: ResponsesAPICallable routing through LiteLLM proxy with native function calling.
- **AC-6**: 86+ tests passing across all builders modules.
- **AC-7**: Ruff and mypy clean on all new files.
- **AC-8**: E2E verified: real LLM call through LiteLLM proxy returns correct result.
- **AC-9**: Tool calling verified: model correctly invokes builder_action with appropriate action and args.

## Open Questions

1. **DAG dispatch** — the full DAG dispatch engine (DagNode/DagEdge/DagDispatch) remains in
   `dagflow.py` for future use. When should we switch from ReAct loop to DAG dispatch?

2. **Model routing** — the role-to-model mapping (architect/editor/tester) is configurable but
   defaults to a single model. Should we default to different models per role?

3. **Session persistence** — sessions are stored via `SessionStore` (filesystem). Should we add
   a database-backed store for sharing across machines?

## References

- ADR-090 — Builders Pipeline stage machine and worker roles
- SPEC-200 — Builders Safety Layer
- [LiteLLM Proxy](https://docs.litellm.ai/docs/proxy/prod)
