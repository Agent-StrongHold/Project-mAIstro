# ADR Index — in-scope decisions

Every **in-scope** architectural decision for maistro-engine, one line each, with version + lifecycle
dates. Companion docs: **`OUT-OF-SCOPE.md`** (decided *not* our call — no-opinion / Stronghold /
Turing / deferred-to-vN) and **`DECISION-BACKLOG.md`** (in-scope but not yet decided).

- **Ver** — revision count (git commits touching the file, following renames).
- **Status** — Accepted · Proposed (decided, not yet ratified/implemented) · Superseded.
- **Created** authored · **Accepted** first-accepted (`†` = created-date proxy where the `accepted:`
  field is absent on an Accepted/Superseded ADR) · **Last Modified** git last-commit (Central time).

| ID | Ver | Status | Created | Accepted | Last Modified | Summary |
|----|-----|--------|---------|----------|---------------|---------|
| ADR-001 | v3 | Superseded | 2026-04-26 | 2026-04-26† | 2026-05-29 17:48 CDT | Original branching strategy (integration as PR base) — superseded by ADR-095. |
| ADR-002 | v2 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Per-port spec-first workflow: a written spec precedes code for each port. |
| ADR-003 | v3 | Accepted | 2026-04-26 | 2026-04-26† | 2026-05-29 22:00 CDT | Agent-runtime gap analysis — roadmap mapping archived-branch work to future ADRs. |
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
| ADR-020 | v2 | Proposed | 2026-05-07 | — | 2026-05-29 22:00 CDT | Setup wizard — browser-first install ceremony (mandatory 2-user). |
| ADR-021 | v2 | Proposed | 2026-05-07 | — | 2026-05-29 22:00 CDT | Conductor Seed — BIP39/BIP32 HD root of trust (one seed backs up everything). |
| ADR-022 | v2 | Proposed | 2026-05-07 | — | 2026-05-29 22:00 CDT | Hardware signing devices (Ledger/Trezor/YubiKey/mobile) as optional seed sources. |
| ADR-023 | v2 | Proposed | 2026-05-07 | — | 2026-05-29 22:00 CDT | Agent crypto ops + spending policy (propose→sign→execute, caps, hot/cold). |
| ADR-024 | v2 | Proposed | 2026-05-07 | — | 2026-05-29 22:00 CDT | Agent identity via DID + Verifiable Credentials (federation trust, audit VCs). |
| ADR-025 | v2 | Proposed | 2026-05-07 | — | 2026-05-29 22:00 CDT | Electrum server — Medley plugin for household-private Bitcoin backend. |
| ADR-026 | v3 | Proposed | 2026-05-07 | — | 2026-05-30 00:14 CDT | Internal trust root — local CA from the seed (immutable root, leaf rotation). |
| ADR-027 | v2 | Proposed | 2026-05-07 | — | 2026-05-29 22:00 CDT | Lightning-native federation — payment-graph reputation + spam resistance. |
| ADR-028 | v4 | Proposed | 2026-05-07 | — | 2026-05-29 23:53 CDT | Mandatory two-tier admin/user privilege separation with wallet-signed elevation. |
| ADR-029 | v2 | Proposed | 2026-05-07 | — | 2026-05-29 22:00 CDT | Pluggable networking & identity substrate (Tailscale/Headscale/NetBird/…). |
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
| ADR-040 | v2 | Proposed | 2026-05-09 | — | 2026-05-09 00:18 CDT | Canvas asset store — persistence for the layer model. |
| ADR-041 | v1 | Proposed | 2026-05-08 | — | 2026-05-09 00:14 CDT | Canvas layer taxonomy, scene graph, and world style. |
| ADR-042 | v1 | Proposed | 2026-05-09 | — | 2026-05-08 21:00 CDT | Canvas asset HTTP routes. |
| ADR-043 | v1 | Proposed | 2026-05-09 | — | 2026-05-08 21:07 CDT | Canvas asset executor + tool (agent integration). |
| ADR-044 | v1 | Proposed | 2026-05-09 | — | 2026-05-08 21:45 CDT | LayerRecord → AssetInstance migration plan. |
| ADR-045 | v1 | Proposed | 2026-05-09 | — | 2026-05-08 21:45 CDT | Canvas Studio ↔ maistro-server /v2/canvas cutover. |
| ADR-046 | v2 | Proposed | 2026-05-13 | — | 2026-05-13 02:56 CDT | Scheduler for recurring agent tasks (cron → TaskQueue). |
| ADR-047 | v2 | Proposed | 2026-05-13 | — | 2026-05-13 02:56 CDT | Outbound delivery gateway — multi-channel notifier. |
| ADR-048 | v2 | Proposed | 2026-05-13 | — | 2026-05-13 02:56 CDT | Session search — read-only episodic-memory inspector endpoint. |
| ADR-049 | v1 | Proposed | 2026-05-13 | — | 2026-05-13 13:10 CDT | Agent file-edit rollback via shadow git (atomic edits, PR candidates). |
| ADR-050 | v3 | Proposed | 2026-05-13 | — | 2026-05-30 00:14 CDT | Tool reversibility taxonomy (internal/reversible/irreversible) + compensators. |
| ADR-051 | v3 | Proposed | 2026-05-13 | — | 2026-05-29 23:53 CDT | Tool approval gates — plan preview + impact escalation + learned trust (→ RLPHD). |
| ADR-052 | v1 | Proposed | 2026-05-13 | — | 2026-05-13 13:10 CDT | Parallel agent waves — per-wave branch isolation + fan-in merge. |
| ADR-053 | v2 | Proposed | 2026-05-13 | — | 2026-05-30 00:14 CDT | Recipe overlay composition (engine base + product overlay, schema-driven merge). |
| ADR-054 | v2 | Proposed | 2026-05-13 | — | 2026-05-29 22:16 CDT | Agent sandbox lifecycle + per-task budget enforcement. |
| ADR-055 | v1 | Proposed | 2026-05-13 | — | 2026-05-13 13:10 CDT | Observability extensions — recorded-response replay + PII sensitivity tiers. |
| ADR-056 | v1 | Proposed | 2026-05-13 | — | 2026-05-13 13:10 CDT | Task crash recovery — durable resume with wave verification. |
| ADR-057 | v1 | Proposed | 2026-05-13 | — | 2026-05-13 13:10 CDT | Memory exposure mode — system-managed vs agent-managed (configurable). |
| ADR-058 | v1 | Proposed | 2026-05-29 | — | 2026-05-29 08:58 CDT | A2A delegation (in-process + federated; budgets, loop guard, SSRF-safe). |
| ADR-059 | v2 | Proposed | 2026-05-29 | — | 2026-05-29 22:00 CDT | OAuth2 user authentication layered over service-key authz. |
| ADR-095 | v1 | Accepted | 2026-05-29 | 2026-05-29† | 2026-05-29 17:48 CDT | Four-tier branch model (feat→develop→integration→main), CI-gated. |
| ADR-062 | v2 | Accepted | 2026-05-19 | 2026-05-19† | 2026-05-29 22:00 CDT | Graph execution protocol — DAG node types, executor, phases. |
| ADR-063 | v2 | Accepted | 2026-05-20 | 2026-05-20† | 2026-05-29 22:00 CDT | Credential pool + automatic key rotation (strategies, cooldowns). |
| ADR-064 | v2 | Accepted | 2026-05-20 | 2026-05-20† | 2026-05-29 22:00 CDT | Comprehensive secret redaction (30+ patterns, single-pass). |
| ADR-065 | v2 | Proposed | 2026-05-20 | — | 2026-05-29 22:00 CDT | Test harness with a full wiring factory. |
| ADR-066 | v2 | Proposed | 2026-05-20 | — | 2026-05-29 22:00 CDT | P1 resilience & control (depth, compaction, steering, rate coordination). |
| ADR-067 | v2 | Proposed | 2026-05-09 | — | 2026-05-29 22:00 CDT | Canvas asset compositor (scene graph, occlusion, prompt composition). |
| ADR-068 | v2 | Proposed | 2026-05-29 | — | 2026-05-29 23:53 CDT | Unified authorization & elevation — tier ladder, approver graph, sudo self-elevation, RLPHD. |
| ADR-069 | v1 | Proposed | 2026-05-30 | — | 2026-05-30 00:14 CDT | Code registry — versioned, signed, microVM-isolated execution of code refs. |
| ADR-070 | v1 | Proposed | 2026-05-30 | — | 2026-05-30 08:10 CDT | The Repertoire pattern — reuse-first cascade (perform/improvise/rehearse/compose). |
| ADR-071 | v1 | Proposed | 2026-05-30 | — | 2026-05-30 08:10 CDT | General task planner & orchestration — SuperPlanner waves as a Repertoire ensemble. |
| ADR-076 | v2 | Accepted | 2026-05-30 | 2026-06-10 | 2026-07-29 | HTTP API versioning via content negotiation on `Accept`/`api_version` — not yet implemented; business routes remain plain `/v1`-path-mounted (tracked in KNOWN-GAPS.md). |
| ADR-091 | v1 | Proposed | 2026-06-02 | — | 2026-06-02 | Memory model reconciliation — storage types vs context assembly layers (7-tier filter, Layer 0-4 taxonomy, ContextAssemblyPolicy). |
| ADR-099 | v1 | Proposed | 2026-06-12 | — | 2026-06-12 | Builders pipeline as a DAG (Epic-15 recreation) with gated verify-and-revise loops and iteration budgets. |
| ADR-100 | v1 | Accepted | 2026-06-14 | 2026-06-14† | 2026-06-14 | Bundled (T1) + cataloged (T2) Open Design design systems for maistro-design, with a content scan and one-click catalog import. |
| ADR-070426-3a1f | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Adopt the A2UI declarative agent-driven UI protocol (v0.10 pin); catalog approval maps to TrustTier; closes [engine-090]/[engine-091]. |
| ADR-070426-c4b2 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | CapabilityProfile — per-agent (capability, intent_class) → permission / EMA skill score / measured cost vector; router substrate. |
| ADR-070426-77d1 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Substrate / tool / agent taxonomy — light agents structurally hold zero tools; substrate-purity validation at registration. |
| ADR-070426-b5e9 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Six-tier priority system (P0–P5) refining ADR-010 lanes — routing weight, model bias, token multiplier, eviction order. |
| ADR-070426-e8a3 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Session Trust Floor — monotonically non-increasing per-session trust reducer; compaction cannot heal it; WardenVerdict.confidence. |
| ADR-070426-9f47 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Autonoetic self-model threat model — guardrail invariants G1–G18 as mandatory AC for the turing migration. |
| ADR-070426-e9da | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Header-based CSRF defense (`X-Maistro-Request`) for hive-conductor's cookie-authenticated mutations; docs-only, flags the conftest fixture update as acceptance-blocking. |
| ADR-070426-ac56 | v1 | Proposed | 2026-07-04 | — | 2026-07-04 | Wire `CostAwareRouter.fallback_chain()` into the conductor's retry loop for cross-model fallback; docs-only, DI change deferred to SPEC-280. |

*Turing-specific ADRs (autonoetic self-model) are tracked as a separate set — see `OUT-OF-SCOPE.md`
§Turing and `DECISION-BACKLOG.md` §Turing. ADR-061 (maistro-design-package) and ADR-100 (its
bundled/cataloged design systems) land via a separate in-flight branch.*

> **Maintenance:** Ver = git revision count; Last Modified = git last-commit (Central). Both are
> derivable from git, so this table can be regenerated by script rather than hand-maintained.
