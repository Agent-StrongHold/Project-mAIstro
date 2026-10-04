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
| ADR-103 | v1 | Accepted | 2026-10-01 | 2026-10-01 | 2026-10-01 | Knowledge-stage ladder on the Learning record — MEMORY → LEARNING → VALIDATED → REPERTOIRE; forward-only single-step transitions, durable append-only provenance ledger; a knowledge stage never grants authority. |
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
| ADR-070426-b5e9 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Six-tier priority system (P0–P5) refining ADR-010 lanes — routing weight, model bias, token multiplier, eviction order. |
| ADR-070426-c4b2 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | CapabilityProfile — per-agent (capability, intent_class) → permission / EMA skill score / measured cost vector; router substrate. |
| ADR-070426-e8a3 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Session Trust Floor — monotonically non-increasing per-session trust reducer; compaction cannot heal it; WardenVerdict.confidence. |
| ADR-070426-e9da | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Header-based CSRF defense (`X-Maistro-Request`) for hive-conductor's cookie-authenticated mutations; docs-only, flags the conftest fixture update as acceptance-blocking. |
| ADR-070426-f2a0 | v1 | Accepted | 2026-07-04 | 2026-07-06 | 2026-08-20 21:03 CDT | Optional external renderers as discoverable capability providers behind maistro-design. |
| ADR-072726-0d6b | v3 | Accepted | 2026-07-27 | 2026-09-09 | 2026-09-26 08:15 CDT | Sentinel permission table: fail-closed default. |
| ADR-073126-c4e1 | v2 | Accepted | 2026-07-31 | 2026-07-31 | 2026-09-30 16:45 CDT | Release and versioning process: lockstep tags, single publish path. |
| ADR-081226-034b | v1 | Accepted | 2026-08-12 | 2026-08-12 | 2026-08-20 21:03 CDT | Package Ownership and Dependency Direction. |
| ADR-081226-69ee | v1 | Accepted | 2026-08-12 | 2026-08-12 | 2026-08-20 21:03 CDT | Graph and Node Execution Model. |
| ADR-081226-6b46 | v2 | Accepted | 2026-08-12 | 2026-08-12 | 2026-10-01 15:22 CDT | Capability, Provider, Binding and Invocation. |
| ADR-081226-6e34 | v1 | Accepted | 2026-08-12 | 2026-08-12 | 2026-08-20 21:03 CDT | Scoped Grants and Deny-Wins Authorization. |
| ADR-081226-7248 | v3 | Accepted | 2026-08-12 | 2026-08-12 | 2026-10-01 15:22 CDT | Event and Checkpoint Model. |
| ADR-081226-9944 | v1 | Accepted | 2026-08-12 | 2026-08-12 | 2026-08-20 21:03 CDT | Canonical Product Hierarchy and Ownership. |
| ADR-081226-a66b | v1 | Accepted | 2026-08-12 | 2026-08-12 | 2026-08-20 21:03 CDT | Run, NodeRun and Attempt Lifecycle. |
| ADR-081226-bb3a | v2 | Accepted | 2026-08-12 | 2026-08-12 | 2026-10-01 15:22 CDT | Template, Object and Provenance Semantics. |
| ADR-081226-e626 | v2 | Accepted | 2026-08-12 | 2026-08-12 | 2026-09-19 16:40 CDT | Persona and Product Surface Model. |
| ADR-081426-1f7c | v1 | Accepted | 2026-08-14 | 2026-08-14 | 2026-08-20 21:03 CDT | ExecutionRuntime Contract. |
| ADR-081426-b1d3 | v1 | Accepted | 2026-08-14 | 2026-08-14 | 2026-08-20 21:03 CDT | Project Scope Tree. |
| ADR-081426-fb9f | v1 | Proposed | 2026-08-14 | — | 2026-08-20 21:03 CDT | Turing future cognitive runtime capability and activation gate. |
| ADR-081626-f383 | v2 | Accepted | 2026-08-16 | 2026-08-16† | 2026-08-24 18:34 CDT | Canonical Attempt Execution Lease and Fencing Contract. |
| ADR-082126-f69c | v2 | Accepted | 2026-08-21 | 2026-08-21 | 2026-09-30 16:45 CDT | Recurrence produces Runs: schedules are definitions, not a second runtime. |
| ADR-082226-4478 | v2 | Proposed | 2026-08-22 | — | 2026-08-21 22:38 CDT | Retire single-purpose demo endpoints in favour of one governed tool surface. |
| ADR-082226-4cd4 | v1 | Proposed | 2026-08-22 | — | 2026-08-22 17:26 CDT | StrikeTracker is a protocol, and the protocol is only what Gate calls. |
| ADR-082226-5104 | v2 | Accepted | 2026-08-22 | 2026-08-22 | 2026-08-21 20:53 CDT | Storage architecture: PostgreSQL as durable system of record, LadybugDB as per-Workspace working memory. |
| ADR-082226-d3dd | v2 | Superseded | 2026-08-22 | 2026-08-22† | 2026-08-24 13:15 CDT | An Archive tier below durable memory, on any S3-compatible or local object store. |
| ADR-082226-f436 | v5 | Proposed | 2026-08-22 | — | 2026-08-25 15:53 CDT | Object storage is an archive tier below durable memory, not a backup. |
| ADR-082226-ff3c | v3 | Accepted | 2026-08-22 | 2026-08-25 | 2026-08-30 05:07 CDT | Design coverage: one monotone number for how much of the decided design is proven. |
| ADR-082326-5386 | v3 | Accepted | 2026-08-23 | 2026-08-25 | 2026-08-25 01:01 CDT | Outbound HTTP policy at the shared-client seam. |
| ADR-082326-8194 | v3 | Accepted | 2026-08-23 | 2026-08-23 | 2026-08-25 15:08 CDT | Embedding vectors live on the memory rows, at one declared dimension. |
| ADR-082326-c126 | v4 | Accepted | 2026-08-23 | 2026-09-27 | 2026-09-26 00:38 CDT | Chat turn Run granularity and retention. |
| ADR-082426-19ed | v1 | Accepted | 2026-08-24 | 2026-08-24 | 2026-08-24 18:51 CDT | A Run cannot claim success over a node that failed. |
| ADR-082426-2192 | v5 | Accepted | 2026-08-24 | 2026-08-24 | 2026-09-26 15:30 CDT | maistro-server builds a Container, and the OpenAI door routes through it. |
| ADR-082426-6201 | v1 | Accepted | 2026-08-24 | 2026-08-24 | 2026-08-24 18:11 CDT | In-agent delegation is not a NodeRun, and the A2A local transport has no consumer. |
| ADR-082426-82c7 | v4 | Accepted | 2026-08-24 | 2026-08-24 | 2026-08-24 18:58 CDT | A schedule firing is claimed by its occurrence, not by the cursor. |
| ADR-082426-a47f | v3 | Accepted | 2026-08-24 | 2026-08-24 | 2026-08-24 18:29 CDT | Terminalizing a Run settles its open NodeRuns, and closes them to further movement. |
| ADR-082426-e3ff | v1 | Accepted | 2026-08-24 | 2026-08-24 | 2026-08-24 18:34 CDT | The fence guards the worker-authored write, and acceptance is one of them. |
| ADR-082426-f170 | v3 | Accepted | 2026-08-24 | 2026-08-24 | 2026-08-24 18:30 CDT | A requested cancellation is not a parked failure, and the Attempt cannot say which it is. |
| ADR-082526-0d30 | v3 | Accepted | 2026-08-25 | 2026-08-25 | 2026-09-27 01:00 CDT | CI runner cost is measured per PR head, in job-minutes, not estimated over a time window. |
| ADR-082526-1899 | v3 | Accepted | 2026-08-25 | 2026-08-25 | 2026-08-30 05:07 CDT | Gate the wired-but-never-read DI attribute; transitive deadness does not find it. |
| ADR-082526-237d | v2 | Accepted | 2026-08-25 | 2026-08-25 | 2026-09-11 06:58 CDT | Derive terminal Run state from a complete logical NodeRun frontier. |
| ADR-082526-3011 | v2 | Accepted | 2026-08-25 | 2026-08-25 | 2026-08-30 05:07 CDT | The setup-uv release is the flake fix; the uv pin is determinism. Both live in one wrapper. |
| ADR-082526-3ca6 | v3 | Accepted | 2026-08-25 | 2026-08-25 | 2026-08-30 05:07 CDT | The Container owns the delegation dependencies, and Hive resolves them at call time. |
| ADR-082526-547c | v2 | Accepted | 2026-08-25 | 2026-08-25 | 2026-08-30 05:07 CDT | The suite-inventory count is a sum of per-change deltas, not a shared row. |
| ADR-082526-7f02 | v1 | Accepted | 2026-08-25 | 2026-08-25 | 2026-08-24 20:04 CDT | Dispatch identity belongs to the Attempt, not to the Run's admission provenance. |
| ADR-082526-9fa2 | v2 | Accepted | 2026-08-25 | 2026-08-25 | 2026-08-30 05:07 CDT | The gates are gated too: scripts/ enters the diff gate, with the boundary drawn at repo-truth tooling. |
| ADR-082526-aef8 | v3 | Accepted | 2026-08-25 | 2026-08-25 | 2026-08-30 05:07 CDT | Repo tooling gets a reachability graph, so a gate's evidence can reach the top rung. |
| ADR-082526-b36a | v2 | Accepted | 2026-08-25 | 2026-08-25 | 2026-09-14 20:20 CDT | A lease that stops being renewed is reclaimed; liveness is proven, not assumed. |
| ADR-082526-cb51 | v2 | Accepted | 2026-08-25 | 2026-08-25 | 2026-08-30 05:07 CDT | The diff gate declares what it measures; absent from the report is a failure, not a skip. |
| ADR-082526-ef55 | v2 | Accepted | 2026-08-25 | 2026-08-25 | 2026-08-30 05:07 CDT | An absent link in the ADR → spec → AC chain is a per-change mandate, not only a ratchet. |
| ADR-082826-08f0 | v2 | Accepted | 2026-08-28 | 2026-08-28 | 2026-08-28 20:33 CDT | Interrupted-Run recovery has one disposition table, keyed on proven liveness. |
| ADR-082826-51b9 | v2 | Accepted | 2026-08-28 | 2026-08-28 | 2026-08-30 05:07 CDT | Voice intent reports only the capability containment actually leaves it. |
| ADR-082826-b601 | v2 | Accepted | 2026-08-28 | 2026-08-28 | 2026-09-14 19:12 CDT | A canonical consumer executes admitted Runs that no caller drives. |
| ADR-082826-d9f5 | v3 | Accepted | 2026-08-28 | 2026-08-28 | 2026-08-28 22:34 CDT | The durable Graph store becomes a projection over the canonical Run store. |
| ADR-082926-061d | v1 | Accepted | 2026-08-29 | 2026-08-29 | 2026-08-29 07:05 CDT | The convergence matrix states an unreachable share, not a transcribed count. |
| ADR-082926-0b72 | v1 | Accepted | 2026-08-29 | 2026-08-29 | 2026-08-29 09:32 CDT | Conductor settings are durable, or the write fails. |
| ADR-082926-25a2 | v1 | Accepted | 2026-08-29 | 2026-08-29 | 2026-08-29 05:55 CDT | AC-state bounds are folded from per-branch notes, not held on one shared line. |
| ADR-082926-3b80 | v1 | Accepted | 2026-08-29 | 2026-08-29 | 2026-08-29 09:04 CDT | A dashboard layout is saved to the Conductor's data boundary, or the save fails. |
| ADR-082926-65bf | v1 | Proposed | 2026-08-29 | — | 2026-08-29 12:19 CDT | Template versions hold a candidate state before they become active. |
| ADR-082926-730d | v1 | Accepted | 2026-08-29 | 2026-08-29 | 2026-08-29 13:55 CDT | One asyncpg pool per database, owned by the registry. |
| ADR-082926-a6ab | v1 | Accepted | 2026-08-29 | 2026-08-29 | 2026-08-29 12:19 CDT | Candidate validation runs where the edits do, or it does not run. |
| ADR-082926-d0dc | v1 | Proposed | 2026-08-29 | — | 2026-08-28 23:15 CDT | Save-as-template records the object it was saved from, outside the content hash. |
| ADR-083026-0596 | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 12:43 CDT | A store's private state is not an interface: signals cross the boundary as protocol queries. |
| ADR-083026-12f7 | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 05:58 CDT | A run record declares every field it reports, and states the bound it keeps. |
| ADR-083026-14c3 | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 03:39 CDT | An emptied Attempt output is repaired only where a second copy proves it was emptied. |
| ADR-083026-1cb1 | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 12:42 CDT | Correlation is ambient: one execution context, bound at the seams that hold the ids. |
| ADR-083026-3d92 | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 10:06 CDT | Profile state has one durable owner, and no acknowledged write reaches nothing. |
| ADR-083026-427c | v2 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-29 21:43 CDT | A prompt version and a prompt label are separate facts, written in one transaction. |
| ADR-083026-4b70 | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 19:41 CDT | memory_entries.embedding is repaired to vector(1536); a column's declared type is asserted, not assumed. |
| ADR-083026-56ee | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 19:27 CDT | A session turn names its producing Run, and a correlation id keeps its own name. |
| ADR-083026-5fab | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 03:57 CDT | A session turn carries an identity, and is appended at most once under it. |
| ADR-083026-6c72 | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-09-03 00:22 CDT | A durable HITL deadline is an absolute boundary, and one canonical write settles it. |
| ADR-083026-6e2a | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-31 00:15 CDT | Graph continuation, not events.checkpoints, is the canonical graph recovery checkpoint. |
| ADR-083026-a322 | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 14:31 CDT | Episodic memory is durable, and the scope rule has one meaning in two languages. |
| ADR-083026-a91e | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 10:06 CDT | An unmeasured metric is absent, not zero. |
| ADR-083026-aba1 | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 16:36 CDT | A record with no caller says so, and a turn's token total says how many calls reported one. |
| ADR-083026-cdcb | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 09:16 CDT | A design project's org and team are soft scope axes, enforced at the store. |
| ADR-083026-e602 | v1 | Accepted | 2026-08-30 | 2026-08-30 | 2026-08-30 15:46 CDT | A record names the execution that produced it, filled from the ambient context. |
| ADR-083126-5e62 | v2 | Accepted | 2026-08-31 | 2026-08-31 | 2026-09-02 15:40 CDT | Generated quality evidence is not the judge after trusted-base migration. |
| ADR-090226-9c3f | v1 | Accepted | 2026-09-02 | 2026-09-02 | 2026-09-02 23:01 CDT | An episodic memory names the execution that stored it. |
| ADR-090726-9a4e | v1 | Accepted | 2026-09-07 | 2026-09-07 | 2026-09-07 15:59 CDT | The Hybrid — crypto-bound approvals: WebAuthn presence, Biscuit delegation, hash-chained evidence. |
| ADR-091226-1341 | v1 | Accepted | 2026-09-12 | 2026-09-12 | 2026-09-12 12:11 CDT | Gates Ran evaluates path-scoped execution evidence from measured changed files; ambiguous scope fails closed. |
| ADR-091626-ba4f | v1 | Accepted | 2026-09-16 | 2026-09-16 | 2026-09-16 | The Workspace design system is a first-party Tier-1 bundled Open Design system: shared token schema plus a fixed actor quartet, four state faces, honest undo outcomes and a 12px floor; personas rebind four values only. |
| ADR-091726-7c2a | v1 | Accepted | 2026-09-17 | 2026-09-17 | 2026-09-17 | A requirements interview precedes every Goal and CreativeBrief commit: one plain question at a time, the record answers first, free text, defaults only where defensible, nothing written until the person confirms; the draft carries every field's source. |
| ADR-092326-7ed7 | v1 | Accepted | 2026-09-23 | 2026-09-23 | 2026-09-23 | One dedicated Workspace Agent per Workspace (stable `workspace-agent:{id}` row in the one roster, swappable persona template, default `program_manager`); Workspace-less turns run in the caller's per-user default Workspace, chosen by a durable insert-once claim and never resurrected. |
| ADR-092326-97c4 | v1 | Accepted | 2026-09-23 | 2026-09-23 | 2026-09-23 | Shared PostgreSQL is the single owner of canonical Workspace identity: Hive's embedded runtime uses maistro-engine's database and never migrates; on that durable path Hive's legacy Workspace mirror is imported once and never written or replayed. |
| ADR-092526-4391 | v1 | Proposed | 2026-09-25 | — | 2026-09-25 | The durable user model is a separate non-decaying `UserModelFact` record (revision lineage, sensitivity/shareability, validity window, re-promotion-blocking tombstones); promoting a Workspace/Project/AGENT fact into the same user's model is audited self-consent, amending SPEC-242; Hive's profile stays user-authored preferences; no Workspace traverses another's Ladybug graph. |
| ADR-092626-c1e7 | v1 | Proposed | 2026-09-26 | — | 2026-09-26 | A Workspace work campaign is versioned operator policy that only narrows the BacklogItems/linked Goals an authorized actor may choose; it grants no permission, owns or reassigns no Goal, adds no scheduler or lifecycle, and audits every decision by actor and policy version (SPEC-092626-1831, #103). |
| ADR-092926-7a01 | v1 | Proposed | 2026-09-29 | — | 2026-09-29 07:00 CDT | Closed-loop design process — Goal→Rubric→Explore→Execute→Evaluate→Refine as one Graph/Run; freezes the M7 kind table (Goal, Rubric, CreativeBrief, Pack, FenceDecision, EvalRecord, Canvas-as-tool, Design Studio-as-host), the three redirect targets, eval-on-Run, and kind fencing; gates M7 A2–A7 (SPEC-092926-7a01, #790). |
| ADR-093026-7a90 | v1 | Proposed | 2026-09-30 | — | 2026-09-30 | The design process is a first-class object graph on the canonical pipeline: Rubric as a versioned ontology object bound to Goal, eval records on the same Run/NodeRun/Attempt, product/game/book packs as interchangeable shape selectors, park/redirect/accept as a HITL fence on waiting NodeRuns, refine as a later Attempt, and Evolve/RSI as read-only consumers — no Design-Studio-private universe (SPEC-093026-7a90, #790). |
| ADR-100126-b118 | v1 | Proposed | 2026-10-01 | — | 2026-10-01 | Declared DAG execution budgets are canonical policy: `max_cycles` enforces a frontier-wave budget (clamped 1–20, fail-closed, provenance-recorded), per-node `timeout_s` becomes the canonical Attempt `ExecutionRuntime` deadline (clamped 1–600s), and product-runner transport constants can no longer extend work past it (#1184). |
| ADR-100126-f9d6 | v1 | Accepted | 2026-10-01 | 2026-10-01 | 2026-10-01 | Engine lifecycle state gates `/health/ready` — `startup_failed`/`starting`/`stopped`/unreadable answer 503 so healthchecks pull the instance from rotation; `not_started` keeps the historical contract for lifespan-less contexts and liveness `/health` stays 200 (#1181). |

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
