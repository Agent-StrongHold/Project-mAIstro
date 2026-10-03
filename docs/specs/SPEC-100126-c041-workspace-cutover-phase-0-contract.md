---
id: SPEC-100126-c041
title: "Workspace cutover Phase 0 contract — one principal, default-deny routes, typed client, durable audit, durable effects, packaged app, crash windows, store scope, aggregated scan"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-10-01
history:
  - status: Proposed
    date: 2026-10-01
substrate:
  - maistro-engine#ADR-019
implements:
  - maistro-engine#ADR-068
  - maistro-engine#ADR-081226-6e34
related:
  - maistro-engine#ADR-072726-0d6b
  - maistro-engine#ADR-092326-7ed7
  - maistro-engine#ADR-081226-6b46
  - maistro-engine#ADR-081226-a66b
supersedes: []
blocks: []
blocked-by: []
contracts: []      # kinds declared here once the P0 checks land their marked tests
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-100126-c041: Workspace cutover Phase 0 contract

- **Status:** Proposed
- **Date:** 2026-10-01
- **Plan:** [`docs/architecture/WORKSPACE-CUTOVER-PLAN.md`](../architecture/WORKSPACE-CUTOVER-PLAN.md), Phase 0 (P0.1–P0.9)
- **Issues:** #53, #373, #1048, #325, #804, #62, #364, #1037, #66. Epics #1046 (Adaptive Workspace) and #804 (Persistent Workspace Agent).
- **Technical Area:** identity, authorization, frontend contract, audit, capability effects, execution spine, store scope, Warden/Sentinel

## Context

The Workspace (#1046/#804) is the fourth attempt at a product surface. The
cutover plan's rule is *contract before surface*: no Workspace Home, Attention,
or Agent surface is built on the current route table, principal dict, or
hand-typed client until Phase 0 lands. Each Phase 0 item is an invariant with a
check that is red on `develop` when the plan was written, and the plan states
the acceptance criterion each owning issue closes on as an "AC text" line.

Those criteria lived only in the plan, which is a planning surface with no
registry front matter, so `scripts/check-ac-state.py` could not see them and no
`@pytest.mark.ac` marker could bind to them. This spec registers them, with
stable ids, so Phase 1 PRs can mark the P0 criteria they rely on (plan,
Phase 1: "an unproven marker with a reason is allowed; silence is not") and
the epics close when `check-ac-state` reports every criterion `reachable`,
never by keyword.

## Goals

- Give each Phase 0 criterion a stable `SPEC-100126-c041/AC-N` id the
  acceptance-state checker measures.
- Keep the plan's `AC-P1`..`AC-P9` labels as aliases, so existing references
  (`check-principal-identity.py`, `check-route-permissions.py`,
  `quality/route-permissions.json`, `ci.yml`) stay resolvable.
- Record the owning issue for each criterion.

## Non-goals

- **Implementing any Phase 0 check.** Each check lands in its owning issue's
  PR, red with a baseline first, then green.
- **Changing the plan.** The plan remains the design narrative; this document
  is the measurable contract it points to.
- **Deciding the prerequisites** the plan lists in §7 (durable effect ledger,
  flat-layout package name, Conductor persistence mechanism).

## Decision

### Id mapping

The checker reads `**AC-N**` ids with a numeric `N`, scoped by spec id. The
plan's `AC-Pn` maps to `AC-n` one to one:

| Plan label | Checker id | Plan section | Owning issue(s) |
| --- | --- | --- | --- |
| AC-P1 | `SPEC-100126-c041/AC-1` | P0.1 One principal | #53 |
| AC-P2 | `SPEC-100126-c041/AC-2` | P0.2 Default-deny route table | #53, #373 |
| AC-P3 | `SPEC-100126-c041/AC-3` | P0.3 Typed API contract | #1048 |
| AC-P4 | `SPEC-100126-c041/AC-4` | P0.4 One durable audit store | #53, #325 |
| AC-P5 | `SPEC-100126-c041/AC-5` | P0.5 Backend-selected effect context | #804 |
| AC-P6 | `SPEC-100126-c041/AC-6` | P0.6 The Workspace app is a package | §7 prerequisite B (unopened) |
| AC-P7 | `SPEC-100126-c041/AC-7` | P0.7 Crash-window invariants | #804 (#62 closed 2026-09-27 by #1618's kill-recovery evidence, which this criterion builds on) |
| AC-P8 | `SPEC-100126-c041/AC-8` | P0.8 Store-boundary scope | #364 |
| AC-P9 | `SPEC-100126-c041/AC-9` | P0.9 Aggregated inbound scan | #804, #66 (#1037 closed 2026-09-23 by #1555) |

A test proving a criterion carries `@pytest.mark.ac("SPEC-100126-c041/AC-N")`
and, once the criterion's module is known, the spec gains an `ac-modules`
anchor for it so the criterion can reach the `reachable` rung.

### AC-6 wording

P0.6 is the only Phase 0 item without an "AC text" line in the plan. AC-6 is
therefore stated from P0.6's own invariant and check, not invented: new
Workspace backend code lives in an importable package, and
`check-cross-package-imports.py` rejects a new top-level backend module outside
one.

## Acceptance criteria

Each id is stable for `@pytest.mark.ac` marking by the PR that proves it. The
text is the plan's "AC text" line verbatim (AC-6 excepted, see above). None is
proven by this contract document: each is declared deliberately unproven here,
naming the issue that discharges it, and the PR that proves a criterion removes
its marker (per `check-ac-state.py --mandate`).

<!-- ac-state: unproven AC-1 - proven by #53 (P0.1 one principal; fitness test packages/maistro-core/tests/fitness/test_principal_identity.py ratchets quality/principal-identity-baseline.json to zero) -->
- **AC-1** (AC-P1, #53): every authenticated request in maistro-server,
  hive-conductor and the Turing backend yields one `maistro.identity.Principal`;
  no handler reads a dict-shaped user; the fitness ledger is empty.
<!-- ac-state: unproven AC-2 - proven by #53 / #373 (P0.2 default-deny route table; quality/route-permissions.json under check-route-permissions.py) -->
- **AC-2** (AC-P2, #53 / #373): `check-route-permissions.py` proves every
  registered Conductor route is either scoped, public-by-declaration (via
  `quality/public-routes.json`), or exempt-by-declaration (via
  `quality/route-permissions.json`); an undeclared route fails CI;
  `PrivilegeMiddleware` is deleted or enforces its table.
<!-- ac-state: unproven AC-3 - proven by #1048 (P0.3 generated types.gen.ts and one client; raw-fetch and hand-typed-entity ledgers) -->
- **AC-3** (AC-P3, #1048): Workspace Home and every surface it composes import
  backend entity types only from `types.gen.ts` and call only the generated
  client; the raw-fetch and hand-typed-entity ledgers are empty.
<!-- ac-state: unproven AC-4 - proven by #53 / #325 (P0.4 one durable audit store; packages/hive-conductor/backend/tests/test_audit_convergence.py) -->
- **AC-4** (AC-P4, #53 / #325): `GET /v1/audit` is served from the core audit
  store; `log_audit` is a thin adapter over it; auth and HITL events are
  present after restart.
<!-- ac-state: unproven AC-5 - proven by #804 (P0.5 backend-selected effect context; blocked on the durable Binding/Invocation/Approval stores, plan prerequisite A) -->
- **AC-5** (AC-P5, #804): a Workspace Agent Invocation survives process
  restart and is visible from a second replica; the approval it requested is
  reused, not re-requested.
<!-- ac-state: unproven AC-6 - proven by the P0.6 check in scripts/check-cross-package-imports.py; owning issue is plan prerequisite B (flat-layout module collisions), not yet opened -->
- **AC-6** (AC-P6, plan prerequisite B): new Workspace backend code lives in an
  importable package (`hive_conductor/` or a new `maistro_workspace/`), never
  as new top-level `routes`, `config`, `middleware`, `main`, `state` modules;
  `scripts/check-cross-package-imports.py` rejects a new top-level module under
  `packages/*/backend/` that is not inside a package with `__init__.py`.
<!-- ac-state: unproven AC-7 - proven by #804 (P0.7 RUNNING-run recovery sweep plus one crash-injection test per window) -->
- **AC-7** (AC-P7, #804): a process killed at any of the four named
  points leaves a Run that the next recovery tick settles or resumes; no Run is
  RUNNING with no live Attempt after one tick.
<!-- ac-state: unproven AC-8 - proven by #364 (P0.8 store-boundary scope conformance per store on real PostgreSQL; retained SQLite/in-memory legs are explicit fixtures) -->
- **AC-8** (AC-P8, #364): workspaces, projects, runs and audit each have a
  store-boundary scope test; `actor_principal_id` is required and validated at
  admission; audit rows carry and filter by `org_id`.
<!-- ac-state: unproven AC-9 - proven by #804 / #66 (P0.9 aggregated-context Warden boundary test, evasion cases, armed Sentinel permission table) -->
- **AC-9** (AC-P9, #804 / #66): the Workspace Agent's inbound scan covers the
  aggregated turn context after normalization; the three reproduced evasions
  are detected; the Sentinel permission table is armed in every supported
  profile.

## Testing

Each criterion is proven by the check its plan section names (P0.1–P0.9,
"Check."), marked `@pytest.mark.ac("SPEC-100126-c041/AC-N")`, and measured by
`scripts/check-ac-state.py --run-tests`. A criterion leaves `declared` only
through a marked test; it reaches `reachable` only once this spec carries an
`ac-modules` anchor the reachability graph resolves.

## Open questions (decided before this spec leaves Proposed)

- **Q1 — AC-6 owner:** which issue owns P0.6 once the plan's §7 prerequisite B
  (flat-layout module collisions) is opened.
- **Q2 — module anchors:** the `ac-modules` identity each criterion asserts
  about (e.g. `maistro.identity.principal` for AC-1), added by the PR that
  proves it rather than guessed here.

## References

- [WORKSPACE-CUTOVER-PLAN.md](../architecture/WORKSPACE-CUTOVER-PLAN.md) — Phase 0, §6 guards, §8 order of operations
- [ADR-068](../adr/ADR-068-unified-authorization-and-elevation.md) — unified authorization and elevation (AC-1, AC-2, AC-4, AC-9)
- [ADR-081226-6e34](../adr/ADR-081226-6e34-hierarchical-permissions.md) — scoped grants, deny-wins (AC-2, AC-8)
- [ADR-072726-0d6b](../adr/ADR-072726-0d6b-sentinel-permission-table-fail-closed.md) — Sentinel fail-closed (AC-9)
- [ADR-092326-7ed7](../adr/ADR-092326-7ed7-workspace-agent-identity.md) — Workspace Agent identity (AC-5, AC-9)
