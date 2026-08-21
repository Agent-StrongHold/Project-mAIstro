---
id: SPEC-200
title: Builders Safety Layer — execution contexts + ephemeral workspace
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-06-03
accepted: 2026-06-03
implemented: 2026-06-03
substrate:
  - maistro-engine#ADR-038
  - maistro-engine#SPEC-190
implements: []
related:
  - maistro-engine#SPEC-201
  - maistro-engine#ADR-095
  - maistro-engine#ADR-049
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-bootstrap/tests/
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-03
  - status: Accepted
    date: 2026-06-03
  - status: AC Defined
    date: 2026-06-03
---

# SPEC-200 — Builders Safety Layer: Execution Contexts + Ephemeral Workspace

> **Status:** Implemented — the builders safety layer shipped to `develop` in #107
> (`maistro-bootstrap/src/maistro_bootstrap/builders/`). This document is the spec of record.

---

## Objective

The interactive builders DAG needs to execute untrusted LLM-generated code changes without ever
touching the live filesystem or the live repo state until a human explicitly approves the diff.
Claude Code and similar tools operate directly on the root filesystem — this is the threat model
we are explicitly rejecting.

The safety layer is the **execution context system**: a typed boundary that declares where each
agent is allowed to act, and enforces it at runtime. No agent can exceed its declared context.

### Who uses this

The builders DAG — a graph of agents, not a linear sequence. Nodes include:

| Agent | Role in DAG | Execution Context |
|---|---|---|
| **Arbiter** | Voice of the DAG — drives human clarification conversation until spec + AC are confirmed | CONVERSATION |
| **Scout / Ranger** | Called when the DAG determines external research is needed (docs, standards, examples) | NETWORK (read-only) |
| **Quartermaster** | Template lookup — finds and adapts prior verified specs for similar tasks | CONVERSATION |
| **Frank** | Spec emission — turns confirmed requirements into structured Spec + invariants | CONVERSATION |
| **Archie** | Property test generation from spec invariants | SANDBOX |
| **Mason** | TDD loop: write tests → write code → run checks → fix | SANDBOX |
| **Auditor** | Code review, mock detection, spec coverage, security scan | SANDBOX (read) + CONVERSATION |
| **Janitor** | Repo hygiene: close stale PRs/issues, clean dead branches — against the **real repo** | REPO (gated, human-confirmed per action) |

The DAG is not sequenced — the orchestrator decides which nodes fire based on context. A
pure-conversation task may never enter SANDBOX. A repo hygiene task goes straight to Janitor.
The safety layer must support all of these without conflating them.

## Acceptance Criteria

- **AC-1**: `GitWorktreeWorkspace` creates an ephemeral git worktree in `/tmp/maistro-ws-<id>` and destroys it on exit or failure.
- **AC-2**: `SandboxedShell` refuses any command whose resolved path escapes the workspace root (`SandboxEscapeError`).
- **AC-3**: `SandboxedShell` refuses any command that exceeds its timeout (`TimeoutError`).
- **AC-4**: Every agent declares an `ExecutionContext`; orchestrator raises `ContextViolation` if a stage handler uses an undeclared context.
- **AC-5**: `RepoContext` requires explicit human confirmation before each destructive action (`UnconfirmedRepoAction` if called without token).
- **AC-6**: `GitWorktreeWorkspace.diff()` produces a valid unified diff with no ephemeral metadata leaks.
- **AC-7**: `WorkspaceContext.apply_diff()` uses `git apply --check` before `git apply`; raises `DiffApplyError` on failure without touching real repo.

### Success criteria

1. `GitWorktreeWorkspace` creates an ephemeral `git worktree` in `/tmp/maistro-ws-<id>` and
   destroys it on exit or failure — verified by asserting the path does not exist after teardown.
2. `SandboxedShell` refuses any command whose resolved path argument escapes the workspace root —
   verified by attempting `../../etc/passwd` and asserting `SandboxEscapeError` is raised.
3. `SandboxedShell` refuses any command that exceeds its timeout — `TimeoutError` raised.
4. Every agent that registers with the orchestrator declares an `ExecutionContext`; the
   orchestrator raises `ContextViolation` if a stage handler tries to use a context it didn't
   declare.
5. `RepoContext` (Janitor's context) requires explicit human confirmation before each destructive
   action; it raises `UnconfirmedRepoAction` if called without a confirmation token.
6. The diff from `GitWorktreeWorkspace.diff()` is a valid unified diff string representing only
   changes inside the workspace — no ephemeral metadata leaks out.
7. `WorkspaceContext.apply_diff()` applies an approved diff to the real repo using
   `git apply --check` before `git apply` — if check fails, `DiffApplyError` is raised, real
   repo is untouched.

---

## Execution Contexts

Four contexts, strictly separated:

```
ExecutionContext (enum)
├── CONVERSATION   — pure I/O, no filesystem, no network side effects
├── NETWORK        — read-only external fetches (HTTP GET only, no auth tokens exposed)
├── SANDBOX        — ephemeral git worktree; read + write allowed inside root only
└── REPO           — real repo; each destructive action requires a confirmation token
```

The SANDBOX context is the heart of this spec. Everything else is lighter.

---

## Components

### 1. `GitWorktreeWorkspace`

```
packages/maistro-core/src/maistro/builders/workspace.py
```

Responsibilities:
- Create: `git worktree add /tmp/maistro-ws-{id} -b builders/{id} {base_ref}`
- Expose `root: Path` — the absolute path to the worktree
- Teardown: `git worktree remove --force /tmp/maistro-ws-{id}` + branch delete
- `diff() -> str` — unified diff of worktree vs base ref (pipe to `git diff`)
- `commit(message: str) -> str` — commit inside worktree, return sha
- Context manager protocol (`__enter__` / `__exit__`) — teardown on any exit including exception
- `status: WorkspaceStatus` — ACTIVE | COMMITTED | TORN_DOWN
- Teardown is idempotent — calling it twice is safe

Invariants:
- `root` is always under `/tmp/` — never under the real repo root or any project directory
- The worktree branch name is always `builders/{id}` — never `main`, `develop`, `integration`
- On teardown, the branch is deleted unless `keep_branch=True` is passed

### 2. `SandboxedShell`

```
packages/maistro-core/src/maistro/builders/workspace.py  (same file)
```

Responsibilities:
- `run(cmd: list[str], *, timeout: float = 30.0) -> ShellResult`
- CWD is always `workspace.root` — not configurable
- Before execution: scan all string arguments; if any resolves (via `os.path.realpath`) to a path
  outside `workspace.root`, raise `SandboxEscapeError(arg, workspace.root)`
- After timeout: kill subprocess, raise `CommandTimeoutError(cmd, timeout)`
- Blocked commands (raises `BlockedCommandError`): `rm -rf /`, `sudo`, `su`, `chmod 777`,
  `curl | bash`, `wget | sh`, `git push` (pushing from sandbox is never allowed — diff goes
  through `WorkspaceContext.apply_diff()` instead)
- Captures stdout + stderr; returns `ShellResult(returncode, stdout, stderr, elapsed_seconds)`
- Max output: 1 MB captured; beyond that, `OutputTruncatedWarning` is emitted and output is
  truncated (not dropped — first 512KB + last 512KB)

### 3. `RepoContext`

```
packages/maistro-core/src/maistro/builders/repo_context.py
```

Responsibilities (Janitor's interface):
- Every destructive action (`close_pr`, `delete_branch`, `close_issue`) requires a
  `ConfirmationToken` — a short-lived signed token issued by the HITL gate
- `ConfirmationToken` expires after 60 seconds and is single-use
- `audit_log: list[RepoAction]` — every action (confirmed or rejected) is logged
- Read operations (`list_prs`, `list_branches`, `list_issues`) require no token
- Raises `UnconfirmedRepoAction` if a destructive action is called without a valid token

```python
# Usage contract:
ctx = RepoContext(repo_path, github_client)
prs = ctx.list_stale_prs(older_than_days=30)   # no token needed
token = hitl_gate.request_confirmation(f"Close {len(prs)} stale PRs?")
ctx.close_pr(prs[0].number, token=token)        # token consumed
# token is now expired — next action needs a new token
```

### 4. `WorkspaceContext` (coordinator)

```
packages/maistro-core/src/maistro/builders/workspace.py
```

Ties workspace + shell + diff application together:

```python
class WorkspaceContext:
    workspace: GitWorktreeWorkspace
    shell: SandboxedShell

    def diff(self) -> str: ...
    def apply_diff(self, *, confirmed: bool) -> ApplyResult:
        # git apply --check first; if confirmed=True and check passes, git apply
        # if confirmed=False, raises UnconfirmedDiffApply
        # if check fails, raises DiffApplyError (real repo untouched)
```

### 5. `ExecutionContext` declaration on agent registration

```
packages/maistro-core/src/maistro/builders/runtime.py  (extend existing)
```

When a stage handler is registered, it declares its context:

```python
runtime.register(
    worker=WorkerName.MASON,
    stage="tests_written",
    handler=mason_write_tests,
    context=ExecutionContext.SANDBOX,        # new required field
)
```

The `BuildersRuntime.execute()` method checks that the active run has a workspace matching the
declared context before calling the handler. If not, raises `ContextViolation`.

---

## Errors

All in `packages/maistro-core/src/maistro/builders/errors.py` (new file):

```python
SandboxEscapeError(arg: str, root: Path)       # path escape attempt
BlockedCommandError(cmd: list[str])            # blocked command attempted
CommandTimeoutError(cmd: list[str], timeout)   # command exceeded timeout
ContextViolation(agent, declared, attempted)   # wrong context used
UnconfirmedRepoAction(action: str)             # Janitor called without token
UnconfirmedDiffApply()                         # apply_diff called with confirmed=False
DiffApplyError(check_output: str)              # git apply --check failed
OutputTruncatedWarning(bytes_dropped: int)     # informational only
WorkspaceTeardownError(path: Path, detail)     # teardown failed (non-fatal warning)
```

---

## Project Structure

```
packages/maistro-core/src/maistro/builders/
├── contracts.py          # existing — WorkerName, RunRequest, RunResult (extend: add context field)
├── orchestrator.py       # existing — stage machine (extend: enforce context on execute)
├── runtime.py            # existing — stage dispatcher (extend: context param on register)
├── workspace.py          # NEW — GitWorktreeWorkspace, SandboxedShell, WorkspaceContext
├── repo_context.py       # NEW — RepoContext, ConfirmationToken, RepoAction audit log
└── errors.py             # NEW — all builder safety errors

packages/maistro-core/tests/builders/
├── test_workspace.py     # NEW
├── test_sandbox_shell.py # NEW
└── test_repo_context.py  # NEW
```

---

## Testing Strategy

Framework: pytest + unittest.mock. No real git operations in unit tests — use `tmp_path` fixture
for filesystem tests and mock `subprocess.run` for shell tests.

**Integration tests** (tag `@pytest.mark.integration`, skipped in CI unless `RUN_INTEGRATION=1`):
- Actually call `git worktree add/remove` against the real repo
- Actually run `pytest` inside the worktree

**Unit test coverage targets:**
- `SandboxedShell`: all blocked commands, path escape (relative, absolute, symlink), timeout,
  output truncation, happy path
- `GitWorktreeWorkspace`: create, teardown, idempotent teardown, diff, commit, status transitions
- `WorkspaceContext.apply_diff`: `confirmed=False` → raises, check-fails → raises + real repo
  untouched, check-passes + `confirmed=True` → applies
- `RepoContext`: read without token, write without token → raises, write with expired token →
  raises, write with valid token → succeeds + token consumed + audit log entry

---

## Boundaries

**Always:**
- `SandboxedShell.run()` always sets `cwd=workspace.root`
- `GitWorktreeWorkspace` always creates under `/tmp/`, never under the real repo
- `WorkspaceContext.apply_diff()` always runs `git apply --check` before `git apply`
- All `RepoContext` destructive actions always write to the audit log regardless of outcome

**Ask first:**
- Adding new blocked commands to `SandboxedShell`
- Changing the `/tmp/` constraint to a different sandbox root
- Changing `ConfirmationToken` TTL or single-use semantics

**Never:**
- `git push` from inside a sandbox — diffs exit through `apply_diff()` only
- Deleting `workspace.root` with `shutil.rmtree` — always use `git worktree remove --force`
  (avoids leaving dangling git refs)
- Silently swallowing `SandboxEscapeError` or `ContextViolation` — these are always hard failures

---

## Open Questions

1. **Janitor's GitHub client** — `RepoContext` takes a `github_client` parameter. Does Janitor
   use PyGithub, ghapi, or the `gh` CLI subprocess? Homelab context probably means `gh` CLI is
   already authed. Preference?

2. **HITL confirmation gate** — `ConfirmationToken` needs to be issued by something. For the
   CLI/TUI, that's a `y/N` prompt. For the web UI, it's a modal. Should the token issuer be
   injected (DI) or is a simple `input()` wrapper acceptable for the CLI MVP?

3. **Workspace root** — hardcoded `/tmp/maistro-ws-{id}`? Or configurable via
   `MAISTRO_WORKSPACE_ROOT` env var? The env var gives more flexibility (e.g. a dedicated tmpfs
   mount) without breaking the `/tmp/` invariant.

4. **`builders/{id}` branch naming** — should the branch be `builders/{id}` or should it
   incorporate the task description (e.g. `builders/add-version-flag-{id[:8]}`)? More readable
   in git log but slightly more complex to sanitize.
