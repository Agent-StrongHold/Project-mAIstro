# Roadmap

One product in one monorepo. The shared substrate and every variant live here
together: a variant is a Copier template plus the packages it turns on, not a
separate repository. [`BACKLOG.md`](BACKLOG.md) is the item-level companion; the
substrate-vs-variant split is [`engine#ADR-019`](docs/adr/ADR-019-canonical-source-split.md).

## Item ID convention (per [`engine#ADR-031`](docs/adr/ADR-031-front-matter-and-registry.md))

Every roadmap and backlog item is tagged by the part of the product it belongs to:

| Prefix | Part | Concern |
|---|---|---|
| `engine-NNN` | Substrate | Shared runtime, canonical ADRs, Copier templates, registry CI |
| `conductor-NNN` | Conductor variant | Single-tenant multi-user self-hosting (`packages/hive-conductor`) |
| `turing-NNN` | Autonoetic variant | Continuity of self (`packages/maistro-turing`) |
| `sh-NNN` | Multi-tenant variant | Compliance + hard isolation (Stronghold, planned downstream) |

## The system at a glance

```
┌──────────────────────── maistro-engine (this monorepo) ────────────────────────┐
│                                                                                │
│  Substrate    packages/maistro-core · -server · -canvas · -evolve · -rsi       │
│               · -registry · -design · -bootstrap  +  docs/adr  +  templates/   │
│                                                                                │
│  ── variants, composed from that substrate ──────────────────────────────────  │
│                                                                                │
│  Conductor          packages/hive-conductor        templates/single-tenant-…   │
│  single-tenant      + maistro-core                                             │
│  multi-user                                                                    │
│                                                                                │
│  Autonoetic         packages/maistro-turing        templates/autonoetic        │
│  continuity of self + maistro-core                                             │
│                                                                                │
│  Multi-tenant       planned downstream build       templates/multi-tenant      │
│  isolation +        (Stronghold)                                               │
│  compliance                                                                    │
└────────────────────────────────────────────────────────────────────────────────┘
```

| Part | Role | Dominant constraint |
|---|---|---|
| Substrate | Shared runtime, canonical ADRs, Copier templates, registry CI | n/a (it is the substrate) |
| Conductor variant | Single-tenant secure multi-user deployment | **Ease of self-hosting** |
| Autonoetic variant | Continuity-of-self extensions | **Continuity of self** |
| Multi-tenant variant | Enterprise deployment (planned downstream) | **Multi-tenant isolation** |

## Horizons

- **v1.0** — 3 months. Each variant reaches its MVP; substrate code parity reached.
- **v1.1–1.3** — 3–12 months. Hardening and inventory drainage.
- **v2.0** — 12 months. Inventory-clear: every accepted ADR/spec is `Implemented`, `Superseded`, or `Abandoned`.

---

## v1.0 (3 months) — organised by phase

Phases A–D run sequentially-ish in the substrate. Phase E (per-variant v1.0) runs in parallel from week 1, gated by the substrate items it depends on. Phase F (contracts as the bar) ramps from week 6.

### Phase A — Foundation enforcement (weeks 1–4)

| Item | Part | Status | Detail |
|---|---|---|---|
| `[engine-001]` Registry CI tooling | substrate | Implemented | Front-matter validator + cross-repo link checker + registry generator + GitHub Action; warn-only → hard fail at day 30 |
| `[engine-002]` INVENTORY auto-regenerated | substrate | Proposed | Once `engine-001` lands, hand-edits to INVENTORY fail CI |
| `[engine-003]` Front-matter on existing engine ADRs | substrate | Implemented | ADRs 000–029 gain front-matter on touch (not bulk) |
| `[engine-004]` CONTRIBUTING.md and convention docs | substrate | Implemented | Author-facing summary of ADR-031/032/001 |
| `[turing-090]` Front-matter on Turing specs | autonoetic | Obsolete | 22 top-level + ~70 nested epic stories |
| `[sh-090]` Front-matter on Stronghold specs | multi-tenant | Proposed; warn-only | Mirror of Turing's spec set during transition; will diverge post-Copier |
| `[conductor-090]` Front-matter on mAIstro specs | conductor | Obsolete | 91 specs (`S-NNN` → `SPEC-NNN` on touch) |

### Phase B — Templates bootstrapped (weeks 2–6)

| Item | Part | Status | Detail |
|---|---|---|---|
| `[engine-010]` Copier template `single-tenant-multi-user` | substrate | Implemented | Default/alternate render and update evidence: `tests/templates/test_single_tenant_multi_user_renders.py` |
| `[engine-011]` Copier template `autonoetic` | substrate | Implemented | Default/alternate render and update evidence: `tests/templates/test_autonoetic_renders.py` |
| `[engine-012]` Copier template `multi-tenant` | substrate | Accepted; `gap-impl` | Knobs: `tenants_max`, `policy_engine`, `deploy_target`, `compliance_pack`. Round-trips against the multi-tenant variant |
| `[engine-013]` Two-stream release pipeline | substrate | Proposed | `pkg/v*` + `template/v*` tags |
| `[conductor-095]` Copier bootstrap | conductor | Proposed; `gap-impl` | `copier copy` against fresh dir; close diff over 1–2 PRs |
| `[turing-043]` Copier bootstrap | autonoetic | Proposed; `gap-impl` | Same pattern |
| `[sh-080]` Copier bootstrap | multi-tenant | Proposed; `gap-impl` | Same pattern |

### Phase C — Drift closure (weeks 3–7)

Resolves the inventory drift items flagged when the substrate was consolidated.

| Item | Part | Status | Detail |
|---|---|---|---|
| `[engine-021]` Memory spec dedup | substrate | Obsolete | Engine ADR-011…017 canonical; product specs become `Substrate:`-cited |
| `[turing-091]` Memory specs `Substrate:` recast | autonoetic | Obsolete | `turing-dossier`, `turing-memory-consolidator`, `turing-notebook-live-vault`, `turing-obsidian-store` |
| `[conductor-091]` Memory specs `Substrate:` recast | conductor | Obsolete | , , ,  |
| `[engine-022]` Catalog spec dedup | substrate | Obsolete | Engine simple form + stronghold multi-tenant variant per `[engine#ADR-035]` |
| `[conductor-092]` Catalog specs `Substrate:` recast | conductor | Obsolete | ,  cite engine ADR-006/009 |

### Phase D — Substrate code parity (weeks 4–9)

The three engine ADRs that closed `gap-spec` items (036/037/038) become `Implemented`.

| Item | Part | Status | Detail |
|---|---|---|---|
| `[engine-030]` Ontology Semantic facet | substrate | Implemented | Per `[engine#ADR-036]`. v1.0 ships Semantic only; Kinetic + Dynamic deferred to v2.0 |
| `[engine-031]` Observability primitives | substrate | Accepted; `gap-impl` | Per `[engine#ADR-037]`. 3 of 6 baseline metrics live (circuit state, security blocks, request duration); the rest await model/service_key/period label plumbing; spans + event topics open |
| `[engine-032]` Reliability primitives | substrate | Accepted; `gap-impl` | Per `[engine#ADR-038]`. All five primitives shipped (SLO error budgets landed as `maistro.resilience.slo`); throttle wiring to the router scarcity input outstanding |

### Phase E — Per-variant v1.0 (weeks 1–12, parallel to A–D)

Each variant has its own v1.0 acceptance gate; item detail lives in [`BACKLOG.md`](BACKLOG.md).

#### Conductor variant v1.0 — multi-user with hard isolation + setup wizard

Dominant constraint: ease of self-hosting. Ships as `packages/hive-conductor`.

| Item | Status | Detail |
|---|---|---|
| `[conductor-001]` Setup wizard | Implemented |v1.0 critical path |
| `[conductor-002]` Per-user memory isolation | Implemented | Hard boundary; cross-user retrieval impossible by construction |
| `[conductor-003]` Multi-user auth (Keycloak / JWT) | Implemented | , ,  |
| `[conductor-004]` Native install + Podman + systemd | Proposed | ,  |
| `[conductor-005]` Tailscale-native networking | Proposed |  |
| `[conductor-006]` Setup-wizard property test | Proposed | A new household can complete setup in < 30 min |
| `[conductor-007]` Per-user isolation property test | Implemented | Cross-user retrieval is structurally impossible |

#### Autonoetic variant v1.0 — measurable autonoesis

Dominant constraint: continuity of self. Ships as `packages/maistro-turing`.

| Item | Status | Detail |
|---|---|---|
| `[turing-001]` HEXACO-24 + weekly retest | Proposed | Drift bound ≤ 0.05 L₂ weekly |
| `[turing-002]` Mood vector with decay + bounded delta | Proposed | No NaN, no unbounded values |
| `[turing-003]` Drive store with reinforcement and decay | Proposed | Passions, hobbies, interests, skills, preferences |
| `[turing-004]` `SelfModel`, `Mood`, `Drive` ontology registration | Proposed | Depends on `engine-030` |
| `[turing-010]` 7-tier memory implementation | Proposed | OBSERVATION → WISDOM |
| `[turing-011]` Weight floors REGRET (≥0.6) WISDOM (≥0.9) | Implemented | Structurally unforgettable |
| `[turing-012]` Activation graph with self-authored edges | Proposed | The self authors edges |
| `[turing-013]` Todo → episode provenance enforcement | Proposed | Required at the data model |
| `[turing-020]` Continuous self-talk loop | Accepted; `gap-impl` | Spec exists; runnable sketch only |
| `[turing-021]` Awareness loop hz tunable | Proposed | Copier knob |
| `[turing-022]` Memory consolidation at idle | Accepted; `gap-impl` | `turing-memory-consolidator.yaml` |
| `[turing-023]` Dossier generation | Accepted; `gap-impl` | `turing-dossier.yaml` |
| `[turing-030]`…`[turing-034]` Five property tests | Proposed | Identity continuity, narrative consistency, decision provenance, mood plausibility, memory floor preservation |
| `[turing-035]` 30-day staging run | Proposed | All five property tests asserted; v1.0 acceptance gate |

#### Multi-tenant variant v1.0 — compliance-first

Dominant constraint: multi-tenant isolation. Planned downstream product (Stronghold).

| Item | Status | Detail |
|---|---|---|
| `[sh-001]` Multi-tenant catalog wrapper | Proposed; `gap-impl` | Wraps engine simple form per `[engine#ADR-035]` |
| `[sh-002]` Tenant-scoped namespacing for agents/skills/tools/recipes/MCP | Proposed | |
| `[sh-003]` Cross-tenant catalog import (with consent) | Proposed | OAuth-style consent; revocable |
| `[sh-010]` OPA / Rego policy adapter | Proposed; `gap-impl` | Hot-reload, < 1ms p99 at 1000 RPS |
| `[sh-011]` Cedar policy adapter | Proposed; `gap-impl` | Same |
| `[sh-012]` Sentinel policy bridge | Proposed | Existing path stays available |
| `[sh-030]` COMPLIANCE.md OWASP Agentic Top 10 | Implemented | Module + test citations per control; gap markers honest |
| `[sh-031]` COMPLIANCE.md NIST AI RMF stub | Implemented | Govern / Map / Measure / Manage |
| `[sh-032]` COMPLIANCE.md EU AI Act stub | Implemented | Articles 9–15, 17, 26 |
| `[sh-040]` Two-tenant red-team CI | Proposed; `gap-impl` | Hypothesis-driven cross-tenant probe gen |
| `[sh-050]` On-prem (OKD) + cloud (AKS) parity | Proposed; `gap-impl` | Same Helm + image set |
| `[sh-060]` Append-only audit chain (signed, hash-chained) | Proposed; `gap-impl` | Indefinite retention |

#### Substrate — distribution & frontend completion

Detail in `BACKLOG.md` `[engine-100]`–`[engine-105]`.

| Item | Status | Detail |
|---|---|---|
| `[engine-100]` Hosted curl installer + web wizard | Proposed | `get.sh`/`install.sh` already resolve a GitHub release and verify SHA256SUMS; only DNS/hosting is outstanding |
| `[engine-101]` GHCR image publishing pipeline | Implemented | Workflow ships (`release.yml`, push + cosign + SBOM); never exercised — no tag cut yet |
| `[engine-102]` Frontend completion vs. archived PRODUCT-SPEC | Proposed; `gap-impl` | Page-by-page coverage unverified |
| `[engine-103]` MCP server implementations | Proposed | Decide wrap-existing-tools vs. build-new |
| `[engine-104]` Port remaining legacy experimental features | Proposed | Shipped: Bouncer, Agent Factory, Spawner, Skill Forge, Message Board. Superseded: Heartbeat (replaced by `reactor.py`). Outstanding: APM, Red Team |
| `[engine-105]` Wire Master Orchestrator security gate + API dispatch | Accepted; `gap-impl` | J1–J5 shipped (`orchestrator/master.py`, `planner.py`; security gate tested); J6 (API dispatch) open |

### Phase F — Contracts as the bar (weeks 6–12)

Per [`engine#ADR-032`](docs/adr/ADR-032-contracts-as-acceptance-criteria.md). Mutation-testing kill rate is the v1.0 quality bar.

| Item | Part | Status | Detail |
|---|---|---|---|
| `[engine-040]` Pydantic boundary contracts on all public types | substrate | Proposed | ≥95% mutation kill rate |
| `[engine-041]` Hypothesis property tests on accepted behavioral ADRs | substrate | Proposed | ≥80% kill rate |
| `[engine-042]` Pact-style contracts on A2A + MCP edges | substrate | Proposed | ≥75% kill rate; tooling choice deferred to a separate ADR (`engine-080`) |
| `[engine-043]` Mutation-testing CI wiring | substrate | Proposed | Nightly + on-merge; not on every PR |
| `[turing-095]` Adopt contract markers | autonoetic | Proposed | `pytest.mark.contract` / `pytest.mark.scope` per ADR-032 |
| `[sh-095]` Adopt contract markers | multi-tenant | Proposed | Same |
| `[conductor-096]` Adopt contract markers | conductor | Proposed | Same |

---

## v1.1 (3–6 months) — hardening

| Item | Part | Status | Detail |
|---|---|---|---|
| `[engine-050]` Cross-product agent portability proof | substrate | Proposed | Export from mAIstro → import into stronghold tenant catalog without recoding |
| `[engine-051]` Forge iteration loop primitive | substrate | Proposed | Generalises stronghold's planned test→iterate loop |
| `[engine-052]` Compliance gap audit on accepted ADRs | substrate | Implemented | Feeds stronghold COMPLIANCE.md control claims |
| `[turing-050]` Lineage queries | autonoetic | Proposed | "What did you used to think about X?" returns a snapshot |
| `[turing-051]` Dream loop | autonoetic | Proposed | Offline replay + consolidation |
| `[turing-052]` Phantom execution | autonoetic | Proposed | The self can simulate a route without committing |
| `[turing-053]` Adversarial hardening of the self-model | autonoetic | Proposed | Probe for inconsistency or drift attacks |
| `[sh-100]` Trust-tier auto-promotion gates | multi-tenant | Proposed | Currently manual (`update_trust_tier`) |
| `[sh-101]` Forge iteration loop — stronghold side | multi-tenant | Proposed | Wires `engine-051` into Forge agent |
| `[sh-102]` Tournament evolution wired to internal-only routing | multi-tenant | Proposed | Production traffic in v2.0 |
| `[conductor-100]` Voice + email + Alexa channels | conductor | Proposed | … |
| `[conductor-101]` Hardware-signing integration | conductor | Proposed |  (substrate: `engine#ADR-022`) |

## v1.2 (6–9 months) — RASO inner loop + memory v2 if surfaced

| Item | Part | Status | Detail |
|---|---|---|---|
| `[engine-060]` Memory v2 (if a product surfaces a need) | substrate | Proposed | Engine ADR-led; products do not silently extend |
| `[engine-061]` DSPy-style task signatures evaluation | substrate | Proposed | Driver: `turing#epic-07` |
| `[engine-062]` Mid-session model switching primitive | substrate | Proposed | Driver: `turing#epic-10` |
| `[turing-060]` `epic-13-hyperagents-meta-level` formalised | autonoetic | Proposed | Turing-specific concrete |
| `[turing-061]` RASO inner cycle wired to self-talk | autonoetic | Proposed | Auditor→Mason→extract→store→track |
| `[turing-062]` Tournament evolution scaffolding (internal-only) | autonoetic | Proposed | |
| `[sh-200]` Forge test→iterate loop | multi-tenant | Proposed | |
| `[sh-201]` Memory decay function in learnings | multi-tenant | Proposed | Engine substrate likely |

## v1.3 (9–12 months) — RASO meta-agent + agent marketplace

| Item | Part | Status | Detail |
|---|---|---|---|
| `[turing-070]` Meta-agent that modifies activation graph | autonoetic | Proposed | Self-modifying graph; v1.0 property tests gate edits |
| `[turing-071]` Parameter-sensitivity learner | autonoetic | Proposed | Which knobs to turn by inches, which by leaps |
| `[turing-072]` Self-modification gate | autonoetic | Proposed | Property tests re-run after every meta-agent edit |
| `[sh-300]` Agent marketplace (cross-tenant catalog discovery) | multi-tenant | Proposed | |
| `[sh-301]` Multi-region failover | multi-tenant | Proposed | |

## v2.0 (12+ months) — inventory-clear

| Item | Part | Status | Detail |
|---|---|---|---|
| `[engine-070]` Ontology Kinetic facet | substrate | Proposed | Actions an entity exposes, with pre/post-condition contracts |
| `[engine-071]` Ontology Dynamic facet | substrate | Proposed | State transitions, version history, derivation lineage |
| `[engine-072]` Cross-tenant ontology sharing primitive | substrate | Proposed | Stronghold-driven |
| `[engine-073]` Tournament-based agent evolution wired to production routing | substrate | Proposed | Substrate piece |
| `[turing-080]` Self-model export / import | autonoetic | Proposed | Strongest test of autonoesis |
| `[turing-081]` Long-horizon recall with confidence calibration | autonoetic | Proposed | |
| `[turing-082]` Synthesised mood + drives from imported episodic record | autonoetic | Proposed | |
| `[turing-083]` Confidence-calibrated routing | autonoetic | Proposed | Substrate piece if it generalises |
| `[sh-400]` SOC 2 Type II audit | multi-tenant | Proposed | |
| `[sh-401]` ISO 27001 readiness | multi-tenant | Proposed | |
| `[sh-402]` Sectoral regulators (HIPAA, FedRAMP) | multi-tenant | Proposed | Per customer demand |
| `[conductor-300]` Cross-self portability for households | conductor | Proposed | If `turing-080` substrates cleanly |

---

## Cross-repo dependency graph (v1.0 critical path)

```
engine-001 (Registry CI)
    │
    ├─→ engine-002 (INVENTORY auto-regen)
    ├─→ engine-021 (Memory dedup)
    │       └─→ turing-091 + maistro-091 (Substrate recast)
    ├─→ engine-022 (Catalog dedup)
    │       └─→ maistro-092 (catalog Substrate recast)
    ├─→ turing-090 + sh-090 + maistro-090 (front-matter)
    └─→ (CI flips hard at day 30)

engine-010/011/012 (Copier templates)
    │
    ├─→ maistro-095 (bootstrap into single-tenant template)
    ├─→ turing-043 (bootstrap into autonoetic template)
    └─→ sh-080 (bootstrap into multi-tenant template)

engine-030 (Ontology)
    └─→ turing-004 (SelfModel/Mood/Drive ontology registration)

engine-031 (Observability)
    ├─→ turing-020 (self-talk loop instrumentation)
    └─→ sh-060 (audit chain)

engine-032 (Reliability)
    ├─→ turing-035 (30-day staging run stability)
    └─→ sh-050 (on-prem + cloud parity)

```

## Progress dashboard

Verified against the tree on 2026-08-21. Maintained by hand; `engine-002` would regenerate it from the registry.

```
Phase A Foundation enforcement      [x] ██████████ 100%   Registry CI landed and strict since 2026-07-27; all ADRs carry front-matter
Phase B Templates bootstrapped      [~] ███░░░░░░░  30%   Three templates scaffolded; documented knobs + round-trip CI outstanding
Phase C Drift closure                [x] ██████████ 100%   Engine ADRs canonical; the product-side spec items are obsolete (those specs are not in this repo)
Phase D Substrate code parity        [~] ███████░░░  70%   Ontology Semantic done; reliability 5/5 substrate (router throttle wiring pending); observability primitives + 3/6 baseline metrics
Phase E.conductor Conductor v1.0     [~] ███████░░░  70%   Setup wizard, per-user isolation (+property test), JWT auth, DID identity shipped
Phase E.turing  Autonoetic v1.0      [~] ████░░░░░░  40%   Trait/facet model, weight floors, provenance shipped; loops + property tests pending
Phase E.sh      Multi-tenant v1.0    [·] ░░░░░░░░░░   n/a  Planned downstream build; engine-level COMPLIANCE.md controls shipped
Phase F Contracts as the bar         [~] ███░░░░░░░  30%   Spec type + mutation testing in place; substrate adoption pending
```

Legend: `[x]` complete | `[~]` in progress | `[·]` not started

## Maintenance

- Items get appended; status changes happen in-place. IDs are stable; never renumbered.
- Once `engine-001` (registry CI) ships, ROADMAP and BACKLOG are regenerated from front-matter; hand-edits then fail CI.
