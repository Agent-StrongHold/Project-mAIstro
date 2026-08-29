# Architecture Convergence Matrix

**Status:** living document — structurally checked by `scripts/check-convergence-matrix.py` on every PR; ownership/prose truth last re-audited from current `develop` during the 2026-08-24 M0 closeout.
**Scope:** every production module in this repository (`packages/*/src` plus the flat `packages/*/backend` applications), partitioned into subsystems.
**Answers:** [#28](https://github.com/Agent-StrongHold/Project-mAIstro/issues/28) (M0-A1).

The convergence program has one execution identity — `Workspace/Project → Graph → Run → NodeRun → Attempt → ExecutionRuntime` — and one effect path — `Capability → Provider → Binding → Invocation`. Every competing owner below is either legitimate domain state, a compatibility/projection surface, or explicit convergence debt.

## What the checker enforces

`scripts/check-convergence-matrix.py` fails CI when the two tables disagree, module prefixes stop partitioning every production module, a row's unreachable share disagrees with the reachability ratchet, a disposition leaves the fixed vocabulary, a cited ADR/SPEC does not exist, or an **ownership claim names a module that no product path reaches** (#378) — see [How to read an ownership cell](#how-to-read-an-ownership-cell-378) for the grammar those columns now follow. Fifteen such claims were in the table when that check was turned on, all of them now annotated with what is actually true.

It still **does not prove a prose ownership claim**. Reachability proves that code can be reached, not that an advertised control is active, and a cell that names no module at all — “OS file permissions”, “per-route” — says something no import graph can settle. That residue is counted rather than waved at: the ownership census is checked, so the number of unverifiable cells cannot grow unnoticed. Future product-path changes that alter these claims must update this matrix in the same PR; acceptance evidence names the fact that settles each row.

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

### How to read an ownership cell (#378)

The three owner columns have a grammar, and the checker holds them to it. A code span shaped like a module path — `` `runs.pg_store` `` — is a **claim**: it says that module owns this today. Cells abbreviate (`design.engine` for `maistro_design.engine`), so a claim is resolved against the row's own module prefixes first and must land on exactly one production module; a name that resolves to none, or to several, fails.

A bare claim asserts a **current, reached** owner. To say anything else, annotate it in the parenthesis that follows:

| Annotation | Means | Checked |
|---|---|---|
| *(none)* | Current owner, reached by some product path. | The module is not in the unreachable set. |
| `(canonical)` | Current owner, and the canonical one for this concept. | As above. |
| `(unreachable)` | Current owner in design, but **no product path reaches it**. | The module really is unreachable — a stale annotation on a wired module fails too. |
| `(planned)` | A future owner, not a claim about today. | The row may not be `KEEP`; a subsystem still waiting for its owner is `CONNECT` or `MIGRATE`. |
| `(delegated)` | This row reads another subsystem's owner rather than owning it. | Exempt from the single-lifecycle-owner rule below. |

Three further rules follow from the columns' meanings. A `KEEP` column whose every owner is unreachable or planned owns nothing today, so it is not `KEEP`. A module may be the current, undelegated **lifecycle** owner of at most one subsystem — two rows claiming one work-state record is the contradiction the convergence program exists to remove. And a cell that opens with a declared absence (`—`, `n/a`, `none`, `itself`) may not also name a module.

**What is not checked.** A cell may instead describe a non-module owner in prose — “age-encrypted file”, “OS file permissions”, “per-route”. Those are honest and unverifiable, and pretending otherwise would be the same defect this section fixes. The census below is checked, so the size of that gap cannot drift: of the 156 owner cells, 53 name a module, 73 declare there is no module owner, and 30 are prose the checker cannot reach.

<!-- matrix:ownership-census claims=53 declared=73 prose=30 -->
<!-- matrix:ownership -->
| Subsystem | Modules | Canonical concept | Lifecycle owner | Persistence owner | Authorization owner |
|---|---|---|---|---|---|
| Run / NodeRun / Attempt lifecycle | `maistro.runs`, `maistro.runtime` | Run, NodeRun, Attempt, ExecutionRuntime | itself (canonical) | `runs.pg_store` (canonical, #132), `runs.sqlite_store`, `runs.store` | caller-supplied `actor_principal_id` only |
| Graph execution | `maistro.graph` | Graph, Node, GraphExecutionState | `graph.durable_runs.canonical_store` over `maistro.runs` + `graph.durable_runs.continuation` | `graph.durable_runs.stores` (document-shaped; kept for pre-convergence records) | — |
| Request front door and DI | `maistro.conduit`, `maistro.container` | Request admission | none — Conduit decides and delegates, holds no state | — | container-wired Warden/Sentinel |
| Task queue and runner | `maistro.tasks` | Admission receipt | `tasks.queue` + `tasks.status` (second universal lifecycle) | `TaskRecord` upsert, best-effort (ADR-018) | `security.task_policy` (unreachable) |
| A2A delegation | `maistro.a2a` | Child Run | `a2a.lifecycle` worker pool (third universal lifecycle) | — | `a2a.guest_peers` trust tiers |
| Recurrence / schedules | `maistro.scheduling` | Trigger definition → Run | canonical: `evaluate()` decides, the Run owns execution | `scheduling.store` + `scheduling.pg_store` (PostgreSQL, SQLite, in-memory) | schedule's `actor_principal_id` |
| Repo tooling | `scripts` | CI gate / ratchet ledger | the workflow step that runs it | `quality/*.json` ledgers | — |
| Planning and wave orchestration | `maistro.orchestrator` | Graph synthesis | wave state in `orchestrator.waves` | — | — |
| Builders pipeline | `maistro.builders` | Graph of spec→tests→code→review Nodes | `builders.runtime` (unreachable) + `builders.graph_executor` (unreachable; fourth universal lifecycle) | `builders.logger` (unreachable) | — |
| Workspace / Project scope | `maistro.workspaces`, `maistro.projects` | Workspace, Project — the scope roots | n/a (scope, not execution) | `projects.store`, `projects.scope_store`, `workspaces.store` | `projects.authorization` |
| Agents | `maistro.agents` | Node implementation / Provider | per-agent ad-hoc; `agents.pm_runner` emits its own events | `persistence.pg_agents` | `agents.intents` routing table only |
| Capability / Provider / Binding / Invocation | `maistro.capabilities` | the canonical effect path | `capabilities.invocation` | `capabilities.invocation_store`, `approval_store` | `capabilities.governed_invocation` |
| Model providers | `maistro.providers` | Provider implementations | n/a | — | — |
| Router and classifier | `maistro.router`, `maistro.classifier` | Provider selection policy | n/a (pure decision) | — | — |
| Tool execution | `maistro.tools` | Invocation | direct call sites | — | `tools.approval` (unreachable), `tools.reversibility_registry` (unreachable) |
| Sandbox isolation | `maistro.sandbox` | ExecutionRuntime implementation | its own session records | — | — |
| Skills, code registry, repertoire | `maistro.skills`, `maistro.code_registry`, `maistro.repertoire` | Capability supply chain | per-package registries | `skills.marketplace` stores | `code_registry` signing + trust tiers |
| Credentials | `maistro.credentials` | Binding material | `credentials.pool` (unreachable) rotation state | encrypted per-user store | — |
| Quota and billing | `maistro.quota` | Invocation cost accounting | `quota.tracker` | `persistence.pg_quota`, `quota.sqlite_usage_log` (unreachable) | — |
| External integrations | `maistro.integrations` | Provider implementations | n/a | — | — |
| Delivery gateway | `maistro.delivery` | Effect channel | its own send records | — | — |
| Warden / Sentinel / Gate | `maistro.security` | trust boundary + policy decision point | `security.strikes` protocol-backed lockout state | audit durable via `persistence.pg_audit`; PostgreSQL deployments use `PgStrikeTracker`, non-PostgreSQL deployments use the in-memory tracker (#134/#217) | itself (canonical) |
| Authentication and identity | `maistro.auth`, `maistro.identity` | Principal | n/a | service-key store | itself (canonical) |
| Authorization, privilege, governance | `maistro.privilege`, `maistro.policy`, `maistro.governance` | Authorization decision | n/a | — | itself (canonical, ADR-068 partly unbuilt) |
| Secrets vault | `maistro.vault` | Secret material | n/a | age-encrypted file | OS file permissions |
| Memory | `maistro.memory` | Learning, Episode, Outcome | n/a (domain state) | `persistence.pg_learnings`/`pg_outcomes` on a `postgresql://` URL, `sqlite_*` on SQLite, in-memory otherwise; pgvector embeddings live on learning rows when configured | `memory.scopes`, `memory.exposure` (unreachable) |
| Sessions | `maistro.sessions` | Conversation history | `sessions.store` TTL pruning | `persistence.pg_sessions` on PostgreSQL, `sqlite_sessions` on SQLite, in-memory otherwise | session trust floor |
| Archive tier | `maistro.archive` | Cold storage for records that are still authoritative | n/a (placement, not lifecycle) | object storage or a local directory; tombstone stays in PostgreSQL where required | inherits record scope |
| Relational persistence | `maistro.persistence` | Storage adapters | n/a | itself — `pg_*` is wired for PostgreSQL; SQLite remains for homelab/local use | — |
| Local state writer | `maistro.state` | Single-writer SQLite | n/a | itself | — |
| Ontology | `maistro.ontology` | Semantic object layer | n/a | `ontology.registry` (unreachable; in-memory) | — |
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
| maistro-server HTTP app | `maistro_server` | Product entry point | `maistro.tasks.queue` (delegated) receipt plus canonical Run spine | inherited | `maistro.auth` + rate limiter |
| Agent Conductor HTTP surface | `main`, `routes`, `middleware`, `protocols`, `adapters`, `models`, `stores`, `config`, `logging_setup`, `settings_defaults` | Product entry point | mixed: `stores` in-memory dicts, `models` SQLAlchemy | `models` + `services.pg_store` | `middleware` auth + `middleware.privilege` (unreachable) |
| Agent Conductor services | `services` | Product services | `services.dag_run_store` — parallel run identity, event-derived, authoritative for current UI | `services.pg_store` | per-route |
| Canvas ability | `maistro_canvas` | Graph of canvas Nodes | `canvas.executor` pipeline + `canvas.runner` (unreachable) claim/lease/reap state machine | `canvas.store` (unreachable; PostgreSQL) | `maistro_canvas.auth` |
| Open Design integration | `maistro_design` | Renderer Providers | `design.engine` | `design.stores` | `design.trust` |
| Evolve tournament optimizer | `maistro_evolve` | Graph of evaluation Nodes | `evolve.cycle` orchestrates; no universal work-state machine of its own | `evolve.serialize` (unreachable) | — |
| RSI autorun | `maistro_rsi` | Run per improvement cycle | `rsi.coordinator` orchestrates; result records, no universal work-state machine | `rsi.spec_tracker`, quarantine ledger | `rsi.quarantine` gate |
| Turing self-model | `maistro_turing`, `maistro-turing-backend` | Optional cognitive Providers | `turing.runtime` actor + chat session; no universal work-state machine | backend DB via `TuringMemoryBridge` | backend `middleware.auth` |
| ADR/spec registry CLI | `maistro_registry` | Governance tooling | n/a | filesystem | — |
| Bootstrap installer | `maistro_bootstrap` | Installer | n/a | filesystem | — |

## Disposition and evidence

`Unreachable` is the share of the subsystem's production modules that no entry point reaches, from a fixed vocabulary, recomputed by the checker from the same import graph and the same `quality/reachability-baseline.json` the reachability ratchet enforces:

| | |
|---|---|
| `none` | none of them |
| `few` | up to a fifth |
| `some` | up to a half |
| `most` | more than half, but not all |
| `all` | every module in the subsystem |

A share rather than the `19/62` this column used to carry, because the denominator is the subsystem's module count: any pull request that added a module anywhere invalidated the cell for every other open pull request, on a line none of them wrote (#605, ADR-082926-061d). For the exact counts behind each word, run `python scripts/check-convergence-matrix.py --census`.

`Dependencies` names convergence work that must land before the row reaches its target.

<!-- matrix:disposition -->
| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |
|---|---|---|---|---|---|---|
| Run / NodeRun / Attempt lifecycle | reached via `maistro.graph.durable_runs` from `services.dag_agents` | `none` | KEEP — canonical | ADR-081226-a66b, ADR-081426-1f7c, ADR-081626-f383, ADR-082826-b601 | property/conformance tests in `formal/` plus core lifecycle suites | #42, #43, #45, #251 |
| Graph execution | `services.dag_agents.run_registered_dag`; `maistro.container` node resolver | `few` | MIGRATE — traversal state must separate from lifecycle state | ADR-062, ADR-081226-69ee | a durable graph execution whose Run/NodeRun/Attempt records reproduce the traversal | #44, #34 |
| Request front door and DI | `maistro.container.route_request` | `none` | MIGRATE — Conduit is constructed but no shipped product routes through it | ADR-019, ADR-096 | a real Conductor chat turn that traverses Conduit and yields a `run_id` | #41, #53 |
| Task queue and runner | `maistro_server.main`, `adapters.task_backend` | `none` | MIGRATE — becomes an admission receipt over a canonical Run | ADR-018, ADR-056, ADR-097 | task submission returns a `run_id`; `TaskRecord` no longer holds terminal truth | #41, #43 |
| A2A delegation | `maistro.a2a` exported API; no shipped caller | `none` | MIGRATE — delegation must create child Runs | ADR-058 | one local and one remote delegation with durable `parent_run_id` correlation | #47 |
| Recurrence / schedules | `services.scheduler` background loop | `few` | KEEP — converging: the cursor is canonical and durable, execution is not | ADR-082126-f69c (supersedes ADR-046) | `services/scheduler.py` advances the canonical `ScheduleStore` only after a Run exists (#231); it still executes through `run_registered_dag`, whose `DurableRunStore` is disjoint from the canonical `RunStore` — #251 | #46, #62, #231, #251 |
| Repo tooling | the `.github/workflows/*.yml` step that executes the script | `some` | KEEP — the 43 rooted scripts are the gate set; the 19 unrooted are dispositioned, 10 of them behind a disabled workflow and 1 reached only through a shell installer | ADR-082526-aef8 | `scripts/check-reachability.py` roots tooling at the workflow steps that run it; `tests/test_check_reachability.py` | #33, #236, #249 |
| Planning and wave orchestration | `maistro.orchestrator` exported API | `some` | MIGRATE — wave fan-out/fan-in belongs to Graph nodes | ADR-071, ADR-052 | a wave plan that executes as a Graph with per-branch NodeRuns | #44, #34 |
| Builders pipeline | none | `all` | MIGRATE — wholly unreachable and owns a duplicate executor | ADR-090, ADR-099 | Builders stages appear as NodeRuns; `builders.graph_executor` deleted | #49, #35 |
| Workspace / Project scope | `routes.projects`, `routes.workspaces` | `none` | CONNECT — the Workspace store is durable and both scope APIs reach canonical Workspace/Project authorization; canonical Run-store enforcement remains | ADR-081226-9944, ADR-081426-b1d3 | every Run carries a Project id enforced at the store boundary | #37, #38 |
| Agents | `maistro.container` factory; `services.agent_materialization` | `some` | MIGRATE — agents become Node implementations behind Providers | ADR-004, ADR-035 | agent invocation creates an Invocation record; per-agent event emission retired | #55, #56, #34 |
| Capability / Provider / Binding / Invocation | `services.capabilities_wiring`, `routes.capabilities` | `few` | KEEP — canonical effect path, incompletely adopted | ADR-081226-6b46 | every shipped model/tool effect has an Invocation row | #55, #56, #57 |
| Model providers | `maistro.container` provider wiring | `none` | KEEP | ADR-079, ADR-070426-ac56 | provider parity tests; no new direct caller escapes | #56 |
| Router and classifier | `maistro.container.route_request` | `few` | KEEP — pure decision layer | ADR-007, ADR-089 | scoring tests; router chooses Provider, never executes | — |
| Tool execution | `services.tool_executor`, `maistro.container` | `some` | MIGRATE — tool calls must be governed Invocations | ADR-050, ADR-051, SPEC-252 | tool call produces Invocation + authorization + expected-effect evidence | #57, #59 |
| Sandbox isolation | `maistro.cli` `sandbox status`; no execution path yet | `none` | CONNECT — ExecutionRuntime story needs it | ADR-093, ADR-054 | Attempt executes inside sandbox with enforced budgets | #42, #34 |
| Skills, code registry, repertoire | `routes.skills`, `services.mcp_client` | `most` | MIGRATE — one governed supply-chain path | ADR-083, ADR-069, ADR-070 | signed-code verification on real register/load path | #59, #34 |
| Credentials | `routes.credentials`, `services.credential_store_v2` | `most` | MIGRATE — rotation belongs at Provider selection | ADR-063 | real Invocation outcome triggers scoped rotation | #58 |
| Quota and billing | `routes.quotas`, `maistro.container` | `most` | MIGRATE — cost attaches to Invocation | ADR-085 | token/cost metadata on Invocation | #56, #63 |
| External integrations | exported API | `all` | CONNECT — bridges with no shipped caller | ADR-029 | one integration reached from product route | #34 |
| Delivery gateway | none | `all` | CONNECT | ADR-047 | delivery effect recorded as Invocation | #34, #57 |
| Warden / Sentinel / Gate | `maistro.container`, `maistro_server` middleware | `few` | MIGRATE — core/server enforcement exists; Hive product-path coverage still incomplete | ADR-073, ADR-072, ADR-072726-0d6b | durable strikes on PostgreSQL are proven (#217); real Hive chat must prove Warden/Sentinel traversal | #66, #67, #74 |
| Authentication and identity | `routes.auth`, `middleware`, `maistro_server` auth | `none` | KEEP | ADR-059, ADR-084, ADR-077 | Argon2id registration + bcrypt upgrade | #32 |
| Authorization, privilege, governance | `middleware.privilege` (unreachable), `maistro.policy` | `some` | CONNECT — approver matrix partly unbuilt | ADR-028, ADR-068, ADR-081226-6e34 | beyond-authority action resolves approver scope from policy | #60 |
| Secrets vault | `maistro.cli`, installer | `none` | KEEP | SPEC-011 | round-trip encryption tests | — |
| Memory | `routes.memory`, `maistro.container` | `some` | KEEP — domain state; provenance and archive policy still converge | ADR-034, ADR-011, ADR-091, ADR-057, ADR-082226-5104, ADR-082226-d3dd | scoped pgvector recall is live; archive conformance passes; producing Run provenance/policy remain | #64, #133 |
| Sessions | `routes.chat`, `maistro_server.api.ws` | `some` | KEEP — correlates to Runs, does not own them | ADR-048, ADR-070426-e8a3 | session id correlated on Run without owning lifecycle | #64 |
| Archive tier | `maistro.container` when `archive_url` is set | `none` | KEEP — storage tier, not lifecycle | ADR-082226-f436, ADR-082226-5104 | filesystem + S3 conformance; archive-eligibility policy still open | #133 |
| Relational persistence | `maistro.container` (both backends), Alembic | `none` | KEEP — PostgreSQL canonical stores and SQLite homelab adapters are wired | ADR-082226-5104, ADR-087, ADR-012 | container selects durable prompt/audit stores with backend conformance; zero relational modules unreachable | — |
| Local state writer | `maistro.reactor`, CLI | `none` | KEEP | SPEC-010 | single-writer concurrency tests | — |
| Ontology | none | `all` | CONNECT — accepted design, no consumer | ADR-036 | subsystem resolves semantic object through registry | #34 |
| Portability / backup | none | `all` | CONNECT | ADR-081, ADR-101 | backup/restore preserves canonical correlated records | #62, #34 |
| Events and checkpoints | `maistro.container`, `events.durable_log` | `few` | KEEP — canonical envelope, incompletely adopted | ADR-086, ADR-081226-7248 | migrated event families share envelope + Workspace sequence | #61, #62 |
| Observability | `maistro_server` middleware, `adapters` Langfuse | `none` | KEEP | ADR-037, ADR-082, ADR-055 | one trace spans request → Run → NodeRun → Attempt → Invocation | #63 |
| Resilience | `maistro.container`, `resilience.slo` | `some` | KEEP | ADR-038, ADR-066 | circuit/SLO primitives wired to real producers | #63 |
| Collaboration | none | `all` | CONNECT | ADR-070426-3a1f | collaborative edit correlated to Run | #34 |
| Reactor loop | `maistro.reactor` (installer-launched) | `none` | KEEP | SPEC-013, ADR-086 | loop timing tests | — |
| Prompts and personas | `maistro.container`, `routes.agents` | `few` | KEEP | ADR-060, ADR-081226-e626 | persona seed/eval protocol tests | — |
| Codebase analysis | `maistro.tools` call sites | `none` | KEEP | ADR-065 | tool-level tests | — |
| Core CLI | `maistro.cli` console script | `some` | KEEP — thin client, no local lifecycle | ADR-096 | CLI commands hit Conductor API only | — |
| Shared contracts and config | imported by every package | `few` | LIBRARY | ADR-019, ADR-081226-034b | dependency-direction + compatibility-owner fitness checks | #36 |
| Test scaffolding | test suites only | `all` | LIBRARY — unreachable by construction | ADR-065, ADR-032 | used by checked test suites | — |
| maistro-server HTTP app | `maistro_server.main` | `none` | MIGRATE — task queue is receipt; chat front door now uses Container/Conduit | ADR-076, ADR-096, ADR-082426-2192 | `/v1/tasks` and `/v1/chat/completions` both yield canonical Run identity | #43, #234 |
| Agent Conductor HTTP surface | `main` (uvicorn) | `few` | MIGRATE — product surface must read canonical stores | ADR-096, ADR-094 | Run views rendered from canonical stores and surviving restart | #65, #53 |
| Agent Conductor services | route registration + background loops | `some` | MIGRATE — `dag_run_store`, scheduler and graph/product seams still duplicate canonical responsibilities | ADR-096 | DAG/scheduler/chat paths use canonical Runs and projections only | #53, #35, #231 |
| Canvas ability | `maistro_canvas.canvas.routes`, `routes.canvas` | `some` | MIGRATE — pipeline stages become NodeRuns | ADR-045, ADR-040, ADR-067 | canvas stages visible as NodeRuns with retries as Attempts | #52 |
| Open Design integration | `routes.design`, `services.design_service` | `few` | MIGRATE — renderers become Providers | ADR-061, ADR-100 | render effect recorded as Invocation | #52, #55 |
| Evolve tournament optimizer | `routes.evolution`, `services.evolution` | `few` | MIGRATE — cycle is Run, battle is NodeRun | ADR-088, ADR-070126-6386, SPEC-070126-9d37 | tournament history reproducible from canonical Runs | #51 |
| RSI autorun | `maistro_rsi.cli`, `routes.rsi` | `few` | MIGRATE — cycles become Runs over authorized work source | ADR-088 | every RSI cycle has Run provenance; backlog through adapter | #50 |
| Turing self-model | `maistro_turing.runtime`, turing backend `main` | `none` | MIGRATE — reachable paths only; cognition remains gated | ADR-081426-fb9f, ADR-070426-9f47 | reachable Turing execution carries Run/Invocation correlation | #54 |
| ADR/spec registry CLI | `maistro_registry.cli` | `none` | KEEP — lifecycle relationships are now prospectively validated | ADR-031, ADR-062026-9b30, ADR-097 | strict registry validation + #239 lifecycle-evidence cases | #30, #239 |
| Bootstrap installer | `maistro_bootstrap` console script | `none` | KEEP | ADR-020, ADR-033 | installer smoke tests | — |

## Current convergence boundary after M0

- Every unreachable production module is classified. Executing CONNECT/RETIRE dispositions is M1 work under #34/#35; M0 does not pretend that the migration is complete.
- maistro-server chat is now a real Container/Conduit product path (#222), while Hive/Conductor remains the product migration target (#53/#66).
- PostgreSQL strike state is wired through the Gate-compatible tracker (#217); security convergence still has product-path work rather than a persistence fiction.
- Core scheduling owns occurrence identity and exact-one Run claims (#229), while the **live Hive scheduler** has not adopted that seam; #231 is the explicit remaining product migration.
- Relational persistence is fully reached: PostgreSQL is the canonical durable backend, while SQLite remains the explicit single-instance/homelab backend; prompt and audit persistence now follow the selected backend rather than silently falling back to memory.
- The matrix checker proves structure, reachability counts, reference integrity and — since #378 — that every module named as a current owner is one a product path reaches. What it still cannot prove is a cell that names no module: 30 of the 156 owner cells describe a non-module owner in prose, and that count is itself checked so the gap cannot widen quietly. #31's acceptance-state machinery governs machine-verifiable completion claims, and material ownership changes must update this human-reviewed planning surface.

## Related

- `quality/reachability-baseline.json` — ratcheted unreachable set.
- `quality/reachability-dispositions.json` — CONNECT/LIBRARY/RETIRE classification per unreachable module (#33).
- `quality/ac-state.json` — measured acceptance evidence and design coverage (#31/#166).
- `quality/execution-lifecycles.json` — classified work-state enums (#36).
- `docs/quality-gates.md` — enforcement boundaries and known limitations.
