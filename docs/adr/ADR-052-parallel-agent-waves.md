---
id: ADR-052
title: Parallel agent waves — per-wave branch isolation and fan-in merge
repo: maistro-engine
kind: adr
status: Deprecated
created: 2026-05-13
substrate:
  - maistro-engine#ADR-049
  - maistro-engine#ADR-010
  - maistro-engine#ADR-018
implements: []
related:
  - maistro-engine#ADR-054
  - maistro-engine#ADR-056
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Deprecated
    date: 2026-08-19
---

# ADR-052: Parallel agent waves — per-wave branch isolation and fan-in merge

> **Convergence note (2026-08-19).** This ADR was marked `Implemented` over
> code that has no path from any process entry point, which the reachability
> sweep in
> [#360](https://github.com/Agent-StrongHold/maistro-engine/issues/360)
> surfaced and
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363)
> catalogued. It shipped and was never connected. It specifies per-wave git
> branch isolation and fan-in merge for file-editing sub-agents, built on
> ADR-049's shadow workspace. That is a filesystem-isolation concern, not the
> traversal concern ADR-062 owns, so ADR-062 does not replace it.
>
> Status moved `Implemented` → `Deprecated` rather than `Superseded`: nothing
> replaces this design, and `Superseded` requires naming a successor document.
> The code remains in the tree and in `quality/reachability-baseline.json`;
> its removal belongs to the island-elimination stage of the convergence
> effort.


## Context

ADR-010 splits tasks across lanes (LIVE vs BACKGROUND) for fairness. It does not address *intra-task* parallelism — a task that fans out work to N sub-agents in parallel ("have three agents each work on a separate module"). Today, concurrent sub-agents editing files would collide on the shadow workspace from ADR-049. Without a per-wave isolation model and a fan-in story, intra-task parallelism is unsafe.

Production agent systems converge on per-wave git branches with auto-merge at fan-in. Git handles non-overlapping changes cheaply; real conflicts surface for resolution. This ADR specifies the model.

## Problem

No substrate primitive for intra-task parallel sub-agents that may edit overlapping files.

## Decision

Each parallel sub-agent ("wave") runs against its own shadow-git branch inside the task's shadow workspace (ADR-049). Branches named `wave-<wave_id>` from the task's base SHA. The conductor fans out N waves; each wave commits independently. At fan-in, the conductor merges across wave branches:

- Non-overlapping changes: auto-merge.
- Real conflicts: bubble to a meta-resolver agent OR to a human, per recipe knob.
- Failed waves: branch preserved for inspection; does not block merge of successful waves.

The merged result becomes the new shadow-workspace HEAD that the parent agent sees. Waves do not see each other's intermediate state — they are isolated until fan-in.

Waves run as concurrent processes inside the same task sandbox (ADR-054); not separate containers. Git per-branch isolation is sufficient for FS-level safety.

## Interface (sketch)

```python
class WaveSpec(BaseModel):
    wave_id: str
    agent_recipe: str
    inputs: dict[str, Any]

class WaveHandle(BaseModel):
    wave_id: str
    branch: str            # "wave-<wave_id>" under task's shadow repo
    status: Literal["running", "succeeded", "failed"]
    head_sha: str | None

class FanInResult(BaseModel):
    merged_sha: str | None
    conflicts: list[ConflictRecord]
    failed_waves: list[WaveHandle]

class WaveOrchestrator(Protocol):
    async def fan_out(self, parent_task: TaskRecord, wave_specs: list[WaveSpec]) -> list[WaveHandle]: ...
    async def fan_in(self, parent_task: TaskRecord, waves: list[WaveHandle]) -> FanInResult: ...
```

Recipe declares (merge: deep per ADR-053):

```yaml
wave:
  max_parallel: 4
  conflict_resolver: meta_agent | human | fail
  conflict_resolver_ref: "meta.merge.default@v1"   # if meta_agent
```

## Acceptance criteria

- [ ] N parallel waves with disjoint file sets merge cleanly without bubbling conflicts.
- [ ] Overlapping file edits across waves produce `ConflictRecord` entries with both branch SHAs.
- [ ] Recipe-knob `wave.conflict_resolver` honored (`meta_agent` invokes resolver-ref, `human` raises an ADR-051 gate, `fail` aborts the parent task).
- [ ] Failed waves preserve their branch; do not block merge of successful waves.
- [ ] Substrate-enforced hard ceiling on `max_parallel` (recipe cannot exceed substrate cap, default 16).
- [ ] Span `wave.fan_out` parents wave-internal spans; `wave.fan_in` summarizes; both per ADR-037.
- [ ] Metric `maistro_wave_merge_conflicts_total{resolver}` per ADR-037.
- [ ] Wave handles persisted on `TaskRecord` (ADR-018) for crash recovery (ADR-056).

## Resolved decisions (v0)

1. **Max parallel ceiling → recipe-declared, substrate cap 16.** The recipe declares wave width; the substrate enforces a hard safety cap of 16.
2. **Cross-wave communication mid-execution → none.** Waves see each other only after fan-in; a wave needing another's output is modelled as a separate task.
3. **Wave-internal parallelism → sequential (v0).** Each wave runs internally sequential; nested fan-out is **deferred**.
4. **Speculative wave execution → deferred.** Running waves before all gates resolve is out of scope for v0.
5. **Merge-resolver tool surface → read-both, no other writes.** The meta-resolver gets read access to both branches and no write access elsewhere; Sentinel policy enforces it.

## Source references

- ADR-010 lane scheduling (LIVE/BACKGROUND fairness; orthogonal to waves).
- ADR-049 shadow git (the FS substrate that wave branches live in).
- `maistro-engine:src/maistro/tasks/runner.py` (TaskRunner gains wave orchestration).
- `maistro-engine:src/maistro/a2a/` (wave-to-wave is effectively a constrained A2A).

## Out of scope

- DAG-aware scheduling within a wave (each wave is internally sequential).
- Cross-task wave sharing.
- Distributed waves across nodes (single-conductor for v0; revisit with horizontal scale).
