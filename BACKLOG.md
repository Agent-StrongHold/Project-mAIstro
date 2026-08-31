# Backlog

Companion to [`ROADMAP.md`](ROADMAP.md). Items are tagged by the part of the product they belong to:

- `engine-NNN` — shared substrate (runtime, ADRs, templates, registry)
- `conductor-NNN` — Conductor variant (single-tenant multi-user)
- `turing-NNN` — autonoetic variant
- `sh-NNN` — multi-tenant variant (Stronghold). **Not actionable in this repository.**
  Stronghold is a planned downstream product that will *import* the engine (root `CLAUDE.md`);
  no Stronghold code lives here. Every `sh-` item is owned by Stronghold and dispositioned
  *deferred-downstream* — it is not a second system to build alongside the engine. Where an
  item has a prerequisite that **is** actionable here, it names that engine work, because that
  prerequisite is the part this repository owns. Items naming none have no recorded engine
  prerequisite; that is a statement about what is written down, not a claim that none exists.
  Enforced by `scripts/check-backlog-consistency.py` (#30).

Maintained per [`ADR-019`](docs/adr/ADR-019-canonical-source-split.md). Each backlog header carries
a **work status**, which describes the state of the backlog item only. It is deliberately separate
from ADR/spec decision lifecycle. When an item names an ADR or spec, **that document's front matter
is the sole authoritative decision status**; this file does not duplicate or reinterpret it.
External-library adoption per [`engine#ADR-039`](docs/adr/ADR-039-external-library-adoption-policy.md).

## Work status legend

| Marker | Meaning |
|---|---|
| Proposed | Work proposed; not yet committed for implementation |
| Accepted | Work accepted into the backlog; implementation may follow |
| Implemented | Backlog work completed; any referenced ADR/spec keeps its own lifecycle status |
| Accepted (spec) | A spec records the decision, but no ADR does; binding on the spec's terms |
| Superseded | Replaced by a successor (named in `supersedes:` of successor) |
| Blocked | A `blocked-by:` dependency is unmet |
| Abandoned | Decision deliberately not taken (kept for traceability) |
| Obsolete | The item tracked work against specs that lived in the pre-consolidation sibling repositories. Those specs are not part of this repo, so the item can no longer be actioned or verified here. |

## Gap legend

| Marker | Meaning |
|---|---|
| `gap-spec` | No spec or ADR captures this decision yet |
| `gap-test` | Spec/ADR exists; no test (or test stub) covers it |
| `gap-impl` | Spec/ADR + test exist; production code does not match |

---

## Substrate items (`engine-NNN`)

### Foundation (M1 — weeks 1–4)

**[engine-001] Registry CI tooling — Implemented — v1.0 M1**
- Front-matter YAML validator (Pydantic schema from ADR-031)
- Cross-repo link checker via GitHub MCP / API: every `<repo>#<id>` resolves
- Registry generator: emits `registry/registry.json` and `registry.md`
- DAG validator on `supersedes:` and `blocks:` (no cycles)
- GitHub Action wiring: warn-only mode, hard-fail flip after day 30
- Tests: contract `boundary | unit` for the validator; `behavioral | property` for the DAG check

**[engine-002] INVENTORY auto-regenerated — Proposed — v1.0 M1**
- Blocked-by: `engine-001`

**[engine-003] Front-matter on existing engine ADRs — Implemented — v1.0 M1**
- ADRs 000–029 (30 files); renumber-on-touch per ADR-031
- ADR-000 template regenerated to match the new schema

**[engine-004] CONTRIBUTING.md and convention docs — Implemented — v1.0 M1**
- Author-facing summary of ADR-031 / 032 / 001 / **039**
- Linked from product repos' READMEs

### Templates (M2 — weeks 2–6)

**[engine-010] Copier template `single-tenant-multi-user` — Implemented — v1.0 M2**
- Knobs: `users_max`, `auth_backend`, `channels`, `host_target`.
- Evidence: `tests/templates/test_single_tenant_multi_user_renders.py` renders secure defaults,
  exercises alternate knobs through `copier update`, runs generated contract tests, and checks
  target-specific file removal/addition.

**[engine-011] Copier template `autonoetic` — Implemented — v1.0 M2**
- Knobs: `awareness_loop_hz`, `self_model`, `memory_consolidator`, `dossier_store`.
- Evidence: `tests/templates/test_autonoetic_renders.py` renders secure defaults, exercises
  alternate knobs through `copier update`, runs generated contract tests, and checks optional
  consolidator/storage file conditions.

**[engine-012] Copier template `multi-tenant` — Accepted; `gap-impl` — v1.0 M2**
- Knobs: `tenants_max`, `policy_engine`, `deploy_target`, `compliance_pack`. Round-trip vs `stronghold`

**[engine-013] Two-stream release pipeline — Proposed — v1.0 M2**
- `pkg/v*` + `template/v*` tags. Blocked-by 010/011/012

### Drift closure (M3 — weeks 3–7)

**[engine-021] Memory spec dedup (coordinator) — Obsolete — v1.0 M3**

**[engine-022] Catalog spec dedup (coordinator) — Obsolete — v1.0 M3**

### Substrate code parity (M4 — weeks 4–9)

**[engine-030] Ontology Semantic facet — Implemented — v1.0 M4**
- Per `[engine#ADR-036]`. v1.0 ships Semantic only

**[engine-031] Observability primitives — Accepted; `gap-impl` — v1.0 M4**
- Per `[engine#ADR-037]`. 3 of 6 baseline metrics live (circuit state, security blocks, request duration); remaining three await model/service_key/period label plumbing; spans + event topics open
- See also `[engine-094]` for janitor-style signal files extending event topics

**[engine-032] Reliability primitives — Accepted; `gap-impl` — v1.0 M4**
- Per `[engine#ADR-038]`. All five primitives shipped (SLO error budgets in `maistro.resilience.slo`); throttle wiring to the router scarcity input outstanding
- See also Khamel83/oneshot lane-fallback-chain pattern in `INSPIRATIONS.md`

### Contracts (M5 — weeks 6–12)

**[engine-040] Pydantic boundary contracts on all public types — Proposed — v1.0 M5**

**[engine-041] Hypothesis property tests on accepted behavioral ADRs — Proposed — v1.0 M5**
- Possible service-boundary integration with **Promptfoo** for prompt regression

**[engine-042] Pact-style contracts on A2A + MCP edges — Proposed — v1.0 M5**

**[engine-043] Mutation-testing CI wiring — Proposed — v1.0 M5**

### v1.1–v2.0 (engine — original)

**[engine-050] Cross-product agent portability proof — Proposed — v1.1**

**[engine-051] Forge iteration loop primitive — Proposed — v1.1**

**[engine-052] Compliance gap audit on accepted ADRs — Implemented — v1.1**

**[engine-060] Memory v2 (if surfaced) — Proposed — v1.2**

**[engine-061] DSPy-style task signatures evaluation — Proposed — v1.2**

**[engine-062] Mid-session model switching primitive — Proposed — v1.2**

**[engine-070] Ontology Kinetic facet — Proposed — v2.0**

**[engine-071] Ontology Dynamic facet — Proposed — v2.0**

**[engine-072] Cross-tenant ontology sharing — Proposed — v2.0**

**[engine-073] Tournament-based agent evolution wired to production routing — Proposed — v2.0**

### Discovered gaps (engine — original)

**[engine-080] Pact tooling choice — Proposed**

**[engine-081] Mutation-testing exclusion list per repo — Proposed**

**[engine-082] Backup / export semantics for memory — Proposed**

**[engine-083] Disaster-recovery / backup-restore primitives — Proposed**

**[engine-084] Chaos-engineering harness — Proposed**

**[engine-085] Trace export to long-term storage — Proposed**

### Hive Conductor distribution & frontend (migrated from archived `cutover/MASTER-PLAN.md` + `design/PRODUCT-SPEC.md`)

**[engine-100] Hosted curl installer + web wizard — Proposed**
- `get.hiveconductor.com/install.sh` and `install.hiveconductor.com` web wizard never built
- Local `get.sh`/`install.sh` cover a manual-clone install path; the hosted one-liner distribution does not exist

**[engine-101] GHCR image publishing pipeline — Implemented — Proposed; `gap-impl`**
- Cross-check `packages/hive-conductor/frontend/src` against the archived 10-page spec; several shared components exist (`AppShell.tsx`, `AgentFleetCard.tsx`, `WidgetMicroChat.tsx`) but full page coverage (Missions, Schedules, Skills marketplace, MCP discovery, CLI terminal, Container Builder, Memory Explorer) is unverified/incomplete

**[engine-103] MCP server implementations — Proposed**
- `mcp-sandbox`, `mcp-git`, `mcp-browser`, `mcp-ha`, `mcp-utils`, `mcp-trading`, `mcp-reminders` were planned as standalone MCP servers; core already has overlapping in-process tools (`tools/sandbox`, `tools/git`, `tools/browser`) — decide wrap-existing vs. build-new before scoping

**[engine-104] Port remaining legacy experimental features — Proposed**
- Shipped: Bouncer, Agent Factory, Spawner, Skill Forge, Message Board. Superseded: Heartbeat (replaced by `reactor.py`). Outstanding: APM, Red Team — feature-flagged off, not yet ported into the consolidated monorepo

**[engine-105] Wire Master Orchestrator security gate + API dispatch — Accepted; `gap-impl`**
- `orchestrator/master.py` + `orchestrator/planner.py` exist (Group J1–J4 done), but the Security Scanner gate (J5) and wiring into the `maistro-server` API (J6) from the archived consolidation plan are still open

### NEW — from May 2026 catalog review (engine)

**[engine-090] Chat-UI integration contract — Proposed; `gap-impl` — v1.1**
- OpenAI-compatible chat completions (LiteLLM gateway already exposes) **+ A2UI for rich UI generation + MCP for tools**
- Substrate: `BlakeMatthews-dev/A2UI` (Apache 2.0, v0.8 preview) — see INSPIRATIONS.md "Adjacent products"
- Tested against OWUI, LibreChat, Lobe Chat as render targets
- Defuses Open WebUI 50-user attribution clause for stronghold tenants by allowing alternative UI per tenant

**[engine-091] A2UI version-pin substrate confirmation — Proposed — v1.1**
- Pin A2UI to a specific tag in engine's Copier templates (`[engine-010/011/012]`)
- Substrate: `BlakeMatthews-dev/A2UI`

**[engine-092] CLI-Anything skills bundle — Proposed; `gap-impl` — v1.1**
- Adopt 35+ HKUDS/CLI-Anything pre-generated harnesses (GIMP, Blender, LibreOffice, OBS, etc.) as engine skills with manifests + sandbox profiles
- Apache 2.0; service-boundary (subprocess) per `engine#ADR-039`
- Substrate: `engine#ADR-006` (recipe-registry), `engine#ADR-035` (catalog split)

**[engine-093] Self-CLI generation — Proposed — v1.2**
- Run CLI-Anything against our own packages: produce `maistro-cli`, `turing-cli`, `stronghold-cli`, `engine-cli`
- Pattern reference: `Khamel83/oneshot` `bin/oneshot` CLI-first surface
- Replaces ad-hoc admin scripts; agents and operators share the same surface

**[engine-094] MCP server registry survey + catalog seed — Proposed — v1.0 M3**
- Periodic survey of `punkpeye/awesome-mcp-servers` for new candidates passing the maintainer-signal gate (`engine#ADR-039` §3)
- Tier 1 (vendor-official: Microsoft, AWS, HashiCorp, LocalStack) and Tier 2 (org-backed) populate the engine simple catalog
- Stronghold's multi-tenant catalog (`[sh-001]`) inherits the same baseline

**[engine-095] Default skills bundle — Proposed; `gap-impl` — v1.0 M3**
- Standard CLI tools wrapped as versioned skills with manifests, sandbox profiles, and policy bindings
- Categories: search (rg, fd, fzf), data (jq, yq, dasel), HTTP (curl, httpie), git (gh, lazygit), files (yazi, dust, eza), k8s (kubectl, k9s), containers (docker, podman, lazydocker), DBs (pgcli, redis-cli)
- Seeds `engine#ADR-035` simple catalog for mAIstro and Turing; multi-tenant variant for stronghold

**[engine-096] Tournament training-data labeling pipeline — Proposed; `gap-spec` — v1.2**
- Produces (agent_a_output, agent_b_output, intent, verdict) triples at scale for tournament evolution
- Pattern reference: Adala (data-labeling agents)
- Engine-side substrate for `[sh-102]` and `[turing-062]` tournament evolution

**[engine-097] Hyperagent graph runtime substrate — Implemented — v1.2**
- Graph execution primitive (was implicit in `[conductor-200]` hyperagent-graph-runtime); promote to engine substrate
- Single substrate consumed by mAIstro low-code designer and stronghold multi-tenant low-code surface

**[engine-098] Memory drift detection — Proposed; `gap-spec` — v1.1**
- Detect retrieval-quality degradation independent of decay (`engine#ADR-013`)
- Pattern reference: `compemperor/engram` drift-detection
- Engine-side; products inherit

**[engine-099] Recency-summarizer skills + description-optimizer — Proposed; `gap-impl` — v1.1**
- `recency-summary` + `restore-context` personal skills (recency bands + topic summaries + forward-looking block + `low/med/high` fidelity + source citations); prototype the SPEC-189 context-engine methodology
- TODO: run the skill-creator **description-optimizer** to tune triggering (generate ~20 trigger-eval queries → `run_loop`)
- Native home / substrate: `engine#SPEC-189` (lossless rolling context assembly)

### Discovered gaps (engine — found via exploratory/adversarial testing, June 2026)

**[engine-110] `ServiceKeyRegistry` stale-key mapping + unguarded YAML parsing — Implemented**
- Found while adversarially fuzzing `auth/registry.py` for `engine#SPEC-062826-1924`: re-registering a
  service with a rotated key left the old key live in `_key_to_name`; malformed YAML / a non-mapping
  `services` value raised uncaught instead of degrading like `discover_into`
- Fixed in the same change (`_register_key()` helper; `isinstance` guards + `try/except yaml.YAMLError`
  in `load_yaml`); regression-locked by `formal/models/test_auth_registry.py`
- Session log: `docs/exploratory-sessions/2026-06-28-service-key-registry-backfill.md`

**[engine-111] `AuthMiddleware` sibling-prefix bypass + substring permission carve-out — Implemented**
- Found while building the adversarial path-matching suite for `hive-conductor/backend/middleware/auth.py`
  (`engine#SPEC-062826-1924`): `_PUBLIC_PREFIXES`'s unguarded `startswith` let a sibling of
  `/v1/auth/login`/`/v1/auth/register` bypass auth entirely; `_required_permission`'s `"/invoke" in path`
  was a fail-open substring-anywhere check instead of a trailing-segment check
- Fixed in the same change (`_matches_public_prefix()` boundary helper + `_PUBLIC_EXACT` move;
  `path.endswith("/invoke")`); regression-locked by
  `packages/hive-conductor/backend/tests/test_auth_middleware.py`
- Session log: `docs/exploratory-sessions/2026-06-28-auth-middleware-backfill.md`

---

## Conductor variant items (`conductor-NNN`)

Single-tenant, multi-user self-hosted deployment — ships as `packages/hive-conductor`.

### v1.0 — multi-user with hard isolation + setup wizard

**[conductor-001] Setup wizard — Implemented — v1.0** — v1.0 critical path. Acceptance: < 30 min for new household

**[conductor-002] Per-user memory isolation — Implemented — v1.0** — Property test: cross-user retrieval is structurally impossible

**[conductor-003] Multi-user auth (Keycloak / JWT) — Implemented — v1.0** — Possible AuthX integration if not Keycloak (passes `engine#ADR-039` maintainer-signal gate)

**[conductor-004] Native install + Podman + systemd — Proposed — v1.0**

**[conductor-005] Tailscale-native networking — Proposed — v1.0**

**[conductor-006] Setup-wizard property test — Proposed — v1.0**

**[conductor-007] Per-user isolation property test — Implemented — v1.0**

### Documentation hygiene

**[conductor-090] Front-matter on mAIstro specs — Obsolete — v1.0 (warn-only)** — 91 specs; `S-NNN` → `SPEC-NNN` on touch

**[conductor-091] Memory specs `Substrate:` recast — Obsolete — v1.0 M3** — the legacy product specs → engine ADR substrate

**[conductor-092] Catalog specs `Substrate:` recast — Obsolete — v1.0 M3** — the legacy product specs → engine ADR substrate

**[conductor-095] Copier bootstrap — Proposed; `gap-impl` — v1.0 M2**

**[conductor-096] Adopt contract markers — Proposed — v1.0 M5** — `pytest.mark.contract` / `pytest.mark.scope` per ADR-032

### v1.1–v2.0 (mAIstro — original)

**[conductor-100] Voice + email + Alexa channels — Proposed — v1.1**

**[conductor-101] Hardware-signing integration — Proposed — v1.1** — (substrate `engine#ADR-022`)

**[conductor-102] Internal trust root — Proposed — v1.1** — (substrate `engine#ADR-026`)

**[conductor-103] DID/VC agent identity — Implemented — v1.1** — (substrate `engine#ADR-024`)

**[conductor-200] Hyperagent graph runtime — Implemented — v1.2** — Updated: substrate is `[engine-097]`

**[conductor-201] Node-graph designer (low-code) — Implemented — v1.2** — Built natively (`DagBuilder.tsx`); the Flowise service-bridge fallback is unnecessary

**[conductor-202] Human-as-node HITL primitive — Implemented — v1.2**

**[conductor-300] Cross-self portability for households — Proposed — v2.0** — If `[turing-080]` substrates cleanly

### NEW — from May 2026 catalog review (mAIstro)

**[conductor-150] Prediction-pool feature for Conductor-to-Conductor play — Proposed — v1.2**
- Two households' Conductors play prediction-pool games between their users
- Wraps `Khamel83/vig` (TypeScript / Cloudflare; service-boundary) OR reimplements as Python skill
- First user-facing exercise of cross-deployment A2A

**[conductor-151] Cross-deployment A2A test scenario — Proposed — v1.1**
- Friends/families across deployments; companion to `[conductor-150]`

**[conductor-400] Davinci-canvas backend expansion — Proposed; `gap-impl` — v1.1**
- `fal-mcp-server` (FLUX, SD, MusicGen) for generation
- `cli-anything-gimp` for editing (per `[engine-092]`)
- `cli-anything-libreoffice` for book-builder layout (Lulu integration)
- All service-boundary per `engine#ADR-039`

**[conductor-401] Davinci-canvas frontend completion — Proposed; `gap-impl` — v1.1**
- React + Express POC → production-shape
- Design tooling, asset library

---

## Autonoetic variant items (`turing-NNN`)

Continuity-of-self extensions — ship as `packages/maistro-turing`.

### v1.0 — measurable autonoesis

**[turing-001] HEXACO-24 + weekly retest — Proposed; `gap-impl` — v1.0 M1**

**[turing-002] Mood vector with decay + bounded delta — Proposed; `gap-impl` — v1.0 M1**

**[turing-003] Drive store with reinforcement and decay — Proposed; `gap-impl` — v1.0 M1**

**[turing-004] SelfModel/Mood/Drive ontology registration — Proposed; `gap-impl` — v1.0 M1** — Blocked-by: `[engine-030]`

**[turing-010] 7-tier memory implementation — Proposed; `gap-impl` — v1.0 M2** — Substrate: `[engine#ADR-016/017]`

**[turing-011] Weight floors REGRET (≥0.6) WISDOM (≥0.9) — Implemented — v1.0 M2**

**[turing-012] Activation graph with self-authored edges — Proposed; `gap-impl` — v1.0 M2**

**[turing-013] Todo → episode provenance enforcement — Proposed; `gap-impl` — v1.0 M2**

**[turing-020] Continuous self-talk loop — Accepted (spec); `gap-impl` — v1.0 M3**

**[turing-021] Awareness loop hz tunable — Proposed — v1.0 M3**

**[turing-022] Memory consolidation at idle — Accepted (spec); `gap-impl` — v1.0 M3**

**[turing-023] Dossier generation — Accepted (spec); `gap-impl` — v1.0 M3**

**[turing-030..034] Five property tests — Proposed — v1.0 M4**

**[turing-035] 30-day staging run (acceptance gate) — Proposed — v1.0 M4** — Depends on `[engine-032]`

**[turing-040] Reading-order docs aligned with template — Obsolete — v1.0 M5**

**[turing-041] Strip Stronghold-only content — Implemented — v1.0 M5** — Coordinated with `[sh-021]`

**[turing-043] Bootstrap into autonoetic Copier template — Proposed; `gap-impl` — v1.0 M5**

### Documentation hygiene (Turing)

**[turing-090] Front-matter on Turing specs — Obsolete — v1.0 (warn-only)**

**[turing-091] Memory specs `Substrate:` recast — Obsolete — v1.0 M3**

**[turing-092] Project Turing research consolidation — Obsolete — v1.0**

**[turing-095] Adopt contract markers — Proposed — v1.0 M5**

### v1.1–v2.0 (Turing)

**[turing-050] Lineage queries — Proposed — v1.1**

**[turing-051] Dream loop — Proposed — v1.1**

**[turing-052] Phantom execution — Proposed — v1.1**

**[turing-053] Adversarial hardening of self-model — Proposed — v1.1** — Uses `[engine-084]` chaos primitives if shipped

**[turing-060] `epic-13-hyperagents-meta-level` formalised — Proposed — v1.2**

**[turing-061] RASO inner cycle wired to self-talk — Proposed — v1.2**

**[turing-062] Tournament evolution scaffolding (internal-only) — Proposed — v1.2** — Substrate: `[engine-096]` data labeling

**[turing-070] Meta-agent that modifies activation graph — Proposed — v1.3**

**[turing-071] Parameter-sensitivity learner — Proposed — v1.3**

**[turing-072] Self-modification gate — Proposed — v1.3**

**[turing-080] Self-model export / import — Proposed — v2.0**

**[turing-081] Long-horizon recall with confidence calibration — Proposed — v2.0**

**[turing-082] Synthesised mood + drives from imported episodic record — Proposed — v2.0**

**[turing-083] Confidence-calibrated routing — Proposed — v2.0**

### Discovered gaps (Turing)

**[turing-100] HEXACO drift bound calibration — Proposed — v1.0 M1**

**[turing-101] Narrative recall idiom decision — Proposed — v1.0 M4**

**[turing-102] Sleep / off-hours behavior — Proposed — v1.x**

### Items deferred / abandoned (Turing)

**[turing-200] Production deployment — Abandoned**

**[turing-201] Multi-tenant Turing — Abandoned**

---

## Multi-tenant variant items (`sh-NNN`)

Hard-isolation enterprise deployment — planned downstream product (Stronghold).

Full v1.0 detail in [`stronghold/ROADMAP-v1.0.md`](https://github.com/agent-stronghold/stronghold/blob/main/ROADMAP-v1.0.md).

### v1.0 — compliance-first

**[sh-001] Multi-tenant catalog wrapper — Proposed; `gap-impl` — v1.0 W1** — Wraps engine simple form per `[engine#ADR-035]`

**[sh-002] Tenant-scoped namespacing — Proposed — v1.0 W1**

**[sh-003] Cross-tenant catalog import (with consent) — Proposed — v1.0 W1**

**[sh-010] OPA / Rego policy adapter — Proposed; `gap-impl` — v1.0 W2** — Hot-reload, < 1ms p99 at 1000 RPS

**[sh-011] Cedar policy adapter — Proposed; `gap-impl` — v1.0 W2**

**[sh-012] Sentinel policy bridge — Proposed — v1.0 W2**

**[sh-021] Absorb stronghold-only content from the upstream strip — Proposed — v1.0 W3**

**[sh-030] COMPLIANCE.md OWASP Agentic Top 10 — Implemented — v1.0 W4** — AT-10 anchored to `[engine#ADR-039]`

**[sh-031] COMPLIANCE.md NIST AI RMF stub — Implemented — v1.0 W4**

**[sh-032] COMPLIANCE.md EU AI Act stub — Implemented — v1.0 W4**

**[sh-040] Two-tenant red-team CI — Proposed; `gap-impl` — v1.0 W5**

**[sh-050] On-prem (OKD) + cloud (AKS) parity — Proposed; `gap-impl` — v1.0 W6**

**[sh-060] Append-only audit chain — Proposed; `gap-impl` — v1.0 W7**

**[sh-070] v1.0 acceptance suite green — Proposed — v1.0 W8**

**[sh-080] Bootstrap into multi-tenant Copier template — Proposed; `gap-impl` — v1.0 W8** — Blocked-by: `[engine-012]`

### Documentation hygiene (Stronghold)

**[sh-090] Front-matter on Stronghold specs — Proposed; `gap-spec` — v1.0 (warn-only)**

**[sh-095] Adopt contract markers — Proposed — v1.0 M5**

### v1.1–v2.0 (Stronghold — original)

**[sh-100] Trust-tier auto-promotion gates — Proposed — v1.1**

**[sh-101] Forge iteration loop (stronghold side) — Proposed — v1.1** — Wires `[engine-051]`

**[sh-102] Tournament evolution wired to internal-only routing — Proposed — v1.1** — Substrate: `[engine-096]` data labeling

**[sh-200] Forge test→iterate loop — Proposed — v1.2**

**[sh-201] Memory decay function in learnings — Proposed — v1.2**

**[sh-300] Agent marketplace — Proposed — v1.3**

**[sh-301] Multi-region failover — Proposed — v1.3**

**[sh-400] SOC 2 Type II audit — Proposed — v2.0**

**[sh-401] ISO 27001 readiness — Proposed — v2.0**

**[sh-402] Sectoral regulators (HIPAA, FedRAMP) — Proposed — v2.0**

### Discovered gaps (Stronghold)

**[sh-500] Policy evaluation latency under load — Proposed — v1.0 W2**

**[sh-502] Cross-tenant catalog consent flow design — Proposed — v1.0 W1**

**[sh-503] OWASP Agentic Top 10 evidence completeness — Proposed — v1.0 W4**

### NEW — from May 2026 catalog review (Stronghold)

**[sh-600] CLI-Hub federation — Proposed; `gap-impl` — v1.1**
- Multi-tenant catalog ingests from `clianything.cc` (HKUDS) with tenant-scoped enable/disable + audit
- Substrate: `[engine#ADR-035]`, `[sh-001]`, `[engine-092]`

**[sh-601] Forge × CLI-Anything pairing — Proposed; `gap-impl` — v1.2**
- Forge invokes CLI-Anything when a skill request maps to existing software
- Output skills are source-derived, not LLM-confabulated
- Improves `[sh-200]` Forge test→iterate loop

**[sh-602] A2UI render layer for stronghold tenants — Proposed — v1.0 W4**
- Implements `[engine-090]` chat-UI integration contract for tenants
- Resolves Open WebUI 50-user attribution clause concern
- Substrate: `BlakeMatthews-dev/A2UI`, `[engine-090]`, `[engine-091]`

**[sh-603] Default skills bundle for tenants — Proposed; `gap-impl` — v1.0 W1**
- Inherits `[engine-095]` plus tenant-scoping + policy bindings
- Tier 1 + Tier 2 MCP servers federated per `[sh-600]`

**[sh-604] Promptfoo as eval-substrate CI tool — Proposed — v1.0 W5**
- Service-boundary tool per `engine#ADR-039`
- Complements Hypothesis property tests (`[sh-095]`) for prompt regression
- Strong fit for compliance-first v1.0 eval story

**[sh-605] Open Interpreter as sandboxed code execution — Proposed — v1.0 W2**
- Service-boundary candidate via MCP for stronghold sandbox isolation
- Alternative to building from scratch; passes `engine#ADR-039` maintainer-signal gate

---

## Maintenance

- This file is **hand-maintained and canonical**, and is edited by humans and by authorized
  agents. It is the single work-source of record until the database-backed backlog and its
  Conductor UI are live and verified; consumers read it through a stable adapter seam rather
  than parsing it inline
  ([#50](https://github.com/Agent-StrongHold/Project-mAIstro/issues/50)).
- IDs are stable. Items never get renumbered.
- When an item is shipped, mark `Implemented` and link the PR.
- When an item is no longer relevant, mark `Abandoned` with a one-line reason. Don't delete.
- `scripts/check-backlog-consistency.py` gates this file: every item must parse, its status and
  gap marker must appear in the legends above, and every ADR/SPEC it cites must exist. The
  vocabulary is read from the legends themselves, so a legend and its usage cannot drift apart.
- External-library decisions (which to import, which to service-boundary, which to pattern-reference, which to reject) follow `engine#ADR-039`.
