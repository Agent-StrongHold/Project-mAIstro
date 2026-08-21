# ADR Decision Backlog

Tracked list of **open architectural decisions** for maistro-engine, produced by the layered
consistency + coverage review (2026-05). The ADR corpus is internally consistent (PRs #76–81);
this file tracks what is *still undecided* so the decision space is finite and worked top-down
instead of discovered ad hoc.

It is built from (a) the corpus's own self-admitted deferrals — 59 "out of scope", 16 "separate
ADR", 12 "follow-up ADR", 3 "follow-up SPEC", 12 "deferred" markers — plus (b) subsystems with
code but no ADR, plus (c) second-order decisions the recent ADRs opened.

## Legend

Status per item:
- ☐ **open** — needs a decision
- ✅ **decided** — answer banked (ADR pending) or drafted; the PR is noted inline

Dispositions that are *not* engine decisions (Stronghold / Turing / deferred-to-vN / no-opinion) live
in `OUT-OF-SCOPE.md`, not here. `(←ADR-NNN)` marks an item the named ADR explicitly deferred.

---

## Status snapshot

- **Drafted (PRs #76–81):** renumber+backfill · ADR-068 unified authz · consistency fixes ·
  ADR-026 immutable CA · ADR-069 code registry · supersede ADR-030 · open-Q closures ·
  ADR-070 Repertoire pattern · ADR-071 task planner/orchestration.
- ✅ **Banked, ADR pending:** Warden/Sentinel+threat-model · web/session · config-mgmt · skills
  trust · MCP gateway · deployment · backup/DR · alerting · library versioning · evolve
  (experimental) · Builders pipeline.

---

## Tier 1 — load-bearing now (things already-shipped code/ADRs depend on)

### Security & authorization substrate
- ✅ **Warden + Sentinel spec ADR** *(drafted ADR-073, PR #83)* — detection taxonomy (layered heuristics → LLM-judge), the
  hybrid policy model (code detectors + DB-stored declarative thresholds/allow-lists/approver-
  matrix, RBAC-gated online edits, human-readable export), PDP/PEP, decision audit. *ADR-068/050/051
  delegate enforcement to this; it's code-only today.*
- ✅ **Threat-model ADR** *(drafted ADR-072, PR #83)* — assets/adversaries/trust-boundaries; **anchor: malicious third-party
  code** (skill/MCP/dependency); defense = signing + microVM (ADR-069) + trust tiers + SBOM.
- ☐ **Approver-policy-matrix schema** — concrete format of `(action, for-scope) → approved-by`
  (←ADR-068).
- ☐ **Elevation-grant storage + TTL**, and **break-glass / emergency access** when approvers are
  unreachable (←ADR-068).
- ☐ **Agent-authority computation** — how "an agent holds a *subset* of its owner's authority" is
  actually computed/enforced (←ADR-068, ADR-058).
- ☐ **Authz-decision audit format** — fields, tamper-evidence (←ADR-068).
- ☐ **RLPHD predictor SPEC** — model class, features, θ update rule, cold-start (←ADR-068 follow-up SPEC).

### Governance dialectic — Policy ⇄ ADR deconfliction
- ✅ **Policy⇄ADR deconfliction-loop ADR** *(drafted ADR-074, PR #83)* — the learning policy engine
  (Warden/Sentinel adaptive weights + RLPHD) = *revealed preference*; ADRs = *declared intent*. When a
  learned-policy change conflicts with an ADR (or N deployed artifacts), it **never auto-activates** —
  held (fail-safe, ADR stays source of truth) → admin review with impact analysis (which ADR clause,
  which N artifacts, the evidence behind the learning). Three outcomes: **revert the learning** (ADR
  wins; teaches predictor down), **scoped exception** (coexist; waiver + expiry), **amend ADR + reconcile
  the N artifacts** (learning wins; PR to the ADR + fix conflicts). Direction gated by ADR centrality:
  **safety-critical ADRs don't bend** — a drift against them is a **policy-poisoning signal** → security
  review, default revert (this is the threat-anchor immune system). **The conflict-check IS the Repertoire
  *Rehearse* step (ADR-070):** a learned change is a *Compose*; it must *Rehearse* against ADR invariants +
  deployed contracts before commit. All outcomes audited as VCs (ADR-024/068). *Closes a real hole in
  decision #7 / ADR-068 / ADR-070: online-mutable + adaptive policy could silently drift from the ADRs
  with no reconciliation path.* Requires ADRs to carry machine-checkable invariants (ADR-032 tie-in).
- ✅ **Policy-conformance SPEC** *(drafted SPEC-206, PR #83)* — the comparison engine. A
  candidate policy decision is checked against authorities in **strict precedence order, stopping at
  the first conflict**: **(1) ADRs** → **(2) Specs** → **(3) prior policy decisions**. The hierarchy is
  legal: ADRs = constitution (near-inviolable; safety ADRs do not bend), Specs = statutes (derived from
  ADRs; usually win, amendable only if the parent ADR allows), prior policy = case-law precedent (a new
  decision may supersede old precedent with recorded rationale — this is how the learned policy evolves).
  The SPEC defines how each layer's invariants are expressed + checked, what "conflict" means per layer,
  and the routing into the ADR's three outcomes. Needs ADRs + Specs to carry machine-checkable invariants
  (ADR-031/032) and the prior-policy store to be queryable (the DB policy store, decision #7).

### Web / session / client-auth
- ✅ **Web-session security ADR** — opaque server-side session (live privilege re-resolution, instant
  revoke), cookie hardening (HttpOnly/Secure/SameSite, idle+abs expiry, rotation), CSRF tokens,
  per-IP/user rate-limit, WebSocket `authorize()`. *No JWT for sessions (dynamic authority).*

### Versioning & lifecycle (no artifact has a story today)
- ✅ **Library versioning ADR** — maistro-core pre-1.0 / break-freely + CHANGELOG + consumers pin
  exact. *Light.*
- ☐ **HTTP API versioning** — `/v1→/v2` policy, deprecation/sunset window, error envelope (faces clients).
- ☐ **Recipe / agent versioning + deprecation + hot-reload + canary** (←ADR-053 deferred A/B + hot-reload).
- ☐ **Tool versioning / deprecation lifecycle.**
- ☐ **Skill versioning / SemVer compatibility.**
- ☐ **DB schema evolution policy** beyond the first migration — online migration, rollback (←ADR-012 scope).
- ☐ **Template publish CI/CD + breaking-change versioning** (←ADR-033 ×2 "separate engine ADR").
- ☐ **Ontology versioning / schema migration** (←ADR-036).

### Config & operations
- ✅ **Config-management ADR** — DB source-of-truth for nearly everything, online-editable under RBAC;
  live-unsafe config (deploy/bootstrap/secrets) static in files/helm/vault; human-readable export.
- ✅ **Deployment ADR** — compose (Conductor) + K8s/Helm (Stronghold), both wiring ADR-038 health
  probes + rolling/drain.
- ✅ **Backup & DR ADR** — local backup required baseline + optional pluggable cloud connectors
  (Drive/Azure/S3/Backblaze); portable exports: settings (JSON/YAML) + agents/DAGs/dashboards
  (JSON, doubles as cross-platform import) (←ADR-026/038/056 "separate ADR").
- ✅ **Alerting/SLO ADR** — reuse ADR-047 delivery gateway + severity tiers + SLO-burn (ADR-038);
  channels configurable (not hardcoded) (←ADR-037 deferred).

---

## Tier 2 — production readiness

### Orchestration & agents
- ✅ **Planner/orchestration** — ADR-071, drafted PR #81 (SuperPlanner+MasterOrchestrator as Repertoire
  ensemble: template-match → MCTS/ToT → Pregel supersteps + Borg reconciler + speculative exec).
- ✅ **Repertoire pattern** — ADR-070, drafted PR #81 (cross-cutting reuse-first cascade).
- ☐ **Builders pipeline ADR** — the Frank/Mason/Auditor stage machine (spec→tests→code→audit),
  runtime-version lifecycle (ready/draining/retired), Quartermaster spec-emission + template store.
  *Code-only; only ADR-032 (contracts) touches it. A Repertoire instance.*
- ☐ **Planner value-function / rollout model**; **goal-class** determination; desired-state for fuzzy
  goals; preemption policy; MCTS budget bounds (←ADR-071).
- ☐ **Multi-step saga orchestration** (←ADR-050).
- ☐ **A2A async worker-pool / fan-out** (←ADR-058 marked experimental); peer discovery + trust
  bootstrap.
- ☐ **Agent-as-data lifecycle** — AgentCard versioning, retirement, hot-swap.
- ☐ **Multi-conductor (HA) resume** (←ADR-056 single-conductor v0).
- ☐ **Task queue + lane-scheduling depth** — queue semantics (priority, fairness, backpressure at
  intake), ADR-010 LIVE/BACKGROUND depth, cancellation propagation into the queue (←ADR-010/018).

### Router, models, prompts, classifier
- ☐ **Router scoring ADR** — formula weights/tuning, scarcity input source, task-type bonuses
  (router-scoring = 0 ADRs).
- ☐ **Classifier ADR** — 3-phase thresholds, multi-intent handling, complexity tiers.
- ☐ **LLM provider / model registry ADR** — model-per-task selection, pricing, **local-P40-vs-cloud
  routing**, provider failover (beyond ADR-038), model versioning/deprecation.
- ☐ **Prompt-template management ADR** — store, versioning, the `prompts/` module (prompt-template = 0).

### Tools / skills / MCP / supply-chain
- ✅ **Skills trust ADR** — signed (publisher VC) + tiers untrusted→canary→trusted + microVM + canary
  metrics gate; admin signs promotion.
- ✅ **MCP gateway ADR** — admin allow-list + egress allow-list (SSRF) + microVM for code + Sentinel
  policy + **Warden scans every ingress AND egress** + untrusted tools default irreversible.
- ☐ **Code-registry second-order** — signing-key hierarchy (who signs), entry revocation, microVM
  resource defaults (←ADR-069).
- ☐ **SBOM tooling + Sigstore/cosign signing ADR** (←ADR-039 ×2) — ties the supply-chain threat anchor.
- ☐ **Browser-tool safety + sandbox egress policy** (default-deny egress allow-list).
- ☐ **Tool result caching / memoization.**

### Quota / billing / rate-limiting
- ☐ **Cost attribution + quota policy ADR** — per-user/agent/task spend; rate-limiting/throttling.
- **Billing / invoicing / metering** — Stronghold (multi-tenant commercial).

---

## Tier 3 — depth / quality / v2

### Memory & learning
- ☐ **Memory consolidation ADR** — when/how memories merge, contradiction resolution, hallucination
  detection, decay schedule detail (←ADR-016 underspecified).
- ☐ **Algorithmic prompt compression SPEC** — token-level compression (e.g. LLMLingua-style) of the
  SPEC-189 verbatim tail / low-fidelity summary bands, distinct from LLM summarization (←ADR-063026-a91f
  gap: SPEC-189's `fidelity` controls what's kept, not how densely the kept portion is encoded).
- ☐ **Vector store + embedding-model versioning** — pgvector vs external, re-embedding on model change
  (←ADR-016/048 semantic-search deferred).
- ☐ **Cross-scope memory sharing & consent** — promotion (user→team→org), read-authority, cross-agent
  discovery (←ADR-057 covers write authority only).
- ☐ **Memory-v2 design** (←ADR-034).
- ✅ **Data lifecycle (engine side) = basic delete only**;  retention/RTBF/residency/audit-integrity/
  compliance → Stronghold.
- ☐ **maistro-evolve** — ✅ experimental, no stability contract (intended: genome=recipe, fitness=
  outcomes, one-way→registry). ADR marks it experimental.

### Observability & reliability
- ☐ **Distributed tracing across A2A/wave hops**; trace sampling for long workflows (←ADR-037).
- ☐ **Trace export to long-term storage (S3/blob)** (←ADR-037).
- ☐ **Chaos-engineering harness** (←ADR-038).
- ☐ **Replay proxy detail** — what/where the substrate proxy is (←ADR-055).
- ☐ **Capacity / load planning** — throughput targets, concurrency caps, saturation behavior.
- ☐ **Events / triggers / recipes semantics** — bus delivery guarantees, trigger model.
- ☐ **Emit the ADR-declared-but-unemitted events** — `approval.gate.*`, `tool.compensator_invoked`,
  `agent.lifecycle`, `task.lifecycle`, `security.violation`, `policy.decision`, `memory.consolidation`,
  `quota.exhausted` (layer-3 code work).

### Identity / crypto / recovery
- ☐ **Account recovery + key-compromise + offboarding ADR** — lost-seed recovery, admin-signed
  device re-enroll, offboard revokes sessions/VCs, SLIP39 multi-admin.
- ☐ **DID method choice** — did:key vs did:web defaults, Universal Resolver (←ADR-024 deferred).
- On-chain DID methods, DIDComm v2 transport — Medley/v2 (←ADR-024/027).

### Canvas (product)
- ☐ **Canvas pipeline ADR(s)** — image-gen pipeline, streaming/SSE generation progress, parallel
  render, pagination, skill-marketplace integration (←ADR-042/043).
- ☐ **Lulu print / PDF-X fulfilment** (←ADR-041).
- ☐ **Book-maker product** — wizard UX, templates, export formats, collaboration.
- Cross-tenant asset sharing →  Stronghold (←ADR-041/044/045).

### Governance / testing / release
- ☐ **Testing-strategy ADR** — coverage targets, mutation-kill, property-based, formal-conformance,
  e2e, CI gating, Pact tooling choice (←ADR-032).
- ☐ **Feature-flags + gradual-rollout ADR** (feature-flag = 0).
- ☐ **Changelog / release-notes / deprecation-policy ADR** (changelog = 0).
- ☐ **Incident response / runbooks ADR.**
- ☐ **Error taxonomy + user-facing messages.**
- i18n / a11y / mobile-PWA — product-UX, later.

---

## Turing-specific ADR set (`packages/maistro-turing/`)

*Per decision (2026-05-30): the autonoetic self-model is product-specific and gets its **own**
Turing ADRs, not folded into the general engine corpus.* (Code exists; **zero** ADRs.)

- ☐ **Placement decision** — Turing ADR home/numbering (subdir `docs/adr/turing/` vs `repo: maistro-turing`
  front-matter vs a reserved number band).
- ☐ **Autonoetic loop ADR** — the continuous self-aware processing loop (the ADR-030 "Turing-only"
  boundary, now in-repo).
- ☐ **Personality model ADR** — Mood + HEXACO drives.
- ☐ **Proactive producers ADR** — blog / reflection / curiosity / emotion.
- ☐ **Dream / consolidation loop ADR** — frequency, memory consolidation tie-in.
- ☐ **Self-consistency-as-tests ADR** — "the same self that started the run finishes it," measurable
  via property tests (the ADR-030 v1.0 MVP framing).
- ☐ **Turing↔core bridge ADR** — how `bridge.py` adapts memory/security from maistro-core.

---

## Second-order decisions opened by the recent ADRs (068–071)

- ☐ Repertoire **"input class"** definition + matching (embedding vs keys vs taxonomy); demotion
  thresholds; cold-start; multi-match conflict (←ADR-070).
- ☐ (authz/code-registry/planner second-order items listed under their Tier-1/2 clusters above.)

---

## Not in this backlog — see `OUT-OF-SCOPE.md`

Dispositions that are *settled as not-our-call* live in **`OUT-OF-SCOPE.md`**, not here:
- **Stronghold scope** — multi-tenant isolation, RTBF/retention/residency/audit-integrity/compliance,
  policy-engine choice, multi-region, cross-tenant sharing, billing.
- **Deferred to v1/v2/v3** — ontology facets/query-language, semantic session search, canvas
  pagination/streaming, substrate CA distribution, scheduler multi-replica, inbound messaging, etc.
- **No opinion** — tooling choices, dashboard layouts, channel selection, per-product SLO numbers.
- **Turing scope** — the autonoetic ADRs above are tracked here but are out of the *general engine*
  corpus (Turing's own set).

This backlog is the source of truth for **in-scope, still-open** engine decisions only.

---

*Maintenance: check items off as ADRs land; move ✅→ when drafted, →done when merged.*
