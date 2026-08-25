---
id: SPEC-225
title: "Intent classifier: keyword/LLM-fallback/complexity pipeline and multi-intent detection"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-007
  - maistro-engine#ADR-089
implements:
  - maistro-engine#ADR-089
related:
  - maistro-engine#ADR-010
  - maistro-engine#ADR-071
  - maistro-engine#ADR-078
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/classifier/test_engine.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-225: Intent classifier: keyword/LLM-fallback/complexity pipeline and multi-intent detection

## Context

`maistro.classifier` implements a three-phase intent classification
pipeline, but ADR-089 pinned a stricter contract than the code currently
delivers: a DB-config-driven threshold (ADR-078), an observability event
per classification, and multi-intent requests split into independently
routed sub-tasks. This spec documents the pipeline as actually
implemented and flags where it diverges from ADR-089's decision.

## Goals

- `ClassifierEngine.classify`: keyword scoring → LLM fallback (only below
  threshold) → complexity/priority/tier estimation, returning an `Intent`.
- `ClassifierEngine.detect_multi_intent` / `detect_multi_intent()`:
  splits compound text on conjunctions and returns the set of distinct
  task types detected across the parts.

## Non-goals

- Routing/recombination of detected multi-intent sub-tasks — out of
  scope for the classifier itself; `detect_multi_intent` returns a list
  of task types, it does not construct or route sub-tasks (that would be
  a planner/orchestrator concern, ADR-071).
- i18n / cross-language intent detection.

## Decision

`packages/maistro-core/src/maistro/classifier/engine.py`:

```python
LLM_FALLBACK_THRESHOLD = 3.0  # module-level constant, not DB config

def is_ambiguous(scores: dict[str, float]) -> bool: ...

class ClassifierEngine:
    def __init__(self, llm_client: LLMClient | None = None, classifier_model: str = "auto") -> None: ...
    async def classify(self, messages, task_types, explicit_priority=None) -> Intent: ...
    def detect_multi_intent(self, user_text: str, task_types: dict[str, TaskTypeConfig]) -> list[str]: ...
```

`packages/maistro-core/src/maistro/classifier/multi_intent.py`:

```python
def detect_multi_intent(user_text: str, task_types: dict[str, TaskTypeConfig]) -> list[str]: ...
```

`classify()` scores keywords via `score_keywords`; if the best score is
below `LLM_FALLBACK_THRESHOLD` and an `llm_client` is configured, it
calls `llm_classify` to resolve the task type, recording
`classified_by="llm"` vs `"keywords"`. Complexity/priority/tier are then
derived via `estimate_complexity`/`coerce_priority`/`infer_priority`,
with a tier bump to `"large"` for complex tasks and a home-automation-
specific tier sizing path (`automation_min_tier`). `detect_multi_intent`
splits text on conjunction phrases (`" and "`, `" and then "`, etc.),
matches each part against `STRONG_INDICATORS` first and config keywords
second, and returns the list of distinct task types found (empty unless
2+ distinct types are detected).

## Acceptance criteria

- [x] A high-confidence keyword match (`score >= LLM_FALLBACK_THRESHOLD`)
      resolves without an LLM call
- [x] A low-confidence request escalates to the LLM phase when an LLM
      client is configured
- [x] `detect_multi_intent` identifies 2+ distinct task types in a
      compound request and returns them as a list
- [ ] `τ` (`LLM_FALLBACK_THRESHOLD`) is a hardcoded module constant, not
      read from DB config (ADR-078) as ADR-089 specifies — not
      runtime-editable or DB-auditable
- [ ] A multi-intent request is **detected** but not split into
      independently-routed sub-tasks by the classifier — `Intent` is
      still a single-task-type return value; sub-task construction and
      routing is not implemented here
- [ ] Classifier output is not observed emitting an ADR-037
      observability event in `classify()` itself

## Testing

Covered by `packages/maistro-core/tests/classifier/test_engine.py`.

## Open questions

- Whether `LLM_FALLBACK_THRESHOLD` and complexity-tier cutoffs should
  move to DB config (ADR-078) to satisfy ADR-089's "interpretable,
  auditable config" requirement, or whether ADR-089 should be revised to
  match the simpler hardcoded-constant reality.
- Whether multi-intent splitting into independently routed sub-tasks
  belongs in the classifier or in the planner/orchestrator (ADR-071) —
  currently neither implements it.
- Whether a classification observability event should be added, and
  where (engine vs. a calling layer).

## References

- [ADR-007: Variant selector](../adr/ADR-007-variant-selector.md)
- [ADR-089: Intent Classifier](../adr/ADR-089-intent-classifier.md)
- `packages/maistro-core/src/maistro/classifier/engine.py`
- `packages/maistro-core/src/maistro/classifier/multi_intent.py`
