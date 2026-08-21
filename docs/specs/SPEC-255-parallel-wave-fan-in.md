---
id: SPEC-255
title: "Parallel agent waves — fan-out cap enforcement and git fan-in merge (ADR-052)"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate:
  - maistro-engine#SPEC-254
  - maistro-engine#ADR-010
  - maistro-engine#ADR-018
related:
  - maistro-engine#ADR-054
  - maistro-engine#ADR-056
implements:
  - maistro-engine#ADR-052
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/orchestrator/waves/test_fan_in.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-255: Parallel agent waves — fan-out cap enforcement and git fan-in merge

> **Convergence note (2026-08-19).** This spec is marked `Implemented` over
> code with no path from any process entry point — see
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363). It
> tracks ADR-052, now `Deprecated`.
>
> The status is left unchanged because the spec lifecycle has no way to
> express this. From `Implemented` a spec may only become `Superseded`, which
> requires a `superseded-by`, and no successor document exists. There is no
> `Deprecated` state for specs as there is for ADRs. Correcting this needs
> either the successor spec or a lifecycle change, so the note carries the
> truth in the meantime.


## Context

ADR-052 requires intra-task parallel sub-agents ("waves") to run against isolated per-wave
branches inside the task's shadow workspace (ADR-049 / SPEC-254), with a fan-in step that
auto-merges non-overlapping changes and bubbles real conflicts. Nothing implementing this exists.
This SPEC scopes the two load-bearing, independently-testable pieces: fan-out width validation
against the substrate-enforced hard cap, and the fan-in merge itself, built directly on
`ShadowGitWorkspace` (SPEC-254) using real `git merge` so conflict detection is exact rather than
heuristic.

## Goals

- Add `maistro/orchestrator/waves/types.py`: `WaveSpec` (frozen dataclass: `wave_id: str`,
  `agent_recipe: str`, `inputs: dict[str, Any]`), `WaveHandle` (frozen dataclass: `wave_id: str`,
  `branch: str`, `status: Literal["running", "succeeded", "failed"]`, `head_sha: str | None`),
  `ConflictRecord` (frozen dataclass: `path: str`, `wave_a: str`, `wave_b: str`, `sha_a: str`,
  `sha_b: str`), `FanInResult` (frozen dataclass: `merged_sha: str | None`,
  `conflicts: tuple[ConflictRecord, ...]`, `failed_waves: tuple[WaveHandle, ...]`).
- Add `maistro/orchestrator/waves/fan_out.py`: `MAX_PARALLEL_CEILING = 16` and
  `validate_fan_out_width(wave_specs: tuple[WaveSpec, ...], *, max_parallel: int) -> None` —
  raises `ValueError` if `max_parallel > MAX_PARALLEL_CEILING` (recipe cannot exceed the
  substrate cap) or if `len(wave_specs) > max_parallel`.
- Add `maistro/orchestrator/waves/fan_in.py`: `fan_in(workspace: ShadowGitWorkspace, *,
  base_branch: str, fan_in_branch: str, waves: tuple[WaveHandle, ...]) -> FanInResult`:
  - Partitions `waves` into `succeeded` and the rest; anything not `"succeeded"` is passed
    through untouched into `FanInResult.failed_waves` (the name covers `"failed"` and `"running"`
    — anything not cleanly succeeded is excluded from the merge and preserved for inspection,
    matching ADR-052's "failed waves preserve their branch; do not block merge").
  - Creates `fan_in_branch` from `base_branch`, then for each succeeded wave in order attempts
    `git merge --no-edit <wave.branch>`.
  - On clean merge: continues to the next wave.
  - On conflict: reads the conflicting paths (`git diff --name-only --diff-filter=U`), aborts the
    merge (`git merge --abort`), records one `ConflictRecord` per conflicting path (`wave_a` is
    the fan-in branch's current state going into that merge attempt — represented by the prior
    wave's id or `base_branch` if it's the first merge — `wave_b` is the conflicting wave's id;
    `sha_a`/`sha_b` are the respective branch tip SHAs at the time of the attempt), and moves on
    to the next succeeded wave without that wave's changes applied.
  - Returns `FanInResult.merged_sha` as the fan-in branch's final HEAD SHA (always set — even
    zero successful merges still yields `base_branch`'s SHA), plus the accumulated conflicts and
    untouched failed/running waves.

## Non-goals

- Spawning/executing the sub-agent processes for each wave (`WaveOrchestrator.fan_out`'s
  conductor-process side) — this SPEC's `validate_fan_out_width` is the pure cap-check the real
  fan-out call site will call before spawning; spawning itself is a `tasks/runner.py` integration.
- `conflict_resolver` recipe knob (`meta_agent | human | fail`) — ADR-052 routes unresolved
  `ConflictRecord`s to a meta-resolver or an ADR-051 human gate; this SPEC only produces the
  records, it does not resolve them.
- Wave-internal parallelism / nested fan-out — ADR-052 itself defers this; out of scope here too.
- `wave.fan_out`/`wave.fan_in` spans and `maistro_wave_merge_conflicts_total` metric (ADR-037
  wiring) — follow-up once an event-bus/tracer call site invokes this module.
- Persisting `WaveHandle`s on `TaskRecord` for crash recovery (ADR-056) — follow-up; SPEC-256
  scopes ADR-056's checkpoint-replay core separately.

## Decision

```python
# maistro/orchestrator/waves/types.py
@dataclass(frozen=True)
class WaveSpec:
    wave_id: str
    agent_recipe: str
    inputs: dict[str, Any]

@dataclass(frozen=True)
class WaveHandle:
    wave_id: str
    branch: str
    status: Literal["running", "succeeded", "failed"]
    head_sha: str | None

@dataclass(frozen=True)
class ConflictRecord:
    path: str
    wave_a: str
    wave_b: str
    sha_a: str
    sha_b: str

@dataclass(frozen=True)
class FanInResult:
    merged_sha: str | None
    conflicts: tuple[ConflictRecord, ...]
    failed_waves: tuple[WaveHandle, ...]

# maistro/orchestrator/waves/fan_out.py
MAX_PARALLEL_CEILING = 16

def validate_fan_out_width(wave_specs: tuple[WaveSpec, ...], *, max_parallel: int) -> None: ...

# maistro/orchestrator/waves/fan_in.py
def fan_in(
    workspace: ShadowGitWorkspace,
    *,
    base_branch: str,
    fan_in_branch: str,
    waves: tuple[WaveHandle, ...],
) -> FanInResult: ...
```

## Acceptance criteria

- [x] `validate_fan_out_width` accepts a wave count at or below `max_parallel` and at or below
      `MAX_PARALLEL_CEILING`.
- [x] `validate_fan_out_width` raises `ValueError` when `max_parallel` itself exceeds
      `MAX_PARALLEL_CEILING` (recipe cannot raise the substrate cap).
- [x] `validate_fan_out_width` raises `ValueError` when `len(wave_specs) > max_parallel`.
- [x] N waves with disjoint file sets fan in cleanly: `merged_sha` is set, `conflicts` is empty,
      and the fan-in branch contains every wave's files.
- [x] Two waves editing the same file with different content produce a `ConflictRecord` naming
      that path with both waves' ids and SHAs; the fan-in branch still contains the
      non-conflicting wave's other files.
- [x] A `WaveHandle` with `status="failed"` is excluded from the merge and appears in
      `failed_waves`; it does not block the merge of other succeeded waves.
- [x] Zero succeeded waves still returns a `merged_sha` equal to `base_branch`'s SHA.

## Testing

- `packages/maistro-core/tests/orchestrator/waves/test_fan_in.py` (new) — builds a real
  `ShadowGitWorkspace` (SPEC-254) with multiple wave branches via real git operations (no
  mocking), exercises clean fan-in, conflicting fan-in, and failed-wave pass-through; plus
  `validate_fan_out_width`'s cap-enforcement matrix.

## Open questions

- Whether `wave_a` in a multi-wave conflict chain should track the *original* wave whose change
  is already merged, or always `base_branch` — this SPEC tracks the immediately-preceding state
  (prior wave id, or `base_branch` for the first attempt), which is precise for pairwise
  reporting; revisit if the meta-resolver (deferred) needs a different attribution.

## References

- [ADR-052: Parallel agent waves](../adr/ADR-052-parallel-agent-waves.md)
- [SPEC-254: Shadow git workspace](SPEC-254-shadow-git-workspace.md)
- [ADR-056: Task crash recovery](../adr/ADR-056-task-crash-recovery.md)
