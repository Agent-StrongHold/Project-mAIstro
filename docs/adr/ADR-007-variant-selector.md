---
id: ADR-007
title: VariantSelector (Thompson sampling)
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-006
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: [boundary]
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-007: VariantSelector (Thompson sampling)

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T1  
**Depends on:** ADR-006

---

## Context

No A/B testing of prompts today. When multiple prompt variants are defined in a recipe, the system needs a principled way to choose between them that balances exploration and exploitation without manual tuning.

## Decision

Port `VariantSelector` into `src/maistro/agents/spawner/variant_selector.py`. Uses Beta distribution Thompson sampling. Langfuse client is optional (stats fall back to in-memory only).

## Interface

```python
class VariantStats(BaseModel):
    variant: str
    runs: int = 0
    successes: int = 0
    failures: int = 0
    mean_score: float = 0.0
    success_rate: float = 0.0

class VariantSelector:
    def __init__(self, langfuse_client=None, cache_ttl: int = 300, success_threshold: float = 7.0) -> None: ...
    def select(self, recipe: AgentRecipe) -> str: ...
    def record_outcome(self, prompt_name: str, variant: str, score: float, *, trace_id: str | None = None) -> None: ...
    def get_stats(self, prompt_name: str) -> dict[str, VariantStats]: ...
```

Three selection phases: (1) round-robin until `min_samples_before_selection`, (2) random explore with `exploration_rate`, (3) Thompson sample from `Beta(successes+1, failures+1)`.

## Acceptance criteria

- [ ] Single-variant recipe always returns that variant
- [ ] Empty variants list returns `"production"`
- [ ] Round-robin phase cycles all variants before repeating
- [ ] `record_outcome` increments successes when score ≥ 7.0
- [ ] `record_outcome` increments failures when score < 7.0
- [ ] After many successes for variant A, Thompson sampling favours A
- [ ] Seedable with `random.seed()` for deterministic tests
- [ ] No Langfuse client → stats are in-memory only, no exception

## Test plan

| Test | Covers |
|---|---|
| `test_single_variant` | always returns only option |
| `test_empty_variants_returns_production` | fallback |
| `test_round_robin_covers_all_variants` | phase 1 |
| `test_record_outcome_success_threshold` | ≥7.0 = success |
| `test_thompson_sampling_favours_winner` | phase 3 statistical bias |
| `test_no_langfuse_no_exception` | graceful nil client |
| `test_stats_after_records` | mean_score incremental update |

## Source references

- `Project_mAIstro/conductor/orchestrator/agents/variant_selector.py`
