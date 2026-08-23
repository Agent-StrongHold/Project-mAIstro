# Architecture Convergence Matrix

**Status:** living document — checked by `scripts/check-convergence-matrix.py` on every PR.
**Scope:** every production module in this repository (`packages/*/src` plus the flat
`packages/*/backend` applications), partitioned into subsystems.
**Answers:** [#28](https://github.com/Agent-StrongHold/Project-mAIstro/issues/28) (M0-A1).

The convergence program has one claim to defend: there is **one execution identity** —
`Workspace/Project → Graph → Run → NodeRun → Attempt → ExecutionRuntime` — and **one effect
path** — `Capability → Provider → Binding → Invocation`. Every other lifecycle, queue,
scheduler and event bus in this repository is either a *receipt* (domain state that records
what happened), an *adapter* (a projection onto the canonical spine), or debt.

This matrix says, for each subsystem, which of those three it is today. It is a planning
surface, so it is worth exactly as much as its accuracy — which is why it is machine-checked
rather than trusted.

## What the checker enforces

`scripts/check-convergence-matrix.py` fails CI when:

1. The two tables below describe different subsystems, or the same ones in a different order.
2. The `Modules` prefixes fail to partition **every** production module. Longest prefix wins;
   a module claimed by two rows at equal prefix length, a prefix matching nothing, or a module
   matching nothing is an error. This is what makes "covers every significant subsystem"
   checkable instead of asserted — a new package cannot land unclassified.
3. A row's `Unreachable` count disagrees with the import graph
   `scripts/check-reachability.py` ratchets. A row cannot claim a subsystem is wired when the
   reachability gate says it is not reachable from any process entry point.
4. A `Disposition` is outside the fixed vocabulary.
5. A cited `ADR-…`/`SPEC-…` id has no file in `docs/adr` or `docs/specs`.

What it deliberately does **not** enforce: whether the prose in the ownership cells is true.
Reachability is a floor, not proof that an advertised capability is active — the same caveat
`quality/reachability-baseline.json` carries. Ownership claims are reviewed by humans; the
`Acceptance evidence` column names what would settle each one.

## Disposition vocabulary

| Verdict | Meaning |
|---|---|
| **KEEP** | Canonical owner, or domain state that is legitimately its own. No migration planned. |
| **MIGRATE** | Owns lifecycle/effect state that the canonical spine must own. Needs parity tests, then demotion to receipt or adapter. |
| **RETIRE** | Superseded. Delete after parity is demonstrated (M0-B3). |
| **CONNECT** | Correct design, no production entry point yet. Needs wiring, not redesign. |
| **LIBRARY** | Published surface or test scaffolding. Unreachable by construction and honestly so. |

A row's verdict describes the subsystem's **lifecycle/effect ownership**, not its code quality.
`MIGRATE` on a row does not mean the domain logic is wrong; it means the *execution truth* it
currently holds belongs to `Run`/`Invocation`.

## Ownership

`Lifecycle owner` = what holds the authoritative "what state is this work in" record today.
`Persistence owner` = what makes that state survive a restart (`—` means it does not).
`Authorization owner` = what decides whether the work is allowed (`—` means nothing does).

<!-- matrix:ownership -->
| Subsystem | Modules | Canonical concept | Lifecycle owner | Persistence owner | Authorization owner |
|---|---|---|---|---|---|
| Run / NodeRun / Attempt lifecycle | `maistro.runs`, `maistro.runtime` | Run, NodeRun, Attempt, ExecutionRuntime | itself (canonical) | `runs.sqlite_store`, `runs.store` | caller-supplied `actor_principal_id` only |
| Graph execution | `maistro.graph` | Graph, Node, GraphExecutionState | `graph.durable_runs` over `maistro.runs` | `graph.durable_runs.stores` (in-memory + execution store) | — |
| Request front door and DI | `maistro.conduit`, `maistro.container` | Request admission | none — Conduit decides and delegates, holds no state | — | container-wired Warden/Sentinel |
| Task queue and runner | `maistro.tasks` | Admission receipt | `tasks.queue` + `tasks.status` (second universal lifecycle) | `TaskRecord` upsert, best-effort (ADR-018) | `security.task_policy` |
| A2A delegation | `maistro.a2a` | Child Run | `a2a.lifecycle` worker pool (third universal lifecycle) | — | `a2a.guest_peers` trust tiers |
| Recurrence / schedules | `maistro.scheduling` | Trigger definition → Run | canonical: `evaluate()` decides, the Run owns execution | `scheduling.store` (SQLite + in-memory) | schedule's `actor_principal_id` |
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
| Warden / Sentinel / Gate | `maistro.security` | trust boundary + policy decision point | `security.strikes` lockout state | none wired — `security.pg_strikes` has no production importer | itself (canonical) |
| Authentication and identity | `maistro.auth`, `maistro.identity` | Principal | n/a | service-key store | itself (canonical) |
| Authorization, privilege, governance | `maistro.privilege`, `maistro.policy`, `maistro.governance` | Authorization decision | n/a | — | itself (canonical, ADR-068 partly unbuilt) |
| Secrets vault | `maistro.vault` | Secret material | n/a | age-encrypted file | OS file permissions |
| Memory | `maistro.memory` | Learning, Episode, Outcome | n/a (domain state) | `persistence.sqlite_learnings`/`sqlite_outcomes` on a `sqlite:` URL; in-memory otherwise. Target owner is `pg_learnings`/`pg_outcomes` + pgvector (ADR-082226-5104); neither has a caller | `memory.scopes`, `memory.exposure` |
| Sessions | `maistro.sessions` | Conversation history | `sessions.store` TTL pruning | `persistence.sqlite_sessions` on a `sqlite:` URL; in-memory otherwise. Target owner is `pg_sessions` (ADR-082226-5104) | session trust floor |
| Relational persistence | `maistro.persistence` | Storage adapters | n/a | itself — but only the `sqlite_*` half is reachable, and ADR-082226-5104 makes the `pg_*` half canonical | — |
| Local state writer | `maistro.state` | Single-writer SQLite | n/a | itself | — |
| Ontology | `maistro.ontology` | Semantic object layer | n/a | `ontology.registry` (in-memory) | — |
| Portability / backup | `maistro.portability` | Export/import of domain state | n/a | file exports | — |
| Events and checkpoints | `maistro.events` | Event envelope, checkpoint, outbox | n/a | `events.durable_log`, `events.outbox` | — |
| Observability | `maistro.observability` | Trace, metric, log | n/a | exporter-dependent | — |
| Resilience | `maistro.resilience` | Retry, circuit, SLO | circuit state per dependency | in-memory | — |
| Collaboration | `maistro.collaboration` | Multi-actor editing | its own session records | — | — |
| Reactor loop | `maistro.reactor` | Trigger evaluation loop | n/a | — | — |
| Prompts and personas | `maistro.prompts`, `maistro.personas` | Node/agent configuration | n/a | none wired — `persistence.pg_prompts` has no production importer | — |
| Codebase analysis | `maistro.codebase` | Tool implementation | n/a | — | — |
| Core CLI | `maistro.cli` | Client of the Conductor API | n/a (remote) | — | server-side |
| Shared contracts and config | `maistro`, `maistro.types`, `maistro.protocols`, `maistro.constants`, `maistro.config`, `maistro.http` | Types and protocols | n/a | — | — |
| Test scaffolding | `maistro.testing` | Test doubles | n/a | — | — |
| maistro-server HTTP app | `maistro_server` | Product entry point | `maistro.tasks.queue` | inherited | `maistro.auth` + rate limiter |
| Agent Conductor HTTP surface | `main`, `routes`, `middleware`, `protocols`, `adapters`, `models`, `stores`, `config`, `logging_setup`, `settings_defaults` | Product entry point | mixed: `stores` in-memory dicts, `models` SQLAlchemy | `models` + `services.pg_store` | `middleware` auth + `middleware.privilege` |
| Agent Conductor services | `services` | Product services | `services.dag_run_store` — a parallel run identity, event-derived, authoritative for the UI | `services.pg_store` | per-route |
| Canvas ability | `maistro_canvas` | Graph of canvas Nodes | `canvas.executor` pipeline + `canvas.runner` (a claim/lease/reap job state machine) | `canvas.store` (PostgreSQL) | `maistro_canvas.auth` (standalone API key) |
| Open Design integration | `maistro_design` | Renderer Providers | `design.engine` | `design.stores` | `design.trust` |
| Evolve tournament optimizer | `maistro_evolve` | Graph of evaluation Nodes | `evolve.cycle` orchestrates; no work-state machine of its own | `evolve.serialize` | — |
| RSI autorun | `maistro_rsi` | Run per improvement cycle | `rsi.coordinator` orchestrates; result records, no work-state machine | `rsi.spec_tracker`, quarantine ledger | `rsi.quarantine` gate |
| Turing self-model | `maistro_turing`, `maistro-turing-backend` | Optional cognitive Providers | `turing.runtime` actor + chat session; no work-state machine | backend DB via `TuringMemoryBridge` | backend `middleware.auth` |
| ADR/spec registry CLI | `maistro_registry` | Governance tooling | n/a | filesystem | — |
| Bootstrap installer | `maistro_bootstrap` | Installer | n/a | filesystem | — |

## Disposition and evidence

`Unreachable` is `unreachable/total` production modules, recomputed by the checker.
`Dependencies` names the convergence issues that must land for the disposition to be reached.

<!-- matrix:disposition -->
| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |
|---|---|---|---|---|---|---|
| Run / NodeRun / Attempt lifecycle | reached via `maistro.graph.durable_runs` from `services.dag_agents` | `0/10` | KEEP — canonical | ADR-081226-a66b, ADR-081426-1f7c, ADR-2026-08-16 | property/conformance tests in `formal/` plus core lifecycle suites | #42, #43, #45 |
| Graph execution | `services.dag_agents.run_registered_dag`; `maistro.container` node resolver | `3/57` | MIGRATE — traversal state must separate from lifecycle state | ADR-062, ADR-081226-69ee | a durable graph execution whose Run/NodeRun/Attempt records reproduce the traversal | #44, #34 |
| Request front door and DI | `maistro.container.route_request` | `0/2` | MIGRATE — Conduit is constructed but no shipped product routes through it | ADR-019, ADR-096 | a real Conductor chat turn that traverses Conduit and yields a `run_id` | #41, #53 |
| Task queue and runner | `maistro_server.main`, `adapters.task_backend` | `2/10` | MIGRATE — becomes an admission receipt over a canonical Run | ADR-018, ADR-056, ADR-097 | task submission returns a `run_id`; `TaskRecord` no longer holds terminal truth | #41, #43 |
| A2A delegation | `maistro.a2a` exported API; no shipped caller | `0/5` | MIGRATE — delegation must create child Runs | ADR-058 | one local and one remote delegation with durable `parent_run_id` correlation | #47 |
| Recurrence / schedules | `services.scheduler` background loop | `0/5` | KEEP — converged: a firing produces a canonical Run | ADR-082126-f69c (supersedes ADR-046) | `services/scheduler.py` fires through `run_registered_dag`; core scheduling suites | #46, #62 |
| Planning and wave orchestration | `maistro.orchestrator` exported API | `3/10` | MIGRATE — wave fan-out/fan-in belongs to Graph nodes | ADR-071, ADR-052 | a wave plan that executes as a Graph with per-branch NodeRuns | #44, #34 |
| Builders pipeline | none | `15/15` | MIGRATE — wholly unreachable and owns a duplicate executor | ADR-090, ADR-099 | Builders stages appear as NodeRuns; `builders.graph_executor` deleted | #49, #35 |
| Workspace / Project scope | `routes.projects`, `routes.workspaces` (partly unreachable) | `5/11` | CONNECT — correct model, incomplete wiring | ADR-081226-9944, ADR-081426-b1d3 | every Run carries a Project id enforced at the store boundary | #37, #38 |
| Agents | `maistro.container` factory; `services.agent_materialization` | `26/60` | MIGRATE — agents become Node implementations behind Providers | ADR-004, ADR-035 | agent invocation creates an Invocation record; per-agent event emission retired | #55, #56, #34 |
| Capability / Provider / Binding / Invocation | `services.capabilities_wiring`, `routes.capabilities` | `2/31` | KEEP — canonical effect path, incompletely adopted | ADR-081226-6b46 | every shipped model/tool effect has an Invocation row | #55, #56, #57 |
| Model providers | `maistro.container` provider wiring | `0/7` | KEEP | ADR-079, ADR-070426-ac56 | provider parity tests; no direct SDK calls outside this package | #56 |
| Router and classifier | `maistro.container.route_request` | `1/13` | KEEP — pure decision layer | ADR-007, ADR-089 | scoring-formula tests; router chooses a Provider, never executes | — |
| Tool execution | `services.tool_executor`, `maistro.container` | `9/26` | MIGRATE — tool calls must be governed Invocations | ADR-050, ADR-051, SPEC-252 | tool call produces Invocation + authorization + expected-effect evidence | #57, #59 |
| Sandbox isolation | none in this repo's processes | `6/6` | CONNECT — the ExecutionRuntime story needs it | ADR-093, ADR-054 | an Attempt executed inside a sandbox with enforced budgets | #42, #34 |
| Skills, code registry, repertoire | `routes.skills`, `services.mcp_client` | `12/22` | MIGRATE — one governed supply-chain path | ADR-083, ADR-069, ADR-070 | signed-code verification runs on the real register/load path | #59, #34 |
| Credentials | `routes.credentials`, `services.credential_store_v2` (unreachable) | `4/7` | MIGRATE — rotation belongs at Provider selection | ADR-063 | a rotation triggered by a real Invocation outcome | #58 |
| Quota and billing | `routes.quotas`, `maistro.container` | `8/13` | MIGRATE — cost attaches to Invocation | ADR-085 | token/cost metadata on the Invocation, not a side ledger | #56, #63 |
| External integrations | `maistro.integrations` exported API | `5/5` | CONNECT — bridges with no shipped caller | ADR-029 | one integration reached from a product route | #34 |
| Delivery gateway | none | `5/5` | CONNECT | ADR-047 | a delivery effect recorded as an Invocation | #34, #57 |
| Warden / Sentinel / Gate | `maistro.container`, `maistro_server` middleware | `11/54` | MIGRATE — construction is not enforcement | ADR-073, ADR-072, ADR-072726-0d6b | an E2E Conductor chat proving Warden/Sentinel ran on the real path | #66, #67, #68, #69, #70 |
| Authentication and identity | `routes.auth`, `middleware`, `maistro_server` auth | `0/11` | KEEP | ADR-059, ADR-084, ADR-077 | Argon2id on registration, bcrypt upgrade on login | #32 |
| Authorization, privilege, governance | `middleware.privilege` (unreachable), `maistro.policy` | `3/9` | CONNECT — ADR-068's approver matrix is decided but unbuilt | ADR-028, ADR-068, ADR-081226-6e34 | a beyond-authority action resolving an approver scope from policy | #60 |
| Secrets vault | `maistro.cli`, installer | `0/1` | KEEP | SPEC-011 | round-trip encryption tests | — |
| Memory | `routes.memory`, `maistro.container` | `12/25` | KEEP — domain state; align provenance, then move onto pgvector. The +3 are the Archive tier's store layer (ADR-082226-d3dd), CONNECT rather than debt: written and conformance-tested against a real MinIO, not yet wired, because the policy that decides what goes cold hangs off the memory-decay path (#133) | ADR-034, ADR-011, ADR-091, ADR-057, ADR-082226-5104, ADR-082226-d3dd | a memory write that names its producing Run, with its embedding on the same row; an archived record that rehydrates byte-identical | #64, #122, #133 |
| Sessions | `routes.chat`, `maistro_server.api.ws` | `1/3` | KEEP — correlates to Runs, does not own them | ADR-048, ADR-070426-e8a3 | session id correlated on a Run without owning lifecycle | #64 |
| Relational persistence | `maistro.container` (`sqlite_*` only), Alembic | `7/14` | CONNECT — the canonical Postgres half has no caller | ADR-082226-5104, ADR-087, ADR-012 | a container that wires `pg_*` for a `postgresql://` URL, and pgvector embeddings on the memory tables | #122, #33, #34 |
| Local state writer | `maistro.reactor`, CLI | `0/1` | KEEP | SPEC-010 | single-writer concurrency tests | — |
| Ontology | none | `4/4` | CONNECT — accepted design, no consumer | ADR-036 | one subsystem resolving a semantic object through the registry | #34 |
| Portability / backup | none | `4/4` | CONNECT | ADR-081, ADR-101 | a backup/restore preserving canonical Run records | #62, #34 |
| Events and checkpoints | `maistro.container`, `events.durable_log` | `2/11` | KEEP — canonical envelope, incompletely adopted | ADR-086, ADR-081226-7248 | migrated event families sharing one envelope and one Workspace sequence | #61, #62 |
| Observability | `maistro_server` middleware, `adapters` Langfuse | `0/8` | KEEP | ADR-037, ADR-082, ADR-055 | one trace spanning request → Run → NodeRun → Attempt → Invocation | #63 |
| Resilience | `maistro.container`, `resilience.slo` | `3/9` | KEEP | ADR-038, ADR-066 | circuit/SLO primitives wired to real producers | #63 |
| Collaboration | none | `3/3` | CONNECT | ADR-070426-3a1f | a collaborative edit correlated to a Run | #34 |
| Reactor loop | `maistro.reactor` (installer-launched) | `0/1` | KEEP | SPEC-013, ADR-086 | 1kHz loop timing tests | — |
| Prompts and personas | `maistro.container`, `routes.agents` | `1/13` | KEEP | ADR-060, ADR-081226-e626 | persona seed/eval protocol tests | — |
| Codebase analysis | `maistro.tools` call sites | `0/5` | KEEP | ADR-065 | tool-level tests | — |
| Core CLI | `maistro.cli` console script | `5/14` | KEEP — thin client, no local lifecycle | ADR-096 | CLI commands hit the Conductor API only | — |
| Shared contracts and config | imported by every package | `2/45` | LIBRARY | ADR-019, ADR-081226-034b | dependency-direction check; wheel-import verification | #36 |
| Test scaffolding | test suites only | `3/3` | LIBRARY — unreachable by construction | ADR-065, ADR-032 | used by the suites in `scripts/check-suite-inventory.py` | — |
| maistro-server HTTP app | `maistro_server.main` | `0/17` | MIGRATE — its task lifecycle becomes a receipt | ADR-076, ADR-096 | `/v1/tasks` submission returns a canonical `run_id` | #41 |
| Agent Conductor HTTP surface | `main` (uvicorn) | `4/67` | MIGRATE — product surface must read canonical stores | ADR-096, ADR-094 | Run views rendered from canonical stores and surviving restart | #65, #53 |
| Agent Conductor services | `main` route registration + background loops | `15/60` | MIGRATE — `dag_run_store` and `graph_runner` are duplicate lifecycle owners | ADR-096 | DAG execution creates canonical Runs; `dag_run_store` demoted to a projection | #53, #35 |
| Canvas ability | `maistro_canvas.canvas.routes`, `routes.canvas` | `8/17` | MIGRATE — pipeline stages become NodeRuns | ADR-045, ADR-040, ADR-067 | canvas stages visible as NodeRuns with retries as Attempts | #52 |
| Open Design integration | `routes.design`, `services.design_service` | `1/18` | MIGRATE — renderers become Providers | ADR-061, ADR-100 | a render effect recorded as an Invocation | #52, #55 |
| Evolve tournament optimizer | `routes.evolution`, `services.evolution` | `7/61` | MIGRATE — a cycle is a Run, a battle is a NodeRun | ADR-088, ADR-070126-6386, SPEC-070126-9d37 | tournament history reproducible from canonical Runs | #51 |
| RSI autorun | `maistro_rsi.cli`, `routes.rsi` | `4/34` | MIGRATE — cycles become Runs over an authorized work source | ADR-088 | every RSI cycle has Run provenance; BACKLOG.md read through an adapter | #50 |
| Turing self-model | `maistro_turing.runtime`, turing backend `main` | `0/23` | MIGRATE — reachable paths only; cognition stays gated | ADR-081426-fb9f, ADR-070426-9f47 | reachable Turing execution carries Run/Invocation correlation | #54 |
| ADR/spec registry CLI | `maistro_registry.cli` | `0/8` | KEEP | ADR-031, ADR-062026-9b30 | `registry.yml` front-matter validation is green | #30 |
| Bootstrap installer | `maistro_bootstrap` console script | `0/20` | KEEP | ADR-020, ADR-033 | installer smoke tests | — |

## What this matrix already establishes

- **Three subsystems own a competing work-state machine** besides `maistro.runs`, each
  verified by reading the code rather than inferred from the package's role:
  `maistro.tasks.queue` with `tasks.status` (an explicit transition table),
  `maistro.a2a.lifecycle` (`queued → assigned → running → completed/failed` plus a worker
  pool), and `maistro.builders.runtime` with `builders.graph_executor` (a `RunStatus` enum
  and free-text `run.status` assignments). A fourth, `services.dag_run_store`, owns a
  *parallel run identity* rather than a state machine — its node states are folded from
  events — but it is what the Conductor UI reads as authoritative, so it competes with
  `Run` for the same job. A fifth, `maistro_canvas.canvas.runner`, is a claim/lease/reap
  worker with `pending → claimed → done/failed/requeued` states whose leases duplicate the
  ADR-2026-08-16 execution fencing — though unlike the others it is *unstarted rather than
  superseded*: a migration exists for its leases, the reachable `canvas/executor.py` documents
  its contract, and two suites cover it under contention. All five are `MIGRATE` rows with a
  parity-before-deletion dependency on
  [#35](https://github.com/Agent-StrongHold/Project-mAIstro/issues/35).
- **Jira and Airtable no longer have four independent implementations.** The canonical ones are
  registered node kinds — `jira.poll` queries by JQL across both Atlassian backends,
  `airtable.poll` reads base/table records — plus `maistro.tools.atlassian`'s MCP client, which
  `agents/pm_runner.py` reaches. Both bespoke `httpx` clients that sat in `routes/daily_report.py`
  and `routes/daily_report_v2.py` are gone with the Daily Report feature, which was a PM-demo
  artefact superseded by workspace personas. ADR-082226-4478 records the general finding this
  came from: tool execution happened in four unrelated places, and `routes/mcp.py` discovers
  tools but cannot execute one, while `maistro.capabilities` implements the accepted
  Capability → Provider → Binding → Invocation path and is reached by none of them.
- **There is no approved model egress for anything to be outside of.** `maistro.providers` is a
  registry — catalog, router, protocols, errors — and holds no HTTP client, so it performs no
  calls. Twenty-five modules each call a completions endpoint themselves. #56's premise, "no
  legacy harness or direct-provider escape outside approved Provider code", presumes approved
  Provider code that does not exist yet; building it is the work, and until then
  `quality/model-egress.json` freezes the caller set so it can only shrink. Retiring
  `services.pm_fleet_v2` took it from 26 to 25 — progress on the count, none on the boundary.
- **Reading a module beats inferring from its package.** The disposition ledger's RETIRE rows
  were first derived from what each package is *for*; re-deriving them from what each module's
  own docstring *says* moved eight of fourteen to CONNECT. DAG hill-climbing optimises a user's
  DAG, skills and tools and is not `maistro-rsi` improving the engine's own code; `routes/projects`
  is an onboarding flow, not the project *scope* surface; `builders/orchestrator` already says core
  owns workflow state. Absence of callers distinguishes unwired from dead not at all, which is the
  entire distinction the CONNECT/RETIRE split exists to draw.
- **Evolve, RSI and Turing are *not* duplicate lifecycle owners**, though their executions
  still belong in canonical Runs (#51, #50, #54). `maistro_evolve.cycle` and
  `maistro_rsi.coordinator` are domain orchestrators holding results, not work states;
  `maistro_turing/runtime.py` is documented dead code shadowed by the same-named package.
  An earlier draft of this matrix called all three lifecycle owners on the strength of what
  their packages do rather than what their code holds — the correction is recorded here
  because a planning surface that overstates the problem misdirects the work as surely as
  one that understates it.
- **The PostgreSQL persistence layer has no caller, and a Postgres URL silently degrades —
  against a decision that names PostgreSQL the durable system of record.**
  `maistro.container` wires the `sqlite_*` stores when `database_url` starts with `sqlite:`
  and otherwise falls through to `InMemoryQuotaTracker`/`InMemoryLearningStore`/
  `InMemoryOutcomeStore`/`InMemorySessionStore`. No production module imports
  `persistence.pg_learnings`, `pg_outcomes`, `pg_sessions`, `pg_prompts`, `pg_audit` or
  `security.pg_strikes` — only `pg_agents` has a caller, in `agents/factory.py`. So a
  deployment configured with `postgresql://…` gets in-memory stores and loses everything on
  restart, with no warning. That is the failure mode `graph_runner.StubLLMNotAllowedError`
  was introduced to end elsewhere in this repo ("loud degraded modes"), and it contradicts
  the root `CLAUDE.md` subsystem table, which advertises `maistro.persistence` as
  "PostgreSQL stores". ADR-082226-5104 settles the direction: PostgreSQL *is* the durable system
  of record, pgvector carries embeddings, and SQLite is not a canonical datastore — so these are
  `CONNECT` rows (wiring owed) rather than the `RETIRE` rows an earlier reading of the code
  suggested. Filed as
  [#122](https://github.com/Agent-StrongHold/Project-mAIstro/issues/122) rather than fixed here.
- **`maistro.conduit` is constructed but unrouted.** `maistro.container` builds it; no shipped
  product path calls it. The "one front door" claim is currently a design, not a fact.
- **`maistro.builders` is 15/15 unreachable**, and one module of the fifteen —
  `builders/graph_executor.py` — drives its own traversal and writes free-text `run.status`
  values. The rest is domain logic ADR-090/ADR-099 keep: `dag.py` implements SPEC-070226-82ea
  under ADR-099, and `orchestrator.py` states the convergence rule in its own docstring ("Core
  owns workflow state. Builders runtime only returns results.").
- **Reachability is not evenly distributed debt.** Of 201 unreachable modules, 66 — a third — sit
  in four subsystems (`maistro.agents` 26, `maistro.builders` 15, Conductor `services` 15,
  `maistro.skills`/`code_registry`/`repertoire` 12), which is why
  [#34](https://github.com/Agent-StrongHold/Project-mAIstro/issues/34) burns them down by
  subsystem rather than by file.
- **Twenty-five of the modules previously counted as unreachable were never dead.** The node
  catalog registers its implementations with an eager `importlib.import_module` sweep, which an
  AST walk over `import` statements cannot see. Teaching `check-reachability.py` that idiom
  dropped the baseline from 232 to 207 with no code change and no fake imports — the gate was
  reporting its own blind spot. Every remaining row now carries an explicit
  CONNECT/LIBRARY/RETIRE disposition in `quality/reachability-dispositions.json`
  ([#33](https://github.com/Agent-StrongHold/Project-mAIstro/issues/33)).
- **The gate also could not see two modules at all.** `maistro_turing/runtime.py` and
  `producers.py` each sat beside a same-named package directory, so Python resolved the import
  to the package and the flat file could never run — both carried "DEAD CODE — superseded"
  docstrings for months. Because modules are keyed by dotted name, one silently overwrote the
  other and only one was ever analysed. `check-reachability.py` now refuses a flat module
  shadowed by a package, and the six dead files are gone.

## Corrections to the issue that requested this

[#28](https://github.com/Agent-StrongHold/Project-mAIstro/issues/28) says the matrix is
"referenced by current ADR/specs but absent from this repo". The second half is true; the first
is not. No ADR or spec in `docs/adr` or `docs/specs` references a convergence matrix — the
dangling references belong to the private planning train this repository was consolidated from,
not to committed content here. There were therefore no dangling references to resolve, and this
document is a new artifact rather than a restoration. Recorded here rather than silently
delivering against a premise that does not hold.

## Related

- `quality/reachability-baseline.json` — the ratcheted unreachable set this matrix attributes.
- `quality/reachability-dispositions.json` — CONNECT/LIBRARY/RETIRE per unreachable module,
  grouped by the subsystem rows above and CI-checked against them (#33).
- `quality/execution-lifecycles.json` — every work-state enum, classified CANONICAL / DOMAIN /
  CONVERGE, CI-checked against the code (#36).
- `KNOWN-GAPS.md` — capability-level gaps; this matrix is ownership-level.
- `docs/quality-gates.md` — where this gate sits among the other ratchets.
- `docs/adr/ADR-082226-5104-storage-architecture-postgres-durable-ladybug-working-memory.md` —
  what the durable and working stores are, and why.
- `docs/adr/ADR-082226-4478-retire-single-purpose-endpoints-for-one-governed-tool-surface.md` —
  why the demo-era per-integration endpoints retire onto one seam.
- `docs/adr/ADR-INDEX.md` — decision status of everything cited above.
