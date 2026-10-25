---
id: SPEC-180
title: maistro-install bootstrap contract
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-05-13
accepted: 2026-05-13
implemented: 2026-05-13
substrate:
  - maistro-engine#ADR-002
implements: []
related:
  - maistro-engine#ADR-033
  - maistro-engine#SPEC-176
contracts:
  - boundary
tests:
  - packages/maistro-bootstrap/tests/test_plan.py
  - packages/hive-conductor/backend/tests/test_api.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Accepted
    date: 2026-05-13
  - status: AC Defined
    date: 2026-05-13
---

# SPEC-180: maistro-install bootstrap contract

## Context

Operators need a **repeatable** path from feature intent → printed or applied commands. Hive Conductor and CI must share the **same structured plan** as the terminal CLI.

## Decision

- **Answers schema v1** (`InstallAnswersV1` in `packages/maistro-bootstrap/src/maistro_bootstrap/schema.py`):
  - `schema_version: "1"`, `features`, `compose_addons`, `product`, `dry_run`, `install_mode`,
    `llm_gateway`, `observability_backend`, `deployment_tier`, `container_runtime`, `users_intent`,
    `stack_bringup`, `provider_accounts` (booleans only — **no API keys** in YAML).
- **Plan object** (`build_install_plan`): JSON-serializable dict with `kind: maistro_install_plan`, `shell_commands`, `compose_profile_hints`, `preview_notes`, optional `apply_spec` (`cwd` + `argv`), `copier_command`.
- **CLI** (`maistro-install`): `--json` emits the plan; `--apply` with `--no-dry-run` runs `apply_spec` only (`docker|podman compose build --pull never` from monorepo root — builds `build:` services only; run `compose up` yourself for dependencies). Default remains print-only (`--dry-run`).
- **Hive API** (when `packages/maistro-bootstrap/src` is on disk next to Hive — monorepo checkout; else **503**):
  - `GET /v1/install/session` — default answers template + `secrets_policy_doc` pointer.
  - `POST /v1/install/session` — merge partial JSON with defaults via `merge_session_payload`; returns normalized `answers` (no plan).
  - `POST /v1/install/plan` — same JSON body as `maistro-install --json` plan output.
- **Stub manifest** (`stub_manifest.yaml`): merges `[preview]` lines for features not fully wired.

## Out of scope

- **Stronghold / multi-tenant product** code in this repo (per resolver-matrix): print Copier hints only.
- **`curl | bash` remote fetch** of a pinned installer payload: `scripts/install-maestro.sh` documents clone + `uv` only for now.
- **Automatic OS package installation** (brew, dnf, …): wizard prints hints; execution stays explicit.

## Acceptance Criteria

- **AC-1**: `uv run maistro-install --answers-file docs/install/examples/answers-v1-minimal.yaml --json` prints valid JSON with `kind` and `shell_commands`.
- **AC-2**: `pytest packages/maistro-bootstrap/tests` passes without Docker.
- **AC-3**: `GET` / `POST /v1/install/session` and `POST /v1/install/plan` in monorepo CI return 200 with the expected `kind` values (or 503 only when layout is intentionally non-monorepo).


## References

- [docs/install/resolver-matrix.md](../install/resolver-matrix.md)
- [ADR-033: Templates and Copier workflow](../adr/ADR-033-templates-and-copier-workflow.md)
- [packages/maistro-bootstrap/README.md](../../packages/maistro-bootstrap/README.md)
