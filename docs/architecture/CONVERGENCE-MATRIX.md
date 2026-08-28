# Architecture Convergence Matrix

**Status:** living document — structurally checked by `scripts/check-convergence-matrix.py` on every PR; ownership/prose truth last re-audited from current `develop` during the 2026-08-24 M0 closeout.
**Scope:** every production module in this repository (`packages/*/src` plus the flat `packages/*/backend` applications), partitioned into subsystems.
**Answers:** [#28](https://github.com/Agent-StrongHold/Project-mAIstro/issues/28) (M0-A1).

The convergence program has one execution identity — `Workspace/Project → Graph → Run → NodeRun → Attempt → ExecutionRuntime` — and one effect path — `Capability → Provider → Binding → Invocation`. Every competing owner below is either legitimate domain state, a compatibility/projection surface, or explicit convergence debt.

## What the checker enforces

`scripts/check-convergence-matrix.py` fails CI when the two tables disagree, module prefixes stop partitioning every production module, unreachable counts disagree with the reachability ratchet, a disposition leaves the fixed vocabulary, or a cited ADR/SPEC does not exist.

It deliberately **does not prove the prose ownership claims**. Reachability proves that code can be reached, not that an advertised control is active. M0 closes with the prose re-audited against current `develop`; future product-path changes that alter these claims must update this matrix in the same PR. Acceptance evidence names the fact that settles each row.

## Disposition vocabulary

| Verdict | Meaning |
|---|---|
| **KEEP** | Canonical owner, or domain state that is legitimately its own. No lifecycle/effect migration planned. |
| **MIGRATE** | Owns lifecycle/effect state or a product path that still bypasses the canonical owner. |
| **RETIRE** | Superseded. Delete after parity is demonstrated; M1 #35 owns that burn-down. |
| **CONNECT** | Correct design, no complete production entry point yet. Needs wiring, not redesign. |
| **LIBRARY** | Published surface or test scaffolding. Unreachable by construction and honestly so. |

## Ownership

`Lifecycle owner` is the authoritative “what state is this work in” record today. `Persistence owner` is what survives restart. `Authorization owner` is what decides whether the work is allowed.

<!-- matrix:ownership -->
| Subsystem | Modules | Canonical concept | Lifecycle owner | Persistence owner | Authorization owner |
|---|---|---|---|---|---|
| Run / NodeRun / Attempt lifecycle | `maistro.runs`, `maistro.runtime` | Run, NodeRun, Attempt, ExecutionRuntime | itself (canonical) | `runs.pg_store` (canonical, #132), `runs.sqlite_store`, `runs.store` | caller-supplied `actor_principal_id` only |
| Graph execution | `maistro.graph` | Graph, Node, GraphExecutionState | `graph.durable_runs` over `maistro.runs` | `graph.durable_runs.stores` (in-memory + execution store) | — |
| Request front door and DI | `maistro.conduit`, `maistro.container` | Request admission | none — Conduit decides and delegates, holds no state | — | container-wired Warden/Sentinel |
| Task queue and runner | `maistro.tasks` | Admission receipt | `tasks.queue` + `tasks.status` (second universal lifecycle) | `TaskRecord` upsert, best-effort (ADR-018) | `security.task_policy` |
| A2A delegation | `maistro.a2a` | Child Run | `a2a.lifecycle` worker pool (third universal lifecycle) | — | `a2a.guest_peers` trust tiers |
| Recurrence / schedules | `maistro.scheduling` | Trigger definition → Run | canonical: `evaluate()` decides, the Run owns execution | `scheduling.store` + `scheduling.pg_store` (PostgreSQL, SQLite, in-memory) | schedule's `actor_principal_id` |
| Repo tooling | `scripts` | CI gate / ratchet ledger | the workflow step that runs it | `quality/*.json` ledgers | — |
| Planning and wave orchestration | `maistro.orchestrator` | Graph synthesis | wave state in `orchestrator.waves` | — | — |
| Builders pipeline | `maistro.builders` | Graph of spec→tests→code→review Nodes | `builders.runtime` + `builders.graph_executor` (fourth universal lifecycle) | `builders.logger` | — |
| Workspace / Project scope | `maistro.workspaces`, `maistro.projects` | Workspace, Project — the scope roots | n/a (scope, not execution) | `projects.store`, `projects.scope_store`, `workspaces.store` | `projects.authorization` |
| Agents | `maistro.agents` | Node implementation / Provider | per-agent ad-hoc; `agents.pm_runner` emits its own events | `persistence.pg_agents` | `agents.intents` routing table only |
| Capability / Provider / Binding / Invocation | `maistro.capabilities` | the canonical effect path | `capabilities.invocation` | `capabilities.invocation_store`, `approval_store` | `capabilities.governed_invocation` |
| Model providers | `maistro.providers` | Provider implementations | n/a | — | — |
| Router and classifier | `maistro.router`, `maistro.classifier` | Provider selection policy | n/a (pure decision) | — | — |
| Tool execution | `maistro.tools` | Invocation | direct call sites | — | `tools.approval`, `tools.reversibility_registry` |
| Sandbox isolation | `maistro.sandbox` | ExecutionRuntime implementation | its own session records | — | — |
| Skills, code registry, repertoire | `maistro.skills`, `maistro.code_registry`, `maistro.repertoire` | Capability supply chain | per-package registries | `skills.marketplace` stores | `code_registry` signing + trust tiers |
| Credentials | `maistro.credentials` | Binding material | `credentials.pool` rotation state | encrypted per-user store | — |
| Quota and billing | `maistro.quota` | Invocation cost accounting | `quota.tracker` | `persistence.pg_quota`, `quota.sqlite_usage_log` | — |
| External integrations | `maistro.integrations` | Provider implementations | n/a | — | — |
| Delivery gateway | `maistro.delivery` | Effect channel | its own send records | — | — |
| Warden / Sentinel / Gate | `maistro.security` | trust boundary + policy decision point | `security.strikes` protocol-backed lockout state | audit durable via `persistence.pg_audit`; PostgreSQL deployments use `PgStrikeTracker`, non-PostgreSQL deployments use the in-memory tracker (#134/#217) | itself (canonical) |
| Authentication and identity | `maistro.auth`, `maistro.identity` | Principal | n/a | service-key store | itself (canonical) |
| Authorization, privilege, governance | `maistro.privilege`, `maistro.policy`, `maistro.governance` | Authorization decision | n/a | — | itself (canonical, ADR-068 partly unbuilt) |
| Secrets vault | `maistro.vault` | Secret material | n/a | age-encrypted file | OS file permissions |
| Memory | `maistro.memory` | Learning, Episode, Outcome | n/a (domain state) | `persistence.pg_learnings`/`pg_outcomes` on a `postgresql://` URL, `sqlite_*` on SQLite, in-memory otherwise; pgvector embeddings live on learning rows when configured | `memory.scopes`, `memory.exposure` |
| Sessions | `maistro.sessions` | Conversation history | `sessions.store` TTL pruning | `persistence.pg_sessions` on PostgreSQL, `sqlite_sessions` on SQLite, in-memory otherwise | session trust floor |
| Archive tier | `maistro.archive` | Cold storage for records that are still authoritative | n/a (placement, not lifecycle) | object storage or a local directory; tombstone stays in PostgreSQL where required | inherits record scope |
| Relational persistence | `maistro.persistence` | Storage adapters | n/a | itself — `pg_*` is wired for PostgreSQL; SQLite remains for homelab/local use | — |
| Local state writer | `maistro.state` | Single-writer SQLite | n/a | itself | — |
| Ontology | `maistro.ontology` | Semantic object layer | n/a | `ontology.registry` (in-memory) | — |
| Portability / backup | `maistro.portability` | Export/import of domain state | n/a | file exports | — |
| Events and checkpoints | `maistro.events` | Event envelope, checkpoint, outbox | n/a | `events.pg_stores` with a pool, else durable SQLite or in-memory; `events.outbox` | — |
| Observability | `maistro.observability` | Trace, metric, log | n/a | exporter-dependent | — |
| Resilience | `maistro.resilience` | Retry, circuit, SLO | circuit state per dependency | in-memory | — |
| Collaboration | `maistro.collaboration` | Multi-actor editing | its own session records | — | — |
| Reactor loop | `maistro.reactor` | Trigger evaluation loop | n/a | — | — |
| Prompts and personas | `maistro.prompts`, `maistro.personas` | Node/agent configuration | n/a | `persistence.pg_prompts` still has no production importer | — |
| Codebase analysis | `maistro.codebase` | Tool implementation | n/a | — | — |
| Core CLI | `maistro.cli` | Client of the Conductor API | n/a (remote) | — | server-side |
| Shared contracts and config | imported by every package | `1/46` | LIBRARY | ADR-019, ADR-081226-034b | dependency-direction + compatibility-owner fitness checks | #36 |
| Test scaffolding | test suites only | `4/4` | LIBRARY — unreachable by construction | ADR-065, ADR-032 | used by checked test suites | — |
| maistro-server HTTP app | `maistro_server.main` | `0/21` | MIGRATE — task queue is receipt; chat front door now uses Container/Conduit | ADR-076, ADR-096, ADR-082426-2192 | `/v1/tasks` and `/v1/chat/completions` both yield canonical Run identity | #43, #234 |
| Agent Conductor HTTP surface | `main` (uvicorn) | `4/67` | MIGRATE — product surface must read canonical stores | ADR-096, ADR-094 | Run views rendered from canonical stores and surviving restart | #65, #53 |
| Agent Conductor services | route registration + background loops | `15/64` | MIGRATE — `dag_run_store`, scheduler and graph/product seams still duplicate canonical responsibilities | ADR-096 | DAG/scheduler/chat paths use canonical Runs and projections only | #53, #35, #231 |
| Canvas ability | `maistro_canvas.canvas.routes`, `routes.canvas` | `8/17` | MIGRATE — pipeline stages become NodeRuns | ADR-045, ADR-040, ADR-067 | canvas stages visible as NodeRuns with retries as Attempts | #52 |
| Open Design integration | `routes.design`, `services.design_service` | `1/18` | MIGRATE — renderers become Providers | ADR-061, ADR-100 | render effect recorded as Invocation | #52, #55 |
| Evolve tournament optimizer | `routes.evolution`, `services.evolution` | `7/61` | MIGRATE — cycle is Run, battle is NodeRun | ADR-088, ADR-070126-6386, SPEC-070126-9d37 | tournament history reproducible from canonical Runs | #51 |
| RSI autorun | `maistro_rsi.cli`, `routes.rsi` | `4/35` | MIGRATE — cycles become Runs over authorized work source | ADR-088 | every RSI cycle has Run provenance; backlog through adapter | #50 |
| Turing self-model | `maistro_turing.runtime`, turing backend `main` | `0/23` | MIGRATE — reachable paths only; cognition remains gated | ADR-081426-fb9f, ADR-070426-9f47 | reachable Turing execution carries Run/Invocation correlation | #54 |
| ADR/spec registry CLI | `maistro_registry.cli` | `0/8` | KEEP — lifecycle relationships are now prospectively validated | ADR-031, ADR-062026-9b30, ADR-097 | strict registry validation + #239 lifecycle-evidence cases | #30, #239 |
| Bootstrap installer | `maistro_bootstrap` console script | `0/20` | KEEP | ADR-020, ADR-033 | installer smoke tests | — |

## Current convergence boundary after M0

- Every unreachable production module is classified. Executing CONNECT/RETIRE dispositions is M1 work under #34/#35; M0 does not pretend that the migration is complete.
- maistro-server chat is now a real Container/Conduit product path (#222), while Hive/Conductor remains the product migration target (#53/#66).
- PostgreSQL strike state is wired through the Gate-compatible tracker (#217); security convergence still has product-path work rather than a persistence fiction.
- Core scheduling owns occurrence identity and exact-one Run claims (#229), while the **live Hive scheduler** has not adopted that seam; #231 is the explicit remaining product migration.
- Relational persistence is fully reached: PostgreSQL is the canonical durable backend, while SQLite remains the explicit single-instance/homelab backend; prompt and audit persistence now follow the selected backend rather than silently falling back to memory.
- The matrix checker proves structure, reachability counts and reference integrity. It cannot prove prose. That limitation is explicit rather than hidden; #31's acceptance-state machinery governs machine-verifiable completion claims, and material ownership changes must update this human-reviewed planning surface.

## Related

- `quality/reachability-baseline.json` — ratcheted unreachable set.
- `quality/reachability-dispositions.json` — CONNECT/LIBRARY/RETIRE classification per unreachable module (#33).
- `quality/ac-state.json` — measured acceptance evidence and design coverage (#31/#166).
- `quality/execution-lifecycles.json` — classified work-state enums (#36).
- `docs/quality-gates.md` — enforcement boundaries and known limitations.
