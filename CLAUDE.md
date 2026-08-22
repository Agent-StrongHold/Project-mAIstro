# CLAUDE.md — Maistro Engine

**Project:** Maistro Engine — Shared Python runtime for AI agent platforms
**License:** Apache 2.0
**Python:** 3.12+ (the version CI actually tests; 3.11 was claimed but never tested)
**PostgreSQL:** 17-19, 18 recommended. CI matrixes 17 and 18 against `pgvector/pgvector`;
19 is expected to work and is added the day a pgvector image ships for it. Below 17 the
container refuses at startup rather than failing later.

---

## Architecture

Consolidation **monorepo** (single git repo, `uv` workspace) with 9 Python packages + the hive-conductor app. It is *not* just a library: it **contains** the Agent Conductor app (`hive-conductor`, the personal/homelab product) and the canvas ability (`maistro-canvas`), and exposes `maistro-core` for downstream products to import. (Was historically split across sibling repos.)

```
packages/
├── maistro-core/      # Shared library: pip install maistro-core
├── maistro-canvas/    # Canvas ability (engine + protocols); the book-maker frontend is a separate app
├── maistro-server/    # FastAPI app (replaces conductor-router)
├── maistro-turing/    # Autonoetic self-model extensions
├── maistro-evolve/    # Elo tournament optimizer for agent self-improvement
├── maistro-registry/  # ADR/spec registry CLI — walk, validate, lint, link-check for docs
├── maistro-rsi/       # Recursive self-improvement: autorun loop, quarantine gate, sandbox
├── maistro-design/    # Open Design integration (renderer registry, SSE ingest)
├── hive-conductor/    # Agent Conductor app (FastAPI backend + React frontend)
└── maistro-bootstrap/ # Bootstrap installer and planner
```

### Product relationship — contains vs. imports

```
maistro-engine (this monorepo)
  │  contains
  ├── Agent Conductor (household/personal)  — packages/hive-conductor (consumes maistro-core)
  └── canvas ability                        — packages/maistro-canvas
  │
  │  imported by downstream products
  ├─→ Canvas book-maker POC (name TBD)      — imports maistro-canvas (separate frontend app)
  └─→ Stronghold (PLANNED)                  — will import maistro-engine, add multi-tenancy +
                                              stricter security, and disable homelab/personal features
```

Agent Conductor ships **here**; the Canvas book-maker and Stronghold are downstream products that **import** the engine (Stronghold is a planned refactor, not yet done).

**ADR-019** defines the canonical source split: maistro-core = product-agnostic shared runtime (no `org_id`); multi-tenancy/security-posture/feature-toggles live in the importing product (Stronghold). Notable decisions include ADR-036 (ontology), ADR-038 (reliability), ADR-062 (graph execution protocol), and ADR-057 (memory exposure mode).

### Naming convention

- `AgentConfig`, `AgentError` — canonical names in maistro-core
- `MaistroConfig`, `MaistroError`, `StrongholdError` — backwards-compat aliases

### maistro-core (the library)

Every subsystem is importable. Consumers add `maistro-core` to their requirements.

| Subsystem | Import | What |
|-----------|--------|------|
| **Memory** | `maistro.memory` | Learnings, episodic, scopes, outcomes |
| **Security** | `maistro.security` | Warden (threat detection), Sentinel (policy), PII filter |
| **Classifier** | `maistro.classifier` | Keyword classification, optional LLM fallback for ambiguous requests, then complexity estimation |
| **Router** | `maistro.router` | Scoring formula + RouterEngine |
| **Agents** | `maistro.agents` | Base class, factory, strategies, roster |
| **Builders** | `maistro.builders` | Pipeline: spec → tests → code → review |
| **A2A** | `maistro.a2a` | Agent-to-agent delegation + lifecycle |
| **Skills** | `maistro.skills` | Marketplace, Forge, parser, canary |
| **Persistence** | `maistro.persistence` | PostgreSQL stores (learnings, outcomes, sessions, agents, audit, quota, prompts) + SQLite twins for homelab. `postgresql://` selects PG, `sqlite:` SQLite, `memory://` neither |
| **Protocols** | `maistro.protocols` | Abstract interfaces for DI |
| **Types** | `maistro.types` | Shared dataclasses |
| **Orchestrator** | `maistro.orchestrator` | Super Planner + Master Orchestrator |
| **Container** | `maistro.container` | DI wiring + `route_request()` |
| **Conduit** | `maistro.conduit` | Request pipeline: classify → route → agent.handle |
| **Auth** | `maistro.auth` | B2B service keys with scoped permissions |
| **Events** | `maistro.events` | Bus, handlers, recipes, triggers |
| **Quota** | `maistro.quota` | Token usage tracking per provider per billing cycle |
| **Sessions** | `maistro.sessions` | Conversation history with TTL pruning |
| **Intents** | `maistro.agents.intents` | task_type → agent_name routing table |
| **Graph** | `maistro.graph` | DAG execution: node types, executor, optimizer, phases (ADR-062) |
| **Ontology** | `maistro.ontology` | Semantic object layer and registry (ADR-036) |
| **Resilience** | `maistro.resilience` | Reliability taxonomy and circuit-breaking (ADR-038) |
| **Identity** | `maistro.identity` | Identity management |
| **Scheduling** | `maistro.scheduling` | Scheduling |
| **Prompts** | `maistro.prompts` | Prompt templates |
| **Capabilities** | `maistro.capabilities` | Slots, providers, registry, and discovery; SPEC-184/188 self-repair remains proposed |
| **Credentials** | `maistro.credentials` | Per-user encrypted credentials for PM integrations |
| **Projects** | `maistro.projects` | User workspaces: domains, meta-DAGs, PM Fleet, Canvas/Engineering |
| **Testing** | `maistro.testing` | Shared test utilities/fixtures |
| **CLI** | `maistro.cli` | `maistro` command — thin client of the hive-conductor API |

Root-level modules: `reactor.py` (1kHz reactor loop), `vault.py` (age-encrypted secrets), `privilege.py`, `state.py`.

### maistro-canvas (canvas ability + book-maker POC frontend)

```
packages/maistro-canvas/
├── src/maistro_canvas/      # Python library
│   ├── types.py             # Canvas types + 20 domain errors
│   ├── protocols.py         # CanvasStore, ImageGenClient, CompositorService
│   ├── auth.py              # Standalone API key auth
│   └── canvas/              # Canvas engine (from Stronghold spec 1189)
│       ├── tool.py          # In-process canvas tool (903 lines)
│       ├── executor.py      # Canvas action executor
│       ├── compositor.py    # PIL-based RGBA layer assembly
│       ├── store.py         # PostgreSQL canvas store
│       └── routes.py        # REST API routes
├── frontend/                # React + Express POC
│   ├── src/                 # React UI (14 components)
│   ├── server/              # Python backend
│   │   ├── mcp/             # Canvas pipeline, illustration, refinement
│   │   ├── lulu/            # Lulu print-on-demand integration
│   │   ├── models/          # SQLAlchemy models (11 tables)
│   │   └── templates/       # Story templates
│   └── SPEC.md
└── agents/davinci/          # Da Vinci agent definition
```

### maistro-turing (autonoetic self-model)

Implementation in progress: Mood, HEXACO personality, drives, proactive producers (blog, reflection, curiosity, emotion). Bridges to maistro-core for memory and security. `tests/` has suites (protocols, reactor, tiers, types) and `backend/tests` is a second FastAPI service's suite (its own auth lanes); both run in `ci.yml`'s pytest matrix alongside the src type-check.

---

## Development Commands

```bash
# Install for development (from repo root — uv.lock is the source of truth)
uv sync
# Or with pip:
pip install -e packages/maistro-core
pip install -e packages/maistro-server
pip install -e packages/maistro-turing
pip install -e packages/maistro-canvas
pip install -e packages/maistro-evolve

# Run core tests
PYTHONPATH=packages/maistro-core/src pytest packages/maistro-core/tests/ -q

# Run all package tests
PYTHONPATH=packages/maistro-core/src:packages/maistro-canvas/src:packages/maistro-turing/src \
  pytest packages/maistro-core/tests packages/maistro-server/tests \
  packages/maistro-canvas/tests packages/maistro-evolve/tests -q

# Formal property-based conformance tests (separate CI flow — formal-conformance.yml)
PYTHONPATH=packages/maistro-core/src pytest formal/ -q

# Lint — ci.yml runs `ruff check .` + `ruff format --check` + mypy across all packages/*/src
ruff check packages/
mypy packages/ --strict
# CI workflows: ci.yml (lint+type+core tests), quality.yml (full ruleset+coverage),
# security.yml, mutation.yml, registry.yml, cage-guard.yml, formal-conformance{,-nightly}.yml

# Verify all core imports
PYTHONPATH=packages/maistro-core/src python3 -c "
from maistro.container import Container, create_container
from maistro.conduit import Conduit
from maistro.types import AgentConfig, AgentError
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.security.warden.detector import Warden
from maistro.classifier.engine import ClassifierEngine
from maistro.router.selector import RouterEngine
from maistro.agents.intents import IntentRegistry
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.sessions.store import InMemorySessionStore
print('OK')
"

# Verify canvas imports
PYTHONPATH=packages/maistro-core/src:packages/maistro-canvas/src python3 -c "
from maistro_canvas import CanvasRecord, CanvasStore, ImageGenClient
from maistro_canvas.types import validate_canvas_dimensions, CanvasError
print('OK')
"
```

---

## Key Design Decisions

1. **Library-first, app is optional.** Core is a pure Python library. FastAPI app is a thin wrapper.
2. **Protocol-driven DI.** All business logic depends on protocols (abstract interfaces), never concrete implementations.
3. **Agents are data.** An agent is rows in a store, prompts in YAML. The runtime is shared.
4. **Scoring formula.** `quality^(qw*p) / (1 + normalized_cost)^cw` with scarcity-based cost (normalized against the realistic budget band) and task-type speed bonuses.
5. **Memory must forget.** Decay without reinforcement, weight floors for wisdom/regrets.
6. **All input is untrusted.** Warden scans at every trust boundary. Sentinel validates tool calls.
7. **Scope axes in core; hard tenancy in Stronghold (ADR-068).** maistro-core keeps the *soft* scope axes `global → org → team → user → agent → session` (a user may be in multiple teams/orgs). Only the *hard* `tenant` boundary — fully segmented, one tenant per user — is Stronghold-specific. (Supersedes the older "no org_id in core" shorthand, which conflated scope with tenancy.)
8. **The canvas ability is standalone.** `maistro-canvas` needs no Conductor or Stronghold; the book-maker POC frontend imports it and runs on a mini-PC with a P40 image-gen server.

---

## File Layout

```
maistro-engine/
├── packages/
│   ├── maistro-core/
│   │   ├── pyproject.toml
│   │   └── src/maistro/
│   │       ├── agents/          # base, factory, strategies, roster, intents
│   │       ├── a2a/             # delegate, lifecycle, guest_peers
│   │       ├── auth/            # B2B service keys
│   │       ├── builders/        # contracts, runtime, orchestrator, spec, verifier
│   │       ├── classifier/      # engine, keyword, llm_fallback, complexity
│   │       ├── config/          # settings, loader
│   │       ├── capabilities/    # slots, providers, registry; self-repair (SPEC-184/188)
│   │       ├── credentials/     # per-user encrypted PM-integration creds
│   │       ├── projects/        # per-user / team project workspaces
│   │       ├── testing/         # shared test utilities
│   │       ├── conduit.py       # Request pipeline
│   │       ├── container.py     # DI wiring
│   │       ├── cli.py           # `maistro` CLI (thin client of hive-conductor API)
│   │       ├── constants.py     # named constants
│   │       ├── privilege.py     # admin/user1 privilege separation (SPEC-012)
│   │       ├── vault.py         # age-encrypted secrets vault (SPEC-011)
│   │       ├── reactor.py       # 1kHz reactor loop (SPEC-013)
│   │       ├── state.py         # SQLite singleton writer (SPEC-010)
│   │       ├── events/          # bus, handlers, recipes
│   │       ├── integrations/    # HA, CoinSwarm, Turing bridges
│   │       ├── memory/          # learnings, episodic, scopes, outcomes
│   │       ├── observability/   # logging, metrics, tracing
│   │       ├── orchestrator/    # Super Planner, Master Orchestrator
│   │       ├── persistence/     # PostgreSQL stores + SQLite twins (same protocols)
│   │       ├── protocols/       # abstract interfaces
│   │       ├── quota/           # billing, tracker
│   │       ├── router/          # scorer, selector, filter, scarcity, speed
│   │       ├── security/        # warden, sentinel, gate, auth
│   │       ├── sessions/        # conversation history
│   │       ├── skills/          # marketplace, forge, parser, canary, connectors
│   │       ├── tasks/           # queue, runner, models
│   │       ├── tools/           # sandbox, git, browser
│   │       ├── types/           # AgentConfig, AgentError, shared dataclasses
│   │       ├── graph/           # DAG execution: node, executor, optimizer, phases (ADR-062)
│   │       ├── ontology/        # Semantic object layer, registry (ADR-036)
│   │       ├── resilience/      # Reliability taxonomy, circuit-breaking (ADR-038)
│   │       ├── identity/        # Identity management
│   │       ├── scheduling/      # Scheduling
│   │       └── prompts/         # Prompt templates
│   │
│   ├── maistro-canvas/
│   │   ├── pyproject.toml       # depends: maistro-core
│   │   ├── frontend/            # React + Express book builder POC
│   │   ├── agents/davinci/      # Da Vinci agent definition
│   │   └── src/maistro_canvas/
│   │       ├── types.py         # Canvas types + domain errors
│   │       ├── protocols.py     # CanvasStore, ImageGenClient, CompositorService
│   │       ├── auth.py          # Standalone auth
│   │       └── canvas/          # executor, compositor, store, routes, tool
│   │
│   ├── maistro-server/
│   │   ├── pyproject.toml       # depends: maistro-core
│   │   └── src/maistro_server/
│   │       ├── api/             # HTTP routes
│   │       └── main.py          # FastAPI app
│   │
│   ├── maistro-turing/
│   │   ├── pyproject.toml       # depends: maistro-core
│   │   └── src/maistro_turing/
│   │       ├── bridge.py        # Adapters to maistro-core
│   │       ├── self_model.py    # Autonoetic identity
│   │       ├── runtime.py       # Actor, chat, config
│   │       └── producers.py     # Blog, reflection, curiosity, emotion
│   │
│   ├── maistro-evolve/
│   │   ├── pyproject.toml
│   │   └── src/maistro_evolve/  # Elo tournament optimizer (crossover, mutate, fitness, harness)
│   │
│   ├── maistro-registry/        # ADR/spec registry CLI (parser, validator, linker, dag, schema)
│   │
│   └── hive-conductor/          # Agent Conductor app (no pyproject.toml — requirements.txt)
│       ├── backend/             # FastAPI app
│       │   ├── main.py          # Entrypoint + route registration
│       │   ├── routes/          # agents, audit, chat, cli, containers, dags, mcp, memory…
│       │   ├── models/          # SQLAlchemy models
│       │   ├── middleware/      # Auth middleware
│       │   ├── services/        # Business logic
│       │   ├── adapters/        # Langfuse telemetry, noop
│       │   └── requirements.txt
│       └── frontend/            # React SPA
│
├── formal/                      # Property-based conformance tests (Hypothesis); separate CI flow
├── docs/adr/                    # Architecture Decision Records
├── docs/specs/                  # Engine design specifications
└── pyproject.toml               # uv workspace root (uv.lock is source of truth)
```
