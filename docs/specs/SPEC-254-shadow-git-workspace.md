---
id: SPEC-254
title: "Agent file-edit rollback via shadow git workspace (ADR-049)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-018
  - maistro-engine#ADR-037
related:
  - maistro-engine#ADR-052
  - maistro-engine#ADR-056
implements:
  - maistro-engine#ADR-049
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/tools/git/test_shadow.py
layer: Tools
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-254: Agent file-edit rollback via shadow git workspace

> **Convergence note (2026-08-19).** This spec is marked `Implemented` over
> code with no path from any process entry point — see
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363). It
> tracks ADR-049, now `Deprecated`.
>
> The status is left unchanged because the spec lifecycle has no way to
> express this. From `Implemented` a spec may only become `Superseded`, which
> requires a `superseded-by`, and no successor document exists. There is no
> `Deprecated` state for specs as there is for ADRs. Correcting this needs
> either the successor spec or a lifecycle change, so the note carries the
> truth in the meantime.


## Context

ADR-049 requires every agent edit during a task to land in an isolated shadow git workspace —
per-edit commits for atomic rollback, with a single squashed diff produced at task completion so
the consumer sees one reviewable change instead of the agent's intermediate experimentation.
`maistro/tools/git/` exists today as scaffolding only with no shadow-workspace primitive. This
SPEC implements the workspace lifecycle end-to-end against the real `git` CLI (not mocked) since
the operations are local filesystem + subprocess calls that are cheap and deterministic to test
directly with a real temporary repo.

## Goals

- Add `maistro/tools/git/shadow.py`:
  - `create_shadow_workspace(root: Path, task_id: str) -> ShadowGitWorkspace` — creates
    `root / task_id`, runs `git init`, makes an empty base commit (so `diff_against_base` always
    has a real base SHA to diff against), returns a `ShadowGitWorkspace` whose `workspace_ref` is
    the workspace directory path and `base_sha` is that initial commit's SHA.
  - `ShadowGitWorkspace` (dataclass wrapping `workspace_ref: Path`, `base_sha: str`):
    - `commit_edit(files: dict[str, str], message: str) -> str` — writes each `path -> content`
      pair (relative to `workspace_ref`, creating parent dirs as needed), `git add`s them, commits
      with `message`, returns the new commit SHA. One call = one commit (per-edit granularity).
    - `diff_against_base() -> str` — `git diff <base_sha> HEAD`, the unified diff text.
    - `produce_pr_candidate(base: str, branch: str) -> PrCandidate` — creates `branch` at current
      HEAD, returns a `PrCandidate` with `squashed_diff` = `git diff base..HEAD` (a single unified
      diff regardless of how many intermediate commits exist) and `files_changed` = `git diff
      --name-only base..HEAD` split into a list. Does not push or touch any remote — `base` here
      is `self.base_sha` in the common case but is accepted as a parameter so a caller can diff
      against a different point.
    - `discard() -> None` — `shutil.rmtree(workspace_ref)`; safe to call on an already-discarded
      workspace (no-op if the directory doesn't exist).
  - `PrCandidate` (frozen dataclass): `branch: str`, `base: str`, `squashed_diff: str`,
    `files_changed: list[str]`.
- All git invocations use `subprocess.run(["git", ...], cwd=workspace_ref, check=True,
  capture_output=True, text=True)` — no shell string interpolation, consistent with the rest of
  the codebase's subprocess conventions.

## Non-goals

- `TaskRecord.workspace_ref` field wiring (ADR-018 extension) — follow-up once `TaskRecord` needs
  to persist this for ADR-056 crash recovery; this SPEC's `ShadowGitWorkspace` is usable standalone.
- Per-wave branches inside one shared shadow repo (ADR-052) — ADR-049 explicitly defers this to
  ADR-052; this SPEC's `produce_pr_candidate`/`commit_edit` are single-branch primitives that
  ADR-052's wave orchestration will call once per wave.
- Pushing `PrCandidate` to a remote — ADR-049 explicitly scopes this to the consumer.
- Squash-vs-preserve recipe knob (`output.history`) — `produce_pr_candidate` always produces a
  squashed diff in this SPEC; the preserve-history option is a follow-up recipe-driven branch.
- Retention/cleanup scheduling tied to ADR-037 event-log retention tiers — `discard()` is
  caller-invoked here; a retention scheduler is separate infra.
- `tools.git.shadow.commit` span and `maistro_shadow_git_commits_total` metric (ADR-037 wiring) —
  follow-up once an event-bus/tracer call site wraps these calls.
- Synthetic-author attribution scheme — commits use the ambient git identity (test/CI config);
  per-recipe author mapping is a follow-up once a recipe-overlay call site exists.

## Decision

```python
# maistro/tools/git/shadow.py
@dataclass(frozen=True)
class PrCandidate:
    branch: str
    base: str
    squashed_diff: str
    files_changed: list[str]

@dataclass
class ShadowGitWorkspace:
    workspace_ref: Path
    base_sha: str

    def commit_edit(self, files: dict[str, str], message: str) -> str: ...
    def diff_against_base(self) -> str: ...
    def produce_pr_candidate(self, base: str, branch: str) -> PrCandidate: ...
    def discard(self) -> None: ...

def create_shadow_workspace(root: Path, task_id: str) -> ShadowGitWorkspace: ...
```

## Acceptance criteria

- [x] `create_shadow_workspace` initializes a git repo with one empty base commit; `base_sha` is
      a real, non-empty SHA.
- [x] Two calls to `commit_edit` produce two distinct commits (per-edit granularity) — verified via
      `git log --oneline` count.
- [x] `produce_pr_candidate` after N `commit_edit` calls yields exactly one unified diff in
      `squashed_diff` covering the union of all N edits, regardless of N.
- [x] `produce_pr_candidate`'s `files_changed` lists every file touched across all edits, with no
      duplicates.
- [x] `discard()` removes the workspace directory; the real working tree (a separate temp dir in
      tests, standing in for "the real project") is untouched — verified by asserting its content
      is unchanged after `discard()`.
- [x] `discard()` on an already-discarded workspace does not raise.
- [x] `diff_against_base()` reflects edits made so far and is empty before any `commit_edit` call.

## Testing

- `packages/maistro-core/tests/tools/git/test_shadow.py` (new) — exercises the full lifecycle
  against a real temporary git repo (`tmp_path` fixture, real `git` subprocess calls, no mocking):
  workspace creation, multi-edit commit history, squashed PR-candidate production, discard
  idempotency and real-tree isolation.

## Open questions

- Whether `commit_edit`'s file-write step should reject paths that escape `workspace_ref` (path
  traversal) — deferred; callers in this SPEC's scope are trusted substrate code, not raw agent
  input. Revisit if a future call site accepts unsanitized paths.

## References

- [ADR-049: Agent file-edit rollback via shadow git](../adr/ADR-049-shadow-git-rollback.md)
- [ADR-052: Parallel agent waves](../adr/ADR-052-parallel-agent-waves.md)
- [ADR-056: Task crash recovery](../adr/ADR-056-task-crash-recovery.md)
