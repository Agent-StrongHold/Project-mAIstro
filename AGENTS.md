# maistro-engine

## Purpose

Shared Python runtime and monorepo substrate for AI agent platforms: orchestrator, agents, memory, security, skills, tools, and related packages. Not an end-user product — downstream products (Conductor, Stronghold, Canvas) consume this repo. See [README.md](README.md) and [docs/adr/](docs/adr/) for governance and ADRs.

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
- **ADRs:** `docs/adr/`
- **Project context:** [CLAUDE.md](CLAUDE.md)

## PR conventions

- Prefer focused PRs per package or concern; keep cross-package changes explainable in the PR description.
- Run `uv run pytest` and ruff before pushing when you touch Python.
- Link ADR updates when behavior or public contracts change.

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
