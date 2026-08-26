# maistro-engine

The shared Python runtime — and the consolidation monorepo — behind the Maistro products. Not a library you only import: it also *contains* **Agent Conductor** (the personal/homelab app) and the **canvas ability**, and exposes `maistro-core` for downstream products to import.

```
        ┌────────────────────────────────────────────────────┐
        │                    maistro-engine                   │
        │  shared runtime ........ packages/maistro-core, …   │
        │  Agent Conductor app ... packages/hive-conductor    │
        │  canvas ability ........ packages/maistro-canvas    │
        │  + ADRs/specs + registry CI                         │
        └───────────────────────────┬────────────────────────┘
                                    │ imported by
                     ┌──────────────┴───────────────┐
                     ▼                               ▼
         ┌───────────────────────┐      ┌────────────────────────────┐
         │ Canvas book-maker POC │      │ Stronghold  (planned)       │
         │ (name TBD)            │      │ imports the engine, adds    │
         │ imports maistro-canvas│      │ multi-tenancy + a stricter  │
         │                       │      │ security stance, disables   │
         │                       │      │ homelab/personal features   │
         └───────────────────────┘      └────────────────────────────┘
```

## What this repo is

- **A monorepo** — the shared Python runtime under `packages/maistro-core`, its sibling packages, the **Agent Conductor** app (`packages/hive-conductor`, the personal/homelab product), and the **canvas ability** (`packages/maistro-canvas`). One `uv` workspace, one git repo.
- **Library-first** — `maistro-core` is a pure Python library; the FastAPI surface (`maistro-server`) is a thin wrapper. The app is optional.
- **Canonical ADRs & specs** — architectural decisions and specifications under `docs/adr/` and `docs/specs/`.
- **Registry CI host** — the front-matter validator, link-checker, and registry generator that enforce doc conventions (`packages/maistro-registry`).
- **A fresh cut** — this repository began as a single snapshot commit of a longer private development history. Issue and PR numbers cited in `docs/` and in code comments (e.g. `#350`, `#479`) predate that cut and refer to the private repository's numbering; they are preserved as historical rationale, not links into this repository. New work references this repository's own numbering.

> **History note.** This engine was previously split across several sibling repositories. The canonical shape as of 2026-05 is this single substrate monorepo.

## What this repo is not

- Not, by itself, multi-tenant. Tenant isolation is the Stronghold layer on top of `maistro-core`, not part of core. Core carries the *soft* scope axes (`global → org → team → user → agent → session`), including `org_id`; only the **hard** `tenant` boundary is Stronghold-specific (see [`ADR-019`](docs/adr/ADR-019-canonical-source-split.md) and root `CLAUDE.md` decision 7, which supersedes the older "no `org_id` in core" shorthand).
- Not the place for product-specific UX. Homelab/personal features live in Agent Conductor; the enterprise hardening lives in Stronghold.

## Products

**Shipped in this repo:**

| Product | Lives in | Audience |
|---|---|---|
| **Agent Conductor** | `packages/hive-conductor` (consumes `maistro-core`) | Household / personal, self-hosted |

**Downstream products that import the engine:**

| Product | Imports | Status |
|---|---|---|
| **Canvas book-maker** (name TBD) | `maistro-canvas` (the canvas ability) | POC — frontend app on top of the canvas engine |
| **Stronghold** | `maistro-engine` | Planned — refactor to import the engine, add multi-tenancy + a stricter security stance, and disable homelab/personal features |

The line between shared runtime and product-specific code is defined in [`ADR-019`](docs/adr/ADR-019-canonical-source-split.md): `maistro-core` stays product-agnostic; tenancy, security posture, and feature toggles live in the importing product.

## Quick start

```bash
# Requires Python 3.12+ (CI tests 3.12; the container image pins 3.13) and uv — https://github.com/astral-sh/uv
uv sync                               # install every package in the workspace
uv sync --extra bootstrap             # optional: maistro-install TUI / answers-file planner
uv run pytest                         # run the test suite
docker compose up -d                  # full local stack (Postgres + LiteLLM + Langfuse)
```

The engine image applies migrations automatically before it starts the API.
Migration runners serialize through a PostgreSQL advisory lock, so multiple
replicas cannot race the schema. A migration failure keeps readiness down and
terminates the container with a non-zero status. Do not shell-source `.env`:
Compose reads it directly, preserving the JSON representation of `API_KEYS`.

Alembic and the application resolve that URL through the same function
(`require_database_url`, [#187](https://github.com/Agent-StrongHold/Project-mAIstro/issues/187)),
so `DATABASE_URL` and the `DB_*` variables both work and mean the same thing.
PostgreSQL 18 volume and major-upgrade guidance is in
[`docs/install/postgres-volume-upgrades.md`](docs/install/postgres-volume-upgrades.md).

The repo is a `uv` workspace: **nine Python packages**, plus the **`packages/hive-conductor`** reference app (frontend + backend + Docker).

> **Platform compatibility:** MAIstro targets modern 64-bit platforms. Intel (x86_64) Macs and 32-bit Windows have limited compatibility because `cryptography` 50.x no longer provides those upstream wheel/support paths. Apple Silicon Macs, 64-bit Windows, and supported 64-bit Linux platforms are the normal targets.

| Package / tree | Purpose |
|---|---|
| `maistro-core` | The library: orchestration, agents, memory, security, skills, tools, router |
| `maistro-server` | FastAPI HTTP surface around `maistro-core` |
| `maistro-turing` | Autonoetic self-model package (mood, drives, proactive producers) |
| `maistro-canvas` | Canvas engine (Python library) + the standalone Node book-maker POC |
| `maistro-evolve` | Elo-tournament optimizer for agent self-improvement |
| `maistro-bootstrap` | `maistro-install` TUI and answers-file planner (`uv sync --extra bootstrap`) |
| `maistro-registry` | Front-matter validation, link checks, registry generation |
| `maistro-rsi` | Recursive self-improvement: sandboxed self-branch cycles, quarantine gate (`maistro-rsi` CLI) |
| `maistro-design` | Open Design integration: renderer registry, `/v1/design/*` routes |
| `packages/hive-conductor/` | Agent Conductor reference app: React frontend, FastAPI backend, Docker |

## Architecture at a glance

```
request ──► conduit ──► classifier ──► orchestrator ──► router ──► agent ──► tools / memory / LLM
                                                                  │
                                                            (security gates,
                                                             quota, retries,
                                                             observability)
```

- **conduit** — single entry point; classifies, routes, delegates
- **orchestrator** — plans tasks, manages execution, tracks state
- **router** — picks model and agent via the scoring formula `quality^(qw·p) / (1 + normalized_cost)^cw`
- **agents** — base / factory / strategies / roster + A2A delegation
- **memory** — learning, episodic, outcome stores; episodic decays without reinforcement (driven hourly, see feature table). **Not vector-backed:** the learnings/outcome Postgres stores have no embedding column; retrieval is keyword/attribute matching
- **security** — Warden (input), Sentinel (output), Gate (boundary), PII filter. ⚠️ **These are library components, not a pipeline the Conductor's chat path currently traverses** — see #350 and `SECURITY.md`
- **skills** — marketplace + Forge + canary (library only; the Conductor's Skills UI is a separate CRUD store — see feature table)
- **graph** — DAG execution: nodes, executor, optimizer ([`ADR-062`](docs/adr/ADR-062-graph-execution-protocol.md))
- **observability** — traces, Prometheus metrics, structlog logs, domain events ([`ADR-037`](docs/adr/ADR-037-observability-taxonomy.md))
- **resilience** — retries, circuit breakers, fallbacks ([`ADR-038`](docs/adr/ADR-038-reliability-taxonomy.md))

## v1 feature status

<!-- release-status:begin -->
> **Released:** none &nbsp;·&nbsp; **Version in the tree:** 0.9.0 &nbsp;·&nbsp; **Next release target:** 1.0.0
>
> **Nothing has been released yet** — the repository has no release tags. A row marked
> **Complete** means the code does what its name says today; it does not mean you can
> install it. Versioning is lockstep across the monorepo from the root `VERSION` file
> ([`ADR-073126-c4e1`](docs/adr/ADR-073126-c4e1-release-and-versioning-process.md)).
> Each number above is a labelled field, and `scripts/check-release-consistency.py`
> fails CI when any of them stops matching what it comes from: `Released` against the
> repository's `vX.Y.Z` tags, `Version in the tree` against `VERSION`, and
> `Next release target` against `CHANGELOG.md`'s pending heading.
<!-- release-status:end -->

Every row below was verified against the code, not against intent. **Status means what a
user actually gets**, not whether a module exists — this repo has repeatedly shipped correct,
tested modules with no call path, so "the code is there" is not the bar.

| | Meaning |
|---|---|
| **Complete** | Works as the name implies. |
| **Partial** | Works, but materially narrower than the name suggests. The limitation is stated. |
| **TODO** | Reachable in the UI/API but does **not** do what it says. Do not rely on it. |
| **v1.1+** | Deliberately not in v1. |

### Agent Conductor — web UI

| Feature | Status | Notes |
|---|---|---|
| Chat (sessions, streaming) | **Complete** | Requires an LLM gateway; without one it returns a visibly-labelled stub reply. |
| DAG builder / runs / SSE events | **Complete** | Real `maistro.graph` execution. Refuses to run against a stub LLM. |
| DAG feedback, optimizer, eval-judge | **Complete** | Optimizer inbox is a real validation gate + hill-climb. |
| Agents, MCP servers, Skills — CRUD | **Complete** | Local stores. |
| MCP connectivity test | **Complete** | Real probe. |
| Setup wizard, auth, profile, credentials, settings, audit log | **Complete** | |
| Capabilities + HITL approvals inbox | **Complete** | Also via `maistro approvals`. |
| Message board, memory browser, docs | **Complete** | |
| Evolution (population, tournament, champion) | **Partial** | Real cycles; population is **in-process and lost on restart**. |
| Dashboard | **Partial** | KPI cards (`runs_today`, `avg_latency_ms`, `total_cost`, `ttft_ms`) are **hardcoded zeros**. Layout and widgets are real. |
| Quotas | **Partial** | LiteLLM spend is real; quota/limit/remaining bars are structurally always `0` — LiteLLM has no quota concept. |
| Containers | **Partial** | Real Docker client, but no compose file mounts the socket into the Conductor, so it reads as "no containers". |
| Knowledge base / memory API | **Partial** | A plain key-value store — **not** `maistro.memory`. See *reinforce/decay/contradict* below. |
| Missions | **Partial** | Real when an engine is configured; otherwise silently falls back to inert in-memory records. |
| Deck builder | **Partial** | AI generation is real; the slide library is hardcoded demo content. |
| Topology | **Partial** | Agent/MCP/skill graph. Does not use the `/v1/topology` compare API. |
| **Schedules — execution** | **TODO** | Schedules can be created, the cron matcher ticks, and `last_run` advances — but **nothing is ever executed**. "Run now" only stamps a timestamp. |
| **Design Studio** | **TODO** | The six-node pipeline is a `setTimeout` animation with template-string output. No image is produced. |
| **Forge (agents, skills)** | **TODO** | Fabricates a record with a generated name. No LLM is called. |
| **Scan (agents, skills, MCP)** | **TODO** | Returns `{"findings": [], "status": "clean"}` unconditionally. Nothing is scanned. |
| **Memory reinforce / decay / contradict** | **TODO** | Increments/decrements an integer. Not the `maistro.memory` decay or weight-floor logic. |
| **CLI page** | **TODO** | A simulated terminal supporting four hardcoded `hctl` strings. |
| **Containers build / suggest Dockerfile** | **TODO** | Canned status string; one hardcoded Dockerfile. |
| RSI page | **v1.1** | `maistro-rsi` is not installed in the shipped image. Use the `maistro-rsi` CLI. |
| Work Items → post to Jira | **v1.1** | PM-POC mode only, and the post is a stub. |

### APIs

| Feature | Status | Notes |
|---|---|---|
| `maistro-server` — tasks, OpenAI-compatible chat, webhooks, WS, `/metrics` | **Complete** | Webhooks fail closed without a secret. |
| Conductor `/v1/*` — the surfaces marked Complete above | **Complete** | |
| `/v1/design/*` | **Complete** | No UI consumes it. |
| `/v1/harness/*` (inbound foreign-harness API) | **Complete** | Lets another orchestrator drive this instance. |
| `/v1/models` | **Partial** | Four hardcoded pseudo-models. |
| `/v2/canvas` | **TODO** | Every route 503s — nothing injects the canvas store. |
| Program / Work Items / PM Fleet / agent invoke | **v1.1** | `MAISTRO_POC_MODE=pm` only; 404 in a default install. |

### CLI and packages

| Feature | Status | Notes |
|---|---|---|
| `curl \| bash` installer (`get.sh`, `install.sh`, `get.ps1`) | **Complete** | Includes WSL2 setup on Windows. |
| `maistro install` / `launch server` / `builders` / `approvals` | **Complete** | |
| `maistro-install`, `maistro-registry` | **Complete** | |
| `maistro-rsi`, `maistro-rsi-autorun` | **Complete** | The real RSI product is the CLI, not the UI page. |
| `maistro upgrade` | **Partial** | `git pull` + `uv sync`. Does nothing useful for a tarball install. |
| `maistro launch tui` | **TODO** | Prints "coming soon". |
| `maistro-core`, `-server`, `-evolve`, `-registry`, `-bootstrap`, `-design` | **Complete** | |
| `maistro-canvas` (Python library) | **Complete** | Library only — no route in this repo mounts it. |
| Canvas book-maker (Node app, Lulu print ordering) | **Partial** | Runs standalone; not in the root compose or installer. |
| `maistro-turing` | **v1.1** | A separate FastAPI app; its former Astro frontend has been removed from this repo and it is not deployed by compose or the installer. |
| Flutter gateway node | **v1.2** | Planned/spec-only; the former README shell was removed and no implementation is present in this tree. |

### Known non-features

These exist in the tree with **no production call path** — nothing outside their own tests
constructs them, so they do nothing in a running system. They are not v1 features and are not
advertised as working.

*Whole subsystems:* `maistro.builders`, `ontology`, `scheduling`, `governance`, `delivery`,
`portability`, `repertoire`, `collaboration`, `code_registry`, `sandbox`, `integrations`.

*Individual capabilities inside subsystems that otherwise do work* — these are the harder ones
to spot, because the package around them is live:

| Unreachable | Documented as | Reality |
|---|---|---|
| `memory/episodic/retrieval.py` | SPEC-243 / ADR-080(D) hybrid BM25 + vector ranking | Nothing retrieves memory through it; there is no ranked retrieval at runtime. |
| `credentials/pool.py`, `rotation.py` | SPEC-222 / ADR-063 credential pool + rotation-on-exhaustion | Unrelated to `maistro credentials rotate-key`, which rotates the *master key* and does work. |
| `graph/scout.py` | ADR-062 | Not consulted by the executor. |
| `config/loader.py` | SPEC-062226-fb23 | Settings come from `config/settings.py`. |
| `agents/spec/`, `agents/spawner/` | ADR-005 / ADR-008 / ADR-009 | Reachable only from each other. |
| `maistro_canvas/canvas/asset_*` | ADR-040/042/043/044/067, SPEC-220/221/229 | The asset pipeline is a closed island; `/v2/canvas` 503s regardless. |
| `maistro_design/nodes.py` | ADR-061 / SPEC-234 | `/v1/design/*` works without it. |
| `graph/durable_runs/` | — | DAG runs are in-memory only. |

`maistro.testing` is also unreachable from the app, which is correct — it is test scaffolding.

This list came out of a reachability sweep (#357) and supersedes any earlier claim that a
symbol's existence implies it runs.

See [`KNOWN-GAPS.md`](KNOWN-GAPS.md) for shipped-but-limited behavior, and
[`SECURITY.md`](SECURITY.md) / [`COMPLIANCE.md`](COMPLIANCE.md) for which security controls
are operative versus specified.

For the subsystem-by-subsystem view — who owns each subsystem's lifecycle, persistence and
authorization today, and whether it is being kept, migrated, retired or connected — see
[`docs/architecture/CONVERGENCE-MATRIX.md`](docs/architecture/CONVERGENCE-MATRIX.md). It is
CI-checked against the code it describes, so a stale row fails the build rather than
misleading a reader.

## ADRs and specs

- All architectural decisions are recorded as ADRs under `docs/adr/`.
- Front-matter and cross-reference conventions are defined in [`ADR-031`](docs/adr/ADR-031-front-matter-and-registry.md); acceptance criteria are layered contracts per [`ADR-032`](docs/adr/ADR-032-contracts-as-acceptance-criteria.md).
- **Legacy archives:** the former `potential-dead-code/` reference trees were **removed** once their behavior shipped under `packages/` ([`SPEC-178`](docs/specs/SPEC-178-legacy-snapshot-retention.md)); provenance remains in git history and the sibling repos.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full author guide. The essentials:

- Branch model is `feature/* → develop → integration → main` — base feature work off `develop`, never open PRs against `main` directly ([`ADR-095`](docs/adr/ADR-095-four-tier-branch-model.md)).
- ADRs live in `docs/adr/ADR-NNN-<slug>.md` with required front-matter ([`ADR-031`](docs/adr/ADR-031-front-matter-and-registry.md)); validate with `python -m maistro_registry.cli lint .`.
- Tests carry `@pytest.mark.contract` and `@pytest.mark.scope(...)` ([`ADR-032`](docs/adr/ADR-032-contracts-as-acceptance-criteria.md)).
- External-library adoption follows [`ADR-039`](docs/adr/ADR-039-external-library-adoption-policy.md): import / service-boundary / pattern-reference / reject.

## Layout

```
maistro-engine/
├── docs/
│   ├── adr/                          # Architecture Decision Records
│   ├── specs/                        # Numbered engine specs (SPEC-NNN)
├── packages/
│   ├── maistro-core/                 # The library
│   ├── maistro-server/               # FastAPI surface
│   ├── maistro-turing/               # Autonoetic self-model package
│   ├── maistro-canvas/               # Canvas ability (Canvas Studio)
│   ├── maistro-evolve/               # Elo-tournament optimizer
│   ├── maistro-bootstrap/            # maistro-install planner
│   ├── maistro-registry/             # Registry / front-matter CI helpers
│   └── hive-conductor/               # Agent Conductor reference app (frontend + backend + Docker)
├── formal/                           # Property-based conformance tests (Hypothesis; separate CI)
├── templates/                        # Copier templates (per ADR-033)
├── scripts/                          # Repo maintenance scripts
├── alembic/                          # DB migrations
├── tests/                            # Shared / registry pytest tree (in `testpaths`)
├── docker-compose.yml                # Local dev stack
├── pyproject.toml                    # uv workspace root (uv.lock is source of truth)
├── CONTRIBUTING.md                   # Author-facing how-to
└── README.md                         # this file
```

## License

Licensed under the Apache License, Version 2.0 (SPDX: `Apache-2.0`) — see
[`LICENSE`](LICENSE) for the full text.

Every distributable package under `packages/` declares `license = "Apache-2.0"` in its
`pyproject.toml` and ships a copy of the license in its wheel, so the terms travel with the
artifact rather than only with this repository.

```
Copyright 2026 The Maistro Engine authors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
```
