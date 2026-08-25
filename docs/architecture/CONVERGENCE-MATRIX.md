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
| Run / NodeRun / Attempt lifecycle | `maistro.runs`, `maistro.runtime` | Run, NodeRun, Attempt, ExecutionRuntime | itself (canonical) | `runs.sqlite_store`, `runs.store` | caller-supplied `actor_principal_id` only |
| Graph execution | `maistro.graph` | Graph, Node, GraphExecutionState | `graph.durable_runs` over `maistro.runs` | `graph.durable_runs.stores` (in-memory + execution store) | — |
| Request front door and DI | `maistro.conduit`, `maistro.container` | Request admission | none — Conduit decides and delegates, holds no state | — | container-wired Warden/Sentinel |
| Task queue and runner | `maistro.tasks` | Admission receipt | `tasks.queue` + `tasks.status` (second universal lifecycle) | `TaskRecord` upsert, best-effort (ADR-018) | `security.task_policy` |
| A2A delegation | `maistro.a2a` | Child Run | `a2a.lifecycle` worker pool (third universal lifecycle) | — | `a2a.guest_peers` trust tiers |
| Recurrence / schedules | `maistro.scheduling` | Trigger definition → Run | core `ScheduleRunAdmitter`/Run owns admitted execution; Hive still has a separate live fire/cursor loop | `scheduling.store` (SQLite + in-memory) plus Hive schedule projection | schedule's `actor_principal_id` |
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
| Shared contracts and config | `maistro`, `maistro.types`, `maistro.protocols`, `maistro.constants`, `maistro.config`, `maistro.http` | Types and protocols | n/a | — | — |
| Test scaffolding | `maistro.testing` | Test doubles | n/a | — | — |
| maistro-server HTTP app | `maistro_server` | Product entry point | `maistro.tasks.queue` receipt plus canonical Run spine | inherited | `maistro.auth` + rate limiter |
| Agent Conductor HTTP surface | `main`, `routes`, `middleware`, `protocols`, `adapters`, `models`, `stores`, `config`, `logging_setup`, `settings_defaults` | Product entry point | mixed: `stores` in-memory dicts, `models` SQLAlchemy | `models` + `services.pg_store` | `middleware` auth + `middleware.privilege` |
| Agent Conductor services | `services` | Product services | `services.dag_run_store` — parallel run identity, event-derived, authoritative for current UI | `services.pg_store` | per-route |
| Canvas ability | `maistro_canvas` | Graph of canvas Nodes | `canvas.executor` pipeline + `canvas.runner` claim/lease/reap state machine | `canvas.store` (PostgreSQL) | `maistro_canvas.auth` |
| Open Design integration | `maistro_design` | Renderer Providers | `design.engine` | `design.stores` | `design.trust` |
| Evolve tournament optimizer | `maistro_evolve` | Graph of evaluation Nodes | `evolve.cycle` orchestrates; no universal work-state machine of its own | `evolve.serialize` | — |
| RSI autorun | `maistro_rsi` | Run per improvement cycle | `rsi.coordinator` orchestrates; result records, no universal work-state machine | `rsi.spec_tracker`, quarantine ledger | `rsi.quarantine` gate |
| Turing self-model | `maistro_turing`, `maistro-turing-backend` | Optional cognitive Providers | `turing.runtime` actor + chat session; no universal work-state machine | backend DB via `TuringMemoryBridge` | backend `middleware.auth` |
| ADR/spec registry CLI | `maistro_registry` | Governance tooling | n/a | filesystem | — |
| Bootstrap installer | `maistro_bootstrap` | Installer | n/a | filesystem | — |

## Disposition and evidence

`Unreachable` is `unreachable/total` production modules and is recomputed by the checker. `Dependencies` names convergence work that must land before the row reaches its target.

<!-- matrix:disposition -->
| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |
|---|---|---|---|---|---|---|
| Run / NodeRun / Attempt lifecycle | reached via `maistro.graph.durable_runs` from `services.dag_agents` | `0/19` | KEEP — canonical | ADR-081226-a66b, ADR-081426-1f7c, ADR-081626-f383 | property/conformance tests in `formal/` plus core lifecycle suites | #42, #43, #45 |
| Graph execution | `services.dag_agents.run_registered_dag`; `maistro.container` node resolver | `3/60` | MIGRATE — traversal state must separate from lifecycle state | ADR-062, ADR-081226-69ee | durable graph execution whose Run/NodeRun/Attempt records reproduce traversal | #44, #34 |
| Request front door and DI | maistro-server `/v1/chat/completions` → `Container.route_request`; Hive/Conductor still has separate chat/DAG paths | `0/2` | MIGRATE — maistro-server is converged through Conduit; Hive/Conductor is not | ADR-019, ADR-096, ADR-082426-2192 | #222 proves the maistro-server product door; #53/#66 own the remaining Hive product path | #53, #66 |
| Task queue and runner | `maistro_server.main`, `adapters.task_backend` | `2/12` | MIGRATE — receipt over a canonical Run, with remaining production-scope/recovery work | ADR-018, ADR-056, ADR-097 | task submission returns `run_id`; NodeRun/Attempt and recovery children track remaining gaps | #43, #232, #234 |
| A2A delegation | exported API; Hive DAG resolver path | `0/5` | MIGRATE — delegation must create child Runs and product wiring must supply dependencies | ADR-058 | local + remote child Run with durable parent correlation | #47, #147 |
| Recurrence / schedules | `services.scheduler` background loop | `1/6` | MIGRATE — core occurrence/Run semantics are canonical, live Hive firing still bypasses them | ADR-082126-f69c, ADR-082426-82c7 | #229 proves occurrence uniqueness in core; #231 requires E2E through `services.scheduler.py` | #46, #231, #62 |
| Planning and wave orchestration | `maistro.orchestrator` exported API | `3/10` | MIGRATE — wave fan-out/fan-in belongs to Graph nodes | ADR-071, ADR-052 | wave plan executes as Graph with per-branch NodeRuns | #44, #34 |
| Builders pipeline | none | `15/15` | MIGRATE — wholly unreachable and owns duplicate executor | ADR-090, ADR-099 | Builders stages appear as NodeRuns; duplicate executor retired | #49, #35 |
| Workspace / Project scope | `routes.projects`, `routes.workspaces` (partly unreachable) | `4/12` | CONNECT — correct model, incomplete product wiring | ADR-081226-9944, ADR-081426-b1d3 | every production Run carries correct Workspace/Project and scope survives restart | #37, #38, #234 |
| Agents | `maistro.container` factory; `services.agent_materialization` | `26/60` | MIGRATE — agents become Node implementations behind Providers | ADR-004, ADR-035 | agent invocation creates Invocation; per-agent effect/event escapes retire | #55, #56, #34 |
| Capability / Provider / Binding / Invocation | `services.capabilities_wiring`, `routes.capabilities` | `2/31` | KEEP — canonical effect path, incompletely adopted | ADR-081226-6b46 | every shipped model/tool effect has an Invocation row | #55, #56, #57 |
| Model providers | `maistro.container` provider wiring | `0/7` | KEEP | ADR-079, ADR-070426-ac56 | provider parity tests; no new direct caller escapes | #56 |
| Router and classifier | `maistro.container.route_request` | `1/13` | KEEP — pure decision layer | ADR-007, ADR-089 | scoring tests; router chooses Provider, never executes | — |
| Tool execution | `services.tool_executor`, `maistro.container` | `9/26` | MIGRATE — tool calls must be governed Invocations | ADR-050, ADR-051, SPEC-252 | tool call produces Invocation + authorization + expected-effect evidence | #57, #59 |
| Sandbox isolation | none in shipped repo processes | `6/6` | CONNECT — ExecutionRuntime story needs it | ADR-093, ADR-054 | Attempt executes inside sandbox with enforced budgets | #42, #34 |
| Skills, code registry, repertoire | `routes.skills`, `services.mcp_client` | `12/22` | MIGRATE — one governed supply-chain path | ADR-083, ADR-069, ADR-070 | signed-code verification on real register/load path | #59, #34 |
| Credentials | `routes.credentials`, `services.credential_store_v2` | `4/7` | MIGRATE — rotation belongs at Provider selection | ADR-063 | real Invocation outcome triggers scoped rotation | #58 |
| Quota and billing | `routes.quotas`, `maistro.container` | `8/13` | MIGRATE — cost attaches to Invocation | ADR-085 | token/cost metadata on Invocation | #56, #63 |
| External integrations | exported API | `5/5` | CONNECT — bridges with no shipped caller | ADR-029 | one integration reached from product route | #34 |
| Delivery gateway | none | `5/5` | CONNECT | ADR-047 | delivery effect recorded as Invocation | #34, #57 |
| Warden / Sentinel / Gate | `maistro.container`, `maistro_server` middleware | `10/55` | MIGRATE — core/server enforcement exists; Hive product-path coverage still incomplete | ADR-073, ADR-072, ADR-072726-0d6b | durable strikes on PostgreSQL are proven (#217); real Hive chat must prove Warden/Sentinel traversal | #66, #67, #74 |
| Authentication and identity | `routes.auth`, `middleware`, `maistro_server` auth | `0/11` | KEEP | ADR-059, ADR-084, ADR-077 | Argon2id registration + bcrypt upgrade | #32 |
| Authorization, privilege, governance | `middleware.privilege` (unreachable), `maistro.policy` | `3/9` | CONNECT — approver matrix partly unbuilt | ADR-028, ADR-068, ADR-081226-6e34 | beyond-authority action resolves approver scope from policy | #60 |
| Secrets vault | `maistro.cli`, installer | `0/1` | KEEP | SPEC-011 | round-trip encryption tests | — |
| Memory | `routes.memory`, `maistro.container` | `9/24` | KEEP — domain state; provenance and archive policy still converge | ADR-034, ADR-011, ADR-091, ADR-057, ADR-082226-5104, ADR-082226-d3dd | scoped pgvector recall is live; archive conformance passes; producing Run provenance/policy remain | #64, #133 |
| Sessions | `routes.chat`, `maistro_server.api.ws` | `1/3` | KEEP — correlates to Runs, does not own them | ADR-048, ADR-070426-e8a3 | session id correlated on Run without owning lifecycle | #64 |
| Archive tier | `maistro.container` when `archive_url` is set | `0/6` | KEEP — storage tier, not lifecycle | ADR-082226-f436, ADR-082226-5104 | filesystem + S3 conformance; archive-eligibility policy still open | #133 |
| Relational persistence | `maistro.container` (both backends), Alembic | `0/14` | KEEP — PostgreSQL canonical stores and SQLite homelab adapters are wired | ADR-082226-5104, ADR-087, ADR-012 | container selects durable prompt/audit stores with backend conformance; zero relational modules unreachable | — |
| Local state writer | `maistro.reactor`, CLI | `0/1` | KEEP | SPEC-010 | single-writer concurrency tests | — |
| Ontology | none | `4/4` | CONNECT — accepted design, no consumer | ADR-036 | subsystem resolves semantic object through registry | #34 |
| Portability / backup | none | `4/4` | CONNECT | ADR-081, ADR-101 | backup/restore preserves canonical correlated records | #62, #34 |
| Events and checkpoints | `maistro.container`, `events.durable_log` | `2/12` | KEEP — canonical envelope, incompletely adopted | ADR-086, ADR-081226-7248 | migrated event families share envelope + Workspace sequence | #61, #62 |
| Observability | `maistro_server` middleware, `adapters` Langfuse | `0/8` | KEEP | ADR-037, ADR-082, ADR-055 | one trace spans request → Run → NodeRun → Attempt → Invocation | #63 |
| Resilience | `maistro.container`, `resilience.slo` | `3/9` | KEEP | ADR-038, ADR-066 | circuit/SLO primitives wired to real producers | #63 |
| Collaboration | none | `3/3` | CONNECT | ADR-070426-3a1f | collaborative edit correlated to Run | #34 |
| Reactor loop | `maistro.reactor` (installer-launched) | `0/1` | KEEP | SPEC-013, ADR-086 | loop timing tests | — |
| Prompts and personas | `maistro.container`, `routes.agents` | `1/13` | KEEP | ADR-060, ADR-081226-e626 | persona seed/eval protocol tests | — |
| Codebase analysis | `maistro.tools` call sites | `0/5` | KEEP | ADR-065 | tool-level tests | — |
| Core CLI | `maistro.cli` console script | `5/14` | KEEP — thin client, no local lifecycle | ADR-096 | CLI commands hit Conductor API only | — |
| Shared contracts and config | imported by every package | `1/46` | LIBRARY | ADR-019, ADR-081226-034b | dependency-direction + compatibility-owner fitness checks | #36 |
| Test scaffolding | test suites only | `4/4` | LIBRARY — unreachable by construction | ADR-065, ADR-032 | used by checked test suites | — |
| maistro-server HTTP app | `maistro_server.main` | `0/19` | MIGRATE — task queue is receipt; chat front door now uses Container/Conduit | ADR-076, ADR-096, ADR-082426-2192 | `/v1/tasks` and `/v1/chat/completions` both yield canonical Run identity | #43, #234 |
| Agent Conductor HTTP surface | `main` (uvicorn) | `4/67` | MIGRATE — product surface must read canonical stores | ADR-096, ADR-094 | Run views rendered from canonical stores and surviving restart | #65, #53 |
| Agent Conductor services | route registration + background loops | `15/60` | MIGRATE — `dag_run_store`, scheduler and graph/product seams still duplicate canonical responsibilities | ADR-096 | DAG/scheduler/chat paths use canonical Runs and projections only | #53, #35, #231 |
| Canvas ability | `maistro_canvas.canvas.routes`, `routes.canvas` | `8/17` | MIGRATE — pipeline stages become NodeRuns | ADR-045, ADR-040, ADR-067 | canvas stages visible as NodeRuns with retries as Attempts | #52 |
| Open Design integration | `routes.design`, `services.design_service` | `1/18` | MIGRATE — renderers become Providers | ADR-061, ADR-100 | render effect recorded as Invocation | #52, #55 |
| Evolve tournament optimizer | `routes.evolution`, `services.evolution` | `7/61` | MIGRATE — cycle is Run, battle is NodeRun | ADR-088, ADR-070126-6386, SPEC-070126-9d37 | tournament history reproducible from canonical Runs | #51 |
| RSI autorun | `maistro_rsi.cli`, `routes.rsi` | `4/34` | MIGRATE — cycles become Runs over authorized work source | ADR-088 | every RSI cycle has Run provenance; backlog through adapter | #50 |
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
