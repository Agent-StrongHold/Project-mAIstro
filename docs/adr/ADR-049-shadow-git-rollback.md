---
id: ADR-049
title: Agent file-edit rollback via shadow git
repo: maistro-engine
kind: adr
status: Deprecated
created: 2026-05-13
substrate:
  - maistro-engine#ADR-018
  - maistro-engine#ADR-037
implements: []
related:
  - maistro-engine#ADR-052
  - maistro-engine#ADR-056
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Tools
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Deprecated
    date: 2026-08-19
---

# ADR-049: Agent file-edit rollback via shadow git

> **Convergence note (2026-08-19).** This ADR was marked `Implemented` over
> code that has no path from any process entry point, which the reachability
> sweep in
> [#360](https://github.com/Agent-StrongHold/maistro-engine/issues/360)
> surfaced and
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363)
> catalogued. It shipped and was never connected. Its only importer is
> ADR-052's `fan_in.py`, which is itself unreachable — a closed island of two
> dead subsystems importing each other.
>
> Status moved `Implemented` → `Deprecated` rather than `Superseded`: nothing
> replaces this design, and `Superseded` requires naming a successor document.
> The code remains in the tree and in `quality/reachability-baseline.json`;
> its removal belongs to the island-elimination stage of the convergence
> effort.


## Context

`src/maistro/tools/git/` exists as a substrate module but has no rollback primitive for agent file edits. An agent making N edits across a working tree today commits each edit directly — a failed task leaves the tree half-modified, and a successful task produces noisy commit history mixed with experimental edits. Reviewers see the agent's whole working-out, not a clean artifact.

Hermes-desktop's Edit flow uses an intermediate "shadow" working area before committing to the real tree, so the user sees one reviewable diff rather than the agent's intermediate experimentation. The pattern is a natural substrate primitive: cheap atomic rollback for the agent, clean output for the consumer.

## Problem

No substrate primitive for atomic rollback of agent file edits or for producing a clean diff against a real project from a noisy agent edit history.

## Solution sketch

Each task gets a shadow git workspace — a bare repo or worktree under a task-scoped path. Every agent edit becomes a commit in the shadow repo (per-edit granularity). At task completion, the substrate produces a single squashed diff or PR-candidate branch against the real project. The agent's intermediate history stays in the shadow repo for debugging and replay (ADR-055) but is not pushed.

Lifecycle:

1. Task start: substrate creates shadow workspace; stores path on `TaskRecord.workspace_ref` (extends ADR-018).
2. Every agent edit: substrate writes the file, stages it, commits with a synthetic message.
3. Task completion: substrate produces a squashed PR-candidate against the configured base branch of the real repo.
4. Task failure or `/undo`: substrate discards the shadow workspace; real tree untouched.

## Interface (sketch)

```python
class ShadowGitWorkspace(Protocol):
    workspace_ref: str  # opaque path or handle

    async def commit_edit(self, files: dict[str, str], message: str) -> str: ...      # returns sha
    async def diff_against_base(self) -> str: ...                                       # unified diff
    async def produce_pr_candidate(self, base: str, branch: str) -> PrCandidate: ...
    async def discard(self) -> None: ...

class PrCandidate(BaseModel):
    branch: str
    base: str
    squashed_diff: str
    files_changed: list[str]
```

## Acceptance criteria

- [ ] Each agent edit produces a separate shadow-git commit (per-edit granularity).
- [ ] `produce_pr_candidate` yields a single squashed diff regardless of the number of intermediate commits.
- [ ] `discard` on failure cleans up the shadow workspace without touching the real tree.
- [ ] Span `tools.git.shadow.commit` per ADR-037; one span per edit.
- [ ] Metric `maistro_shadow_git_commits_total{outcome}` per ADR-037.
- [ ] On conductor crash mid-task, the shadow workspace path on `TaskRecord` is sufficient to resume per ADR-056.

## Open questions

1. **Per-wave branches inside one shadow repo, or one shadow repo per wave?** Deferred to ADR-052. Recommend per-wave branches inside one shared shadow repo so `git merge` handles fan-in cheaply.
2. **Squash vs preserve-history at PR production.** Recommend recipe knob `output.history: squashed | preserved`, default squashed.
3. **Storage backend.** Local-FS-with-volume for v0; revisit if cold-start hurts or cross-pod resumption becomes a requirement.
4. **Retention of shadow repos post-task.** Recommend tie to ADR-037 event-log retention by recipe sensitivity tier (ADR-055); default 7 days.
5. **Squashed-commit author/committer attribution.** Recommend a per-recipe synthetic author; per-edit micro-commits carry the original agent id.

## Source references

- `maistro-engine:src/maistro/tools/git/` — existing substrate module (currently scaffolding only).
- `maistro-engine:src/maistro/tasks/runner.py` — TaskRunner integration point.
- `maistro-engine:src/maistro/tasks/queue.py` — `TaskRecord` (ADR-018) gains `workspace_ref` field.
- hermes-desktop Edit flow — shadow-workspace pattern (exact path tbd; link in PR).

## Out of scope

- Cross-task workspace sharing (each task is isolated).
- Pushing the PR candidate to a remote (consumer concern; substrate hands back a `PrCandidate`).
- Conflict resolution with concurrent human edits to the real repo.
- Long-lived per-tenant shadow repos (revisit if needed).
