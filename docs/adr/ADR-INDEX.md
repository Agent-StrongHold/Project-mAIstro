# ADR Index — in-scope decisions

Every **in-scope** architectural decision for maistro-engine, one line each, with version + lifecycle
dates. Companion docs: **`OUT-OF-SCOPE.md`** (decided *not* our call — no-opinion / Stronghold /
Turing / deferred-to-vN) and **`DECISION-BACKLOG.md`** (in-scope but not yet decided).

- **Ver** — revision count (git commits touching the file, following renames).
- **Status** — mirrored from each ADR's own front matter, which is canonical (#379) and is
  what the lifecycle machine, the AC ladder and the citation gate all read. Accepted ·
  Proposed (decided, not yet ratified) · Deferred · Deprecated · Superseded.
  `scripts/check-adr-index.py` fails CI if this column, `Created` or `Accepted` drifts from
  the corpus; `--fix` regenerates them. `Ver`, `Last Modified` and `Summary` are not derived
  and are never rewritten.
- **Created** authored · **Accepted** first-accepted (`†` = created-date proxy where the `accepted:`
  field is absent on an Accepted/Superseded ADR) · **Last Modified** git last-commit (Central time).

| ID | Ver | Status | Created | Accepted | Last Modified | Summary |
| ---- | ----- | -------- | --------- | ---------- | --------------- | --------- |
| ADR-001 | v3 | Superseded | 2026-04-26 | 2026-04-26† | 2026-05-29 17:48 CDT | Original branching strategy (integration as PR base) — superseded by ADR-095. |
| ADR-002 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Per-port spec-first workflow: a written spec precedes code for each port. |
| ADR-003 | v3 | Accepted | 2026-04-26 | 2026-04-26† | 2026-10-01 15:22 CDT | Agent-runtime gap analysis — roadmap mapping archived-branch work to future ADRs. |
| ADR-004 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | AgentSpec + AgentOutput envelopes — the typed invoke/result contract. |
| ADR-005 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-11 08:14 CDT | Pydantic schemas + `SCHEMA_REGISTRY` for runtime lookup by dotted path. |
| ADR-006 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-11 08:14 CDT | AgentRecipe + RecipeRegistry — an agent is data (YAML recipe). |
| ADR-007 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | VariantSelector via Thompson sampling (explore/exploit over prompt variants). |
| ADR-008 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | StructuredOutputParser — typed/validated LLM output with retry context. |
| ADR-009 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Spawner pattern for constructing agents. |
| ADR-010 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Lane-based scheduling — LIVE (interactive) vs BACKGROUND. |
| ADR-011 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Memory engine + session-factory wiring (init, DB-URL handling). |
| ADR-012 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | First Alembic migration — memory tables + pgvector. |
| ADR-013 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Memory types — Learning/Episodic/Outcome + scopes + 7 tiers + weight bounds. |
| ADR-014 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Memory protocols (store interfaces for DI). |
| ADR-015 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Learning type + InMemoryLearningStore (dedup, isolation, auto-promotion). |
| ADR-016 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | EpisodicMemory + 7-tier weights + store (reinforce/decay/retrieve). |
| ADR-017 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Outcome + InMemoryOutcomeStore (records outcomes, success rates). |
| ADR-018 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Persist TaskRecord at queue/runner boundaries (fire-and-forget durability). |
| ADR-019 | v4 | Accepted | 2026-05-06 | 2026-05-06 | 2026-05-30 00:14 CDT | Canonical source split — core is product-agnostic; multi-tenancy is Stronghold's. |
| ADR-020 | v2 | Accepted | 2026-05-07 | 2026-06-10 | 2026-05-29 22:00 CDT | Setup wizard — browser-first install ceremony (mandatory 2-user). |
| ADR-021 | v2 | Accepted | 2026-05-07 | 2026-05-07† | 2026-05-29 22:00 CDT | Conductor Seed — BIP39/BIP32 HD root of trust (one seed backs up everything). |
| ADR-022 | v2 | Accepted | 2026-05-07 | 2026-06-10 | 2026-05-29 22:00 CDT | Hardware signing devices (Ledger/Trezor/YubiKey/mobile) as optional seed sources. |
| ADR-023 | v2 | Accepted | 2026-05-07 | 2026-06-10 | 2026-05-29 22:00 CDT | Agent crypto ops + spending policy (propose→sign→execute, caps, hot/cold). |
| ADR-024 | v2 | Accepted | 2026-05-07 | 2026-06-10 | 2026-05-29 22:00 CDT | Agent identity via DID + Verifiable Credentials (federation trust, audit VCs). |
| ADR-025 | v2 | Deferred | 2026-05-07 | — | 2026-05-29 22:00 CDT | Electrum server — Medley plugin for household-private Bitcoin backend. |
| ADR-026 | v3 | Accepted | 2026-05-07 | 2026-06-10 | 2026-05-30 00:14 CDT | Internal trust root — local CA from the seed (immutable root, leaf rotation). |
| ADR-027 | v2 | Deferred | 2026-05-07 | — | 2026-05-29 22:00 CDT | Lightning-native federation — payment-graph reputation + spam resistance. |
| ADR-028 | v4 | Accepted | 2026-05-07 | 2026-05-07† | 2026-05-29 23:53 CDT | Mandatory two-tier admin/user privilege separation with wallet-signed elevation. |
| ADR-029 | v2 | Accepted | 2026-05-07 | 2026-06-10 | 2026-05-29 22:00 CDT | Pluggable networking & identity substrate (Tailscale/Headscale/NetBird/…). |
| ADR-030 | v2 | Superseded | 2026-05-07 | 2026-05-07 | 2026-05-30 00:14 CDT | Four-repo governance — superseded by the monorepo consolidation. |
| ADR-031 | v1 | Accepted | 2026-05-07 | 2026-05-07 | 2026-05-07 16:39 CDT | Front-matter + registry conventions (ADR/spec schema + CI validator). |
| ADR-032 | v1 | Accepted | 2026-05-07 | 2026-05-07 | 2026-05-07 16:39 CDT | Contracts as acceptance criteria (+ mutation testing). |
| ADR-033 | v1 | Accepted | 2026-05-07 | 2026-05-07 | 2026-05-07 16:39 CDT | Templates + Copier workflow for scaffolding downstream products. |
| ADR-034 | v1 | Accepted | 2026-05-07 | 2026-05-07 | 2026-05-07 16:39 CDT | Memory canonical ownership — engine owns memory architecture; products parameterize. |
| ADR-035 | v1 | Accepted | 2026-05-07 | 2026-05-07 | 2026-05-07 16:39 CDT | Catalog ownership split — engine-simple vs Stronghold multi-tenant. |
| ADR-036 | v1 | Accepted | 2026-05-07 | 2026-05-07 | 2026-05-07 16:51 CDT | Ontology / semantic object layer (v1 Semantic facet; entity registry). |
| ADR-037 | v1 | Accepted | 2026-05-07 | 2026-05-07 | 2026-05-07 16:51 CDT | Observability taxonomy — traces/metrics/logs/events + required spans/topics. |
| ADR-038 | v1 | Accepted | 2026-05-07 | 2026-05-07 | 2026-05-07 16:51 CDT | Reliability taxonomy — retries/circuit-breakers/fallbacks/error-budgets/healthchecks. |
| ADR-039 | v1 | Accepted | 2026-05-07 | 2026-05-07 | 2026-05-08 19:14 CDT | External library adoption policy (per-repo, maintainer-signal gate). |
| ADR-040 | v2 | Accepted | 2026-05-09 | 2026-06-10 | 2026-05-09 00:18 CDT | Canvas asset store — persistence for the layer model. |
| ADR-041 | v1 | Accepted | 2026-05-08 | 2026-06-10 | 2026-05-09 00:14 CDT | Canvas layer taxonomy, scene graph, and world style. |
| ADR-042 | v1 | Accepted | 2026-05-09 | 2026-06-10 | 2026-05-08 21:00 CDT | Canvas asset HTTP routes. |
| ADR-043 | v1 | Accepted | 2026-05-09 | 2026-06-10 | 2026-05-08 21:07 CDT | Canvas asset executor + tool (agent integration). |
| ADR-044 | v1 | Accepted | 2026-05-09 | 2026-06-10 | 2026-05-08 21:45 CDT | LayerRecord → AssetInstance migration plan. |
| ADR-045 | v4 | Proposed | 2026-05-09 | — | 2026-08-31 18:55 CDT | Canvas capability ↔ maistro-server /v2/canvas boundary; former separate-Studio migration is historical. |
| ADR-046 | v2 | Superseded | 2026-05-13 | 2026-06-10 | 2026-05-13 02:56 CDT | Scheduler for recurring agent tasks (cron → TaskQueue). |
| ADR-047 | v2 | Deprecated | 2026-05-13 | 2026-05-13† | 2026-05-13 02:56 CDT | Outbound delivery gateway — multi-channel notifier. |
| ADR-048 | v2 | Accepted | 2026-05-13 | 2026-05-13† | 2026-05-13 02:56 CDT | Session search — read-only episodic-memory inspector endpoint. |
| ADR-049 | v1 | Deprecated | 2026-05-13 | 2026-05-13† | 2026-05-13 13:10 CDT | Agent file-edit rollback via shadow git (atomic edits, PR candidates). |
| ADR-050 | v3 | Accepted | 2026-05-13 | 2026-05-13† | 2026-05-30 00:14 CDT | Tool reversibility taxonomy (internal/reversible/irreversible) + compensators. |
| ADR-051 | v3 | Accepted | 2026-05-13 | 2026-05-13† | 2026-05-29 23:53 CDT | Tool approval gates — plan preview + impact escalation + learned trust (→ RLPHD). |
| ADR-052 | v1 | Deprecated | 2026-05-13 | 2026-05-13† | 2026-05-13 13:10 CDT | Parallel agent waves — per-wave branch isolation + fan-in merge. |
| ADR-053 | v2 | Accepted | 2026-05-13 | 2026-06-10 | 2026-05-30 00:14 CDT | Recipe overlay composition (engine base + product overlay, schema-driven merge). |
| ADR-054 | v2 | Accepted | 2026-05-13 | 2026-06-10 | 2026-05-29 22:16 CDT | Agent sandbox lifecycle + per-task budget enforcement. |
| ADR-055 | v1 | Proposed | 2026-05-13 | — | 2026-05-13 13:10 CDT | Observability extensions — recorded-response replay + PII sensitivity tiers. |
| ADR-056 | v1 | Accepted | 2026-05-13 | 2026-05-13† | 2026-05-13 13:10 CDT | Task crash recovery — durable resume with wave verification. |
| ADR-057 | v1 | Accepted | 2026-05-13 | 2026-05-13† | 2026-05-13 13:10 CDT | Memory exposure mode — system-managed vs agent-managed (configurable). |
| ADR-058 | v1 | Proposed | 2026-05-29 | — | 2026-05-29 08:58 CDT | A2A delegation (in-process + federated; budgets, loop guard, SSRF-safe). |
| ADR-059 | v2 | Proposed | 2026-05-29 | — | 2026-05-29 22:00 CDT | OAuth2 user authentication layered over service-key authz. |
| ADR-060 | v1 | Proposed | 2026-06-01 | — | 2026-08-20 21:03 CDT | Persona-as-seed: declarative domain templates, pluggable Scorer protocol, and two-tier eval statistics. |
| ADR-061 | v3 | Accepted | 2026-05-29 | 2026-05-29† | 2026-08-24 21:39 CDT | maistro-design — composable design skills + design systems package. |
| ADR-062 | v3 | Accepted | 2026-05-19 | 2026-05-19† | 2026-10-01 15:22 CDT | Graph execution protocol — DAG node types, executor, phases. |
| ADR-063 | v3 | Accepted | 2026-05-20 | 2026-05-20† | 2026-10-01 15:22 CDT | Credential pool + automatic key rotation (strategies, cooldowns). |
| ADR-064 | v2 | Accepted | 2026-05-20 | 2026-05-20† | 2026-10-01 15:22 CDT | Comprehensive secret redaction (30+ patterns, single-pass). |
| ADR-065 | v2 | Accepted | 2026-05-20 | 2026-06-10 | 2026-05-29 22:00 CDT | Test harness with a full wiring factory. |
| ADR-066 | v2 | Proposed | 2026-05-20 | — | 2026-10-01 15:22 CDT | P1 resilience & control (depth, compaction, steering, rate coordination). |
| ADR-067 | v2 | Accepted | 2026-05-09 | 2026-05-09† | 2026-05-29 22:00 CDT | Canvas asset compositor (scene graph, occlusion, prompt composition). |
| ADR-068 | v2 | Accepted | 2026-05-29 | 2026-05-29† | 2026-05-29 23:53 CDT | Unified authorization & elevation — tier ladder, approver graph, sudo self-elevation, RLPHD. |
| ADR-069 | v1 | Accepted | 2026-05-30 | 2026-05-30† | 2026-05-30 00:14 CDT | Code registry — versioned, signed, microVM-isolated execution of code refs. |
| ADR-070 | v1 | Accepted | 2026-05-30 | 2026-05-30† | 2026-05-30 08:10 CDT | The Repertoire pattern — reuse-first cascade (perform/improvise/rehearse/compose). |
| ADR-071 | v1 | Proposed | 2026-05-30 | — | 2026-05-30 08:10 CDT | General task planner & orchestration — SuperPlanner waves as a Repertoire ensemble. |
| ADR-072 | v2 | Accepted | 2026-05-30 | 2026-06-10 | 2026-09-20 22:38 CDT | Threat Model — assets, adversaries, trust boundaries (anchor: malicious third-party code). |
| ADR-073 | v2 | Accepted | 2026-05-30 | 2026-05-30† | 2026-09-20 22:38 CDT | Warden + Sentinel — threat detection and the policy decision/enforcement substrate. |
| ADR-074 | v4 | Accepted | 2026-05-30 | 2026-05-30† | 2026-09-20 22:38 CDT | Policy ⇄ ADR Deconfliction — the governance dialectic (declared intent vs revealed preference). |
| ADR-075 | v2 | Accepted | 2026-05-30 | 2026-06-10 | 2026-09-20 22:38 CDT | Universal Artifact Versioning and Release Channels. |
| ADR-076 | v2 | Implemented | 2026-05-30 | 2026-06-10 | 2026-10-01 | HTTP API versioning via content negotiation on `Accept`/`api_version` — implemented across maistro-server and hive-conductor by the shared `maistro.api_versioning` middleware; routes stay on stable `/v1` mounts. |
| ADR-077 | v3 | Accepted | 2026-05-30 | 2026-06-10 | 2026-09-25 22:40 CDT | Web and Session Security. |
| ADR-078 | v2 | Accepted | 2026-05-30 | 2026-06-10 | 2026-09-20 22:38 CDT | Configuration Management — DB source of truth, RBAC online edit, file export. |
| ADR-079 | v1 | Proposed | 2026-05-30 | — | 2026-08-20 21:03 CDT | LLM Provider / Model Registry, Routing, and Embeddings. |
| ADR-080 | v4 | Accepted | 2026-05-30 | 2026-05-30† | 2026-09-20 22:38 CDT | Memory Dynamics — decay, reinforcement, tiers, consolidation, and cross-scope sharing. |
| ADR-081 | v1 | Proposed | 2026-05-30 | — | 2026-08-20 21:03 CDT | Deployment Topology, Backup, and Disaster Recovery. |
| ADR-082 | v2 | Accepted | 2026-05-30 | 2026-06-10 | 2026-09-20 22:38 CDT | Alerting, SLO, and Trace Context Propagation. |
| ADR-083 | v1 | Proposed | 2026-05-30 | — | 2026-08-20 21:03 CDT | Skills and MCP Gateway Trust. |
| ADR-084 | v1 | Proposed | 2026-05-30 | — | 2026-08-20 21:03 CDT | Identity Lifecycle — DID method, agent-authority tokens, recovery, offboarding, peer trust. |
| ADR-085 | v2 | Accepted | 2026-05-30 | 2026-05-30† | 2026-09-20 22:38 CDT | Cost, Quota, and Rate Limiting. |
| ADR-086 | v2 | Proposed | 2026-05-30 | — | 2026-09-15 02:22 CDT | Events, Triggers, and the Reactor. |
| ADR-087 | v2 | Accepted | 2026-05-30 | 2026-06-10 | 2026-09-20 22:38 CDT | Database Schema Evolution — expand/contract, zero-downtime. |
| ADR-088 | v2 | Accepted | 2026-05-30 | 2026-06-10 | 2026-09-20 22:38 CDT | maistro-evolve — experimental genome optimiser. |
| ADR-089 | v2 | Accepted | 2026-05-30 | 2026-06-10 | 2026-09-20 22:38 CDT | Intent Classifier — thresholded escalation and multi-intent routing. |
| ADR-090 | v2 | Accepted | 2026-05-30 | 2026-06-10 | 2026-09-20 22:38 CDT | Builders Pipeline — the spec to tests to code to audit stage machine. |
| ADR-091 | v1 | Accepted | 2026-06-02 | 2026-06-02† | 2026-06-02 | Memory model reconciliation — storage types vs context assembly layers (7-tier filter, Layer 0-4 taxonomy, ContextAssemblyPolicy). |
| ADR-092 | v1 | Accepted | 2026-06-02 | 2026-06-02† | 2026-08-20 21:03 CDT | Capability-vs-control posture. |
| ADR-093 | v1 | Accepted | 2026-05-31 | 2026-05-31† | 2026-08-20 21:03 CDT | Sandbox isolation model — hardware-VM isolation for untrusted agent code. |
| ADR-094 | v1 | Accepted | 2026-06-01 | 2026-06-01† | 2026-08-20 21:03 CDT | Cut pydantic-ai from the conductor — call the OpenAI-compatible gateway directly. |
| ADR-095 | v1 | Accepted | 2026-05-29 | 2026-05-29† | 2026-05-29 17:48 CDT | Four-tier branch model (feat→develop→integration→main), CI-gated. |
| ADR-096 | v1 | Accepted | 2026-06-10 | 2026-06-10† | 2026-08-20 21:03 CDT | Hive Conductor / maistro-server boundary. |
| ADR-097 | v1 | Accepted | 2026-06-10 | 2026-06-10 | 2026-08-20 21:03 CDT | Lifecycle Status State Machine for ADRs and Specs. |
| ADR-098 | v1 | Accepted | 2026-06-10 | 2026-06-10 | 2026-08-20 21:03 CDT | Layer taxonomy extension — Evolve, Crypto, Connectivity, Ability, Identity. |
| ADR-099 | v1 | Proposed | 2026-06-12 | — | 2026-06-12 | Builders pipeline as a DAG (Epic-15 recreation) with gated verify-and-revise loops and iteration budgets. |
| ADR-100 | v1 | Accepted | 2026-06-14 | 2026-06-14 | 2026-06-14 | Bundled (T1) + cataloged (T2) Open Design design systems for maistro-design, with a content scan and one-click catalog import. |
| ADR-101 | v2 | Proposed | 2026-06-15 | — | 2026-10-01 15:22 CDT | Foreign harness adapters, hierarchical orchestration, and agent/skill portability. |
| ADR-102 | v1 | Accepted | 2026-09-14 | 2026-09-14 | 2026-09-14 | Sibling packages reuse maistro-core's central guarded outbound HTTP seam; no vendored SSRF control. |
| ADR-100526-be49 | v1 | Proposed | 2026-10-05 | — | 2026-10-05 | Connector/source SDK (M9-E2): out-of-tree connectors implement one `ConnectorSource` port and are driven only by the host `SyncEngine`, which stamps full connector/source/version/workspace provenance onto every record, commits per-page checkpoints scoped by (Workspace, connector, config) after items for restart-safe idempotent replay, treats deletion as explicit tombstones and drift as in-place updates, enforces declared Workspace/secret scope before connector code runs, normalizes upstream failures to canonical rate-limit/unavailable errors, and passes built-in and external implementations through one shared conformance suite surfaced as `maistro connectors verify` (#963). |
| ADR-103 | v1 | Accepted | 2026-10-01 | 2026-10-01 | 2026-10-01 | Knowledge-stage ladder on the Learning record — MEMORY → LEARNING → VALIDATED → REPERTOIRE; forward-only single-step transitions, durable append-only provenance ledger; a knowledge stage never grants authority. |
| ADR-104 | v1 | Accepted | 2026-10-05 | 2026-10-05 | — | Canonical extension context and lifecycle: least-authority seams over the governed effect plane. |
| ADR-105 | v1 | Accepted | 2026-10-05 | 2026-10-05 | 2026-10-05 | Third-party provider adapter SDK: one registration seam into canonical routing, canonical-only egress, secrets by authority, shared conformance for built-in and external adapters. Renumbered from a colliding ADR-104 at the develop sync (the extension-context ADR authored ADR-104 first, 2026-10-05 vs 2026-10-06). |
| ADR-061526-f383 | v2 | Superseded | 2026-06-15 | 2026-10-01 | 2026-10-01 15:22 CDT | Foreign harness adapters, hierarchical orchestration, and agent/skill portability. |
| ADR-062026-9b30 | v1 | Accepted | 2026-06-20 | 2026-06-20 | 2026-08-20 21:03 CDT | Date-based ADR/SPEC IDs for new records (sequential numbering frozen). |
| ADR-062226-674b | v1 | Accepted | 2026-06-22 | 2026-06-22† | 2026-08-20 21:03 CDT | Constant tunability ladder — config-backed defaults that mature toward locked constants. |
| ADR-062326-616c | v3 | Accepted | 2026-06-23 | 2026-06-23† | 2026-08-24 21:39 CDT | Design skills code export capability — React/TSX output format. |
| ADR-062326-702b | v3 | Accepted | 2026-06-23 | 2026-06-23 | 2026-08-24 21:39 CDT | Multi-modality design outputs and hierarchical artifact containers. |
| ADR-063026-a91f | v1 | Proposed | 2026-06-30 | — | 2026-08-20 21:03 CDT | Context windows are not memory — external validation of the Layer 0-4 / SessionStore architecture. |
| ADR-070126-6386 | v3 | Proposed | 2026-07-01 | — | 2026-09-03 05:27 CDT | RSI code improvement as an evolve genome tournament. |
| ADR-070426-3a1f | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Adopt the A2UI declarative agent-driven UI protocol (v0.10 pin); catalog approval maps to TrustTier; closes [engine-090]/[engine-091]. |
| ADR-070426-77d1 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Substrate / tool / agent taxonomy — light agents structurally hold zero tools; substrate-purity validation at registration. |
| ADR-070426-9f47 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Autonoetic self-model threat model — guardrail invariants G1–G18 as mandatory AC for the turing migration. |
| ADR-070426-ac56 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Wire `CostAwareRouter.fallback_chain()` into the conductor's retry loop for cross-model fallback; docs-only, DI change deferred to SPEC-280. |
| ADR-091226-1341 | v1 | Accepted | 2026-09-12 | 2026-09-12 | 2026-09-12 12:11 CDT | Gates Ran evaluates path-scoped execution evidence from measured changed files; ambiguous scope fails closed. |
| ADR-102 | v1 | Accepted | 2026-09-14 | 2026-09-14 | 2026-09-14 | Sibling packages reuse maistro-core's central guarded outbound HTTP seam; no vendored SSRF control. |
| ADR-091626-ba4f | v1 | Accepted | 2026-09-16 | 2026-09-16 | 2026-09-16 | The Workspace design system is a first-party Tier-1 bundled Open Design system: shared token schema plus a fixed actor quartet, four state faces, honest undo outcomes and a 12px floor; personas rebind four values only. |
| ADR-091726-7c2a | v1 | Accepted | 2026-09-17 | 2026-09-17 | 2026-09-17 | A requirements interview precedes every Goal and CreativeBrief commit: one plain question at a time, the record answers first, free text, defaults only where defensible, nothing written until the person confirms; the draft carries every field's source. |
| ADR-092326-7ed7 | v1 | Accepted | 2026-09-23 | 2026-09-23 | 2026-09-23 | One dedicated Workspace Agent per Workspace (stable `workspace-agent:{id}` row in the one roster, swappable persona template, default `program_manager`); Workspace-less turns run in the caller's per-user default Workspace, chosen by a durable insert-once claim and never resurrected. |
| ADR-092326-97c4 | v1 | Accepted | 2026-09-23 | 2026-09-23 | 2026-09-23 | Shared PostgreSQL is the single owner of canonical Workspace identity: Hive's embedded runtime uses maistro-engine's database and never migrates; on that durable path Hive's legacy Workspace mirror is imported once and never written or replayed. |
| ADR-092526-4391 | v1 | Proposed | 2026-09-25 | — | 2026-09-25 | The durable user model is a separate non-decaying `UserModelFact` record (revision lineage, sensitivity/shareability, validity window, re-promotion-blocking tombstones); promoting a Workspace/Project/AGENT fact into the same user's model is audited self-consent, amending SPEC-242; Hive's profile stays user-authored preferences; no Workspace traverses another's Ladybug graph. |
| ADR-092626-c1e7 | v1 | Proposed | 2026-09-26 | — | 2026-09-26 | A Workspace work campaign is versioned operator policy that only narrows the BacklogItems/linked Goals an authorized actor may choose; it grants no permission, owns or reassigns no Goal, adds no scheduler or lifecycle, and audits every decision by actor and policy version (SPEC-092626-1831, #103). |
| ADR-092926-7a01 | v1 | Proposed | 2026-09-29 | — | 2026-09-29 07:00 CDT | Closed-loop design process — Goal→Rubric→Explore→Execute→Evaluate→Refine as one Graph/Run; freezes the M7 kind table (Goal, Rubric, CreativeBrief, Pack, FenceDecision, EvalRecord, Canvas-as-tool, Design Studio-as-host), the three redirect targets, eval-on-Run, and kind fencing; gates M7 A2–A7 (SPEC-092926-7a01, #790). |

*Turing-specific ADRs (autonoetic self-model) are tracked as a separate set — see `OUT-OF-SCOPE.md`
§Turing and `DECISION-BACKLOG.md` §Turing. ADR-061 (maistro-design-package) and ADR-100 (its
bundled/cataloged design systems) land via a separate in-flight branch.*

Dispositions that are *not* engine decisions (Stronghold-only, deferred-to-vN) live in
[`OUT-OF-SCOPE.md`](OUT-OF-SCOPE.md). Open in-scope decisions from the 2026-05 review snapshot
live in [`DECISION-BACKLOG.md`](DECISION-BACKLOG.md) (historical).

> **Maintenance:** `Status`, `Created`, and `Accepted` are derived from ADR front matter
> (`python scripts/check-adr-index.py --fix`). Add missing rows with `--add-missing`.
> `Ver`, `Last Modified`, and `Summary` are reviewed prose/git metadata and are not rewritten
> by `--fix`.
