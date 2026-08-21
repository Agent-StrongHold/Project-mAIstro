---
id: SPEC-195
title: Operational training data collection
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-02
accepted: null
implemented: null
substrate:
  - maistro-engine#ADR-002
  - maistro-engine#ADR-088
implements: []
related:
  - maistro-engine#SPEC-194
  - maistro-engine#SPEC-175
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/training/test_collector.py
  - packages/maistro-core/tests/training/test_exemplar_library.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-02
---

# SPEC-195: Operational training data collection

## Context

Every Ultra Think cycle (SPEC-194) produces a rich signal: N candidates, reviewer
scores, test results, accepted candidate, and sampling parameters. This data is
currently discarded after the orchestrator selects a candidate.

Capturing it in a structured, append-only format enables:
1. **Offline analysis** — which tiers/profiles actually improve acceptance rates?
2. **Prompt optimization** — feed into maistro-evolve (ADR-088) as fitness signals.
3. **Fine-tuning pipeline** — once a volume threshold is reached, the traces become
   supervised fine-tuning examples (preferred candidate given prompt).

**This is distinct from `maistro-evolve`** (ADR-088). Evolve runs an Elo tournament
on agent *recipes* (genome = agent YAML + prompts). Training data collection captures
raw *operational traces* from live task runs. They are complementary: evolve uses
collected fitness signals; training data captures everything evolve does not.

## Decision

### Python surface

New subsystem: `packages/maistro-core/src/maistro/training/`

| Module | Purpose |
|--------|---------|
| `protocol.py` | `TrainingDataProtocol` abstract interface |
| `collector.py` | `TrainingDataCollector` — JSONL append + rotation |
| `exemplar_library.py` | `ExemplarLibrary` — retrieve high-scoring past examples |
| `types.py` | `TrainingRecord`, `CandidateRecord`, `ReviewerScoreRecord`, `TestResultRecord` |

### `TrainingRecord` schema

```python
@dataclass
class TrainingRecord:
    task_id: str
    timestamp: float          # epoch seconds
    prompt_hash: str          # SHA-256[:16] of the raw messages list
    tier: int                 # 1, 2, or 3
    candidates: list[CandidateRecord]
    reviewer_scores: list[ReviewerScoreRecord]
    test_results: list[TestResultRecord]
    accepted_candidate_id: str | None
    human_accepted: bool | None = None   # set later by thumbs widget / eval judge

@dataclass
class CandidateRecord:
    candidate_id: str
    content_hash: str         # SHA-256[:16] of the completion text
    sampling_params: dict     # temperature, top_p, top_k, presence_penalty
    tokens_generated: int
    generation_time_ms: float

@dataclass
class ReviewerScoreRecord:
    candidate_id: str
    scores: dict              # {"correctness": 8, "style": 7, ...}
    overall: float            # weighted composite
    verdict: str              # "accept" | "reject" | "escalate"

@dataclass
class TestResultRecord:
    candidate_id: str
    passed: bool
    summary: str              # e.g. "12/12 tests passed"
```

JSONL on disk — one record per line, one file per project:
`{data_dir}/{project_id}-training.jsonl`

### File rotation

Files are rotated when they exceed **50 MB** (constant `MAX_TRAINING_FILE_SIZE`).
Rotated files are renamed with a Unix timestamp suffix:
`{project_id}-training.{timestamp}.jsonl`

Rotation is best-effort. If `os.rename` fails (e.g. across filesystems), the error
is logged at WARNING and the collector continues writing to the original path.

### `TrainingDataProtocol`

```python
class TrainingDataProtocol(Protocol):
    def record(self, entry: TrainingRecord) -> None: ...
    def recent(self, project_id: str, n: int = 100) -> list[TrainingRecord]: ...
```

`record` is **synchronous and non-blocking** — it must never delay the task pipeline
(same contract as SPEC-175 progress webhook). If the write fails, log at DEBUG and
return.

`recent()` is a **new addition** not present in the Conductor snapshot. It enables
maistro-evolve to read recent traces without a separate data pipeline. The JSONL
implementation reads the current training file tail; the noop implementation returns `[]`.

The **noop implementation** (`record` no-ops, `recent` returns `[]`) is the default in
`create_container()`. The JSONL implementation is injected when `TRAINING_DATA_DIR` is
set. This mirrors the SPEC-175 pattern exactly: zero filesystem access by default.

### `ExemplarLibrary`

The exemplar library stores the **best accepted completions by task category** for
use as few-shot examples in future prompts ("Training-Free GRPO"). It is category-keyed,
not hash-keyed — the goal is to retrieve good examples of the same *kind* of task.

```python
@dataclass
class Exemplar:
    task_category: str       # one of the CATEGORIES list
    task_description: str    # human-readable task summary
    solution: str            # the accepted completion text
    score: float             # overall reviewer score (0–10)

class ExemplarLibrary:
    CATEGORIES = ["test_writing", "bug_fix", "new_feature", "refactor", "documentation"]
    MAX_PER_CATEGORY = 50    # top 50 by score per category; older lower-scored entries are evicted

    def add(self, exemplar: Exemplar) -> None: ...
    def get_exemplars(self, category: str, n: int = 2) -> list[Exemplar]: ...
```

**Storage:** single JSONL file `{data_dir}/exemplars.jsonl`, rewritten on every `add()`
call (not append-only — the library maintains a score-sorted in-memory cache and
persists the full sorted list). The file is loaded eagerly on `__init__`.

**Category mapping:** if `task_category` is not in `CATEGORIES`, it maps to
`"new_feature"`. Unknown categories do not create new buckets.

**Score sorting:** each category bucket is kept sorted descending by `score`. When a
bucket reaches `MAX_PER_CATEGORY`, the lowest-scored entry is evicted.

**Promotion path:** the orchestrator is responsible for converting a `TrainingRecord`
into an `Exemplar` before calling `add()`. The mapping:
- `task_category` ← orchestrator-determined (from task metadata or classifier)
- `task_description` ← from the original task prompt
- `solution` ← the `content` of the accepted `CandidateCompletion`
- `score` ← the `overall` field of the matching `ReviewerScoreRecord`

Only records where `accepted_candidate_id is not None` and `score >= TRAINING_EXEMPLAR_THRESHOLD`
(default 8.0) should be promoted. The collector does not promote automatically — the
orchestrator calls `add()` explicitly.

Semantic/embedding-based retrieval is a v2 concern (see DECISION-BACKLOG vector store ADR).

### Integration points

| Caller | Hook |
|--------|------|
| Orchestrator / conductor | After reviewer selects a candidate, call `collector.record(...)` |
| Thumbs widget / eval judge | Set `human_accepted` on an existing record by `task_id` lookup |
| maistro-evolve | Read `recent()` traces to compute fitness signals for recipe Elo tournament |

The orchestrator is responsible for assembling `TrainingRecord` from the
`UltraThinkResult` (SPEC-194) and reviewer output. The collector only persists.

### Environment / settings

| Variable | Default | Semantics |
|----------|---------|-----------|
| `TRAINING_DATA_DIR` | `""` | Absolute path. Empty disables collection entirely (noop protocol). |
| `TRAINING_EXEMPLAR_THRESHOLD` | `8.0` | Min overall reviewer score for exemplar promotion. |

### Relationship to `maistro.types.memory.Outcome`

`Outcome` already carries `eval_judge_score`, `thumb`, and `thumb_comment` for
lightweight post-hoc signals on completed tasks. `TrainingRecord` is **richer and
earlier**: it captures the full candidate slate *during* a task, not just the final
outcome. Both are needed; they are not duplicates.

## Reference bundle

Reference implementation in git history at `d6603c9^`,
path `potential-dead-code/code-worth-implementing-from-Conductor/snapshot/`:

| Snapshot file | Port target |
|---------------|-------------|
| `orchestrator/training/data_collector.py` | `packages/maistro-core/src/maistro/training/collector.py` |
| `orchestrator/training/exemplar_library.py` | `packages/maistro-core/src/maistro/training/exemplar_library.py` |

## Acceptance criteria

1. **Noop by default** — `create_container()` with no `TRAINING_DATA_DIR` set
   makes zero filesystem calls when `record()` is called.
2. **Record written** — with a temp dir, a `TrainingRecord` produces a valid JSONL
   line that round-trips through `TrainingRecord` dataclass deserialization.
3. **File rotation** — writing past `MAX_TRAINING_FILE_SIZE` (50 MB) renames the
   current file with a timestamp suffix and starts a new one; both files are valid JSONL.
4. **Non-blocking on failure** — if the data dir is read-only, `record()` logs at
   DEBUG and returns without raising.
5. **recent() returns tail** — `recent(project_id, n=5)` returns the last 5 records
   from the JSONL file in insertion order.
6. **Exemplar add and retrieve** — calling `add(Exemplar(category="bug_fix", ..., score=9.0))`
   followed by `get_exemplars("bug_fix", n=1)` returns that exemplar as the first result.
7. **Category fallback** — `get_exemplars("unknown_category")` returns results from
   the `"new_feature"` bucket, not an empty list.
8. **MAX_PER_CATEGORY eviction** — adding 51 exemplars to the same category keeps
   exactly 50; the one with the lowest score is dropped.
9. **Score ordering** — `get_exemplars(category, n=3)` returns the top 3 by score
   descending.
10. **Exemplar file rewrite** — after `add()`, the `exemplars.jsonl` file reflects
    the current sorted state (not an append; the full file is rewritten).
