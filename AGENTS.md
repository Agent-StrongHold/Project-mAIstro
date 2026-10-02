# maistro-engine

## Purpose

Shared Python runtime and monorepo substrate for AI agent platforms: orchestrator, agents, memory, security, skills, tools, and related packages. **v1.0 ships Workspaces** (`packages/hive-conductor`) alongside the library; Stronghold and Canvas book-maker are downstream. See [README.md](README.md), [ROADMAP.md](ROADMAP.md), [BACKLOG.md](BACKLOG.md), and [docs/adr/](docs/adr/) for governance and ADRs.

## Stack

- Python **3.12+** (strict typing with mypy)
- **uv** workspace — root meta-package `maistro-workspace`; code in `packages/*`
- **FastAPI**, **SQLAlchemy** (async) + **asyncpg**, **Alembic**, **LiteLLM**, **structlog**
- Packages: `maistro-core`, `maistro-server`, `maistro-turing`, `maistro-canvas`, `maistro-bootstrap`, `maistro-registry`; reference app `packages/hive-conductor`

## Build and test commands

| Step | Command |
|------|---------|
| Install deps | `uv sync` |
| Run tests | `uv run pytest` |
| Lint / format | `uv run ruff check .` and `uv run ruff format .` |
| Typecheck | `uv run mypy packages/maistro-core/src packages/maistro-server/src packages/maistro-turing/src packages/maistro-canvas/src packages/maistro-bootstrap/src packages/maistro-registry/src` |
| Expected dirs | `./scripts/verify-monorepo-layout.sh` |
| DB migrations | `uv run alembic upgrade head` (requires Postgres) |
| Local stack | `docker compose up -d` (Postgres + LiteLLM + Langfuse per README) |

## Architecture pointers

- **Canonical library:** `packages/maistro-core/src/maistro/` — agents, memory, classifier, router, builders, protocols, types, agent spec/recipes/spawner, etc.
- **HTTP API:** `packages/maistro-server/src/maistro_server/` — FastAPI app (thin wrapper over core). Prefer `from maistro_server...` in tests and tooling; do not reintroduce a second `maistro.main` at repo root.
- **ADR/spec registry CLI:** `packages/maistro-registry/src/maistro_registry/` — `maistro-registry` console script.
- **Legacy snapshots:** the former `code-worth-implementing-from-*` and `legacy-maistro-site/` trees (once under `potential-dead-code/`) were **removed** per [`docs/specs/SPEC-178`](docs/specs/SPEC-178-legacy-snapshot-retention.md) — their behavior ships under `packages/` (graph execution per [`SPEC-177`](docs/specs/SPEC-177-hyperagent-graph-execution.md)) or lives in the sibling repos; git history retains provenance. New Python work belongs under `packages/*/src/`.
- **Canvas:** `packages/maistro-canvas/src/maistro_canvas/`
- **Turing extensions:** `packages/maistro-turing/src/maistro_turing/`
- **ADRs:** `docs/adr/` — start at [docs/README.md](docs/README.md)
- **v1.0 release contract:** [ROADMAP.md](ROADMAP.md) (Workspaces product, M1 convergence, blockers)
- **Item backlog:** [BACKLOG.md](BACKLOG.md) — CI-checked; run `uv run python scripts/check-backlog-consistency.py` after edits
- **Workspace cutover:** [docs/architecture/WORKSPACE-CUTOVER-PLAN.md](docs/architecture/WORKSPACE-CUTOVER-PLAN.md)
- **Project context:** [CLAUDE.md](CLAUDE.md)

## PR conventions

- Prefer focused PRs per package or concern; keep cross-package changes explainable in the PR description.
- Run `uv run pytest` and ruff before pushing when you touch Python.
- Link ADR updates when behavior or public contracts change.

## Quality ratchets and grants

The repo gates on per-identity ledgers in `quality/*.json` (vulture, radon,
promotion surface, reachability, direct effects, suite inventory). Two rules
account for most blocked PRs:

- **A floor raise takes two merges.** `ratchet_provenance.load_authorizations`
  reads `quality/ratchet-authorizations.json` **from the merge base**, not from
  your branch, so a grant never authorizes the change that introduces it. Land
  the grant first, then the change. The gates say so when they fail
  ("candidate baseline edits cannot approve them") — believe them rather than
  re-running.
- **Banking is not authorizing.** Most ratchets check twice: your ledger must
  match the scan *and* the new debt must be authorized from the base. A clean
  candidate ledger with no grant still fails.

Run a gate with **CI's exact arguments** — `grep` the workflow. The vulture
scan is `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`; its
defaults (`packages`, `tests`) bank rows the blocking job can never see.

**`quality/*.json` merge cleanly while losing rows.** Two branches append, git
auto-resolves to one side, nothing conflicts and nothing asks. After any merge
or `git checkout <ref> -- quality/...`, diff row counts against `origin/develop`
before trusting it; expect `git diff --numstat` to be additions-only when you
meant to add. `vulture-baseline.json` is a **multiset** — it carries intentional
duplicates, so never pass its lists through `set()`.

## Verifying your own work

- **Confirm the push landed.** `git add -A && git commit … && git push` skips the
  push when `commit` exits non-zero — which it does after a conflict-free
  `git merge`, because the merge already committed. Compare
  `git rev-parse HEAD` with `git rev-parse origin/<branch>` afterwards.
- **A missing module and a real violation both exit 1.** A fresh `git worktree`
  venv has base deps only; run `uv sync --locked --extra dev` before trusting a
  gate's exit code, and read its output rather than its status.
- **Show a new test fails against the regression it names.** A test can pass for
  the wrong reason — a fixture that pins the value under test, or a bound that
  encodes the current machine's speed. Assert structure over wall-clock timing
  where the code allows it, and check the degenerate paths, not just the happy
  one.
- **CI failures are often not yours.** Runner shutdowns, and tests that assert a
  transient UI state or a latency bound, fail on PRs that cannot have caused
  them. Read the log before changing code.

## Security and secrets

- Never commit `.env`, API keys, or credentials. Root `.gitignore` already ignores `.env` and `.env.local`.
- Prefer env vars and documented placeholders in `mcp.json` / deployment config.

## What not to edit

- Generated / build output: `dist/`, `build/`, `__pycache__/`, `*.egg-info`
- Remote-synced Cursor rules under `.cursor/rules/imported/` (managed by Cursor, not hand-edited)

## Install and scaffolding

- **Feature slices / Copier commands:** [docs/install/resolver-matrix.md](docs/install/resolver-matrix.md). Run `uv sync --extra bootstrap` then `uv run maistro-install` (interactive TUI or `--answers-file`). JSON plan: `--json`; compose build (no `up`): `--no-dry-run --apply` when answers set `stack_bringup: root_full`. See [SPEC-180](docs/specs/SPEC-180-maistro-install-bootstrap.md).

## Subagent context

Subagents start with a **clean context**. Put durable notes under [`.cursor/context/`](.cursor/context/) and **paste paths or excerpts into Task prompts** when delegating. See [.cursor/context/README.md](.cursor/context/README.md).
