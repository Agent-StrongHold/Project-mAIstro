---
id: ADR-092626-c1e7
title: "Workspace work campaigns are narrowing policy, not an owner of work"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-09-26
history:
  - status: Proposed
    date: 2026-09-26
substrate:
  - maistro-engine#ADR-019
implements: []
related:
  - maistro-engine#ADR-092326-7ed7
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-092626-c1e7: Workspace work campaigns are narrowing policy, not an owner of work

## Context

#103 asks for a way to steer ongoing, authorized Workspace work: narrow the
eligible pool, pin, pause or exclude items, set budgets, and keep explicit
human priority apart from the system's selection score. The persistent
Workspace Agent (#804, ADR-092326-7ed7) consumes it now and RSI (#50) later.

Nothing on `develop` defines a campaign. The nearest thing is the RSI-private
`maistro_rsi.trace_notes.read_campaign`, a git-notes reconstructor, which #50
says must not become the authority. Without a recorded boundary, the first
implementation could make a campaign a second scheduler, a Goal owner, or a
permission source, each of which would contradict the canonical ontology
(`docs/architecture/INTEROP-ONTOLOGY-v1.md`) and the M1 convergence freeze.

## Decision (proposed)

A campaign is versioned operator policy scoped to a Workspace or Project. It
only **narrows** which BacklogItems and linked canonical Goals an already
authorized actor may choose. It does not:

- grant permissions, capabilities or scope;
- own a Goal, reassign one, or copy Goal ownership or lifecycle into its own
  fields;
- schedule, lease or execute work, or add a lifecycle beside Goal and Run.

Every campaign, eligibility, selection and control decision is recorded with
the actor and the campaign's `policy_version`. The operator controls (pin-next,
pause, exclude, human-only) are durable records. RSI reuses the same contract
and keeps no private campaign model.

The contract, its autonomy modes and its acceptance criteria are in
SPEC-092626-1831. The priority combination rule, the default autonomy mode,
overlapping campaigns and the record's owning store are open there and are
decided before this ADR is accepted.

## Consequences

### Positive

- #804 and #50 share one campaign contract instead of growing two.
- Authorization and Goal ownership stay with their existing owners, so a
  campaign bug cannot widen access.

### Negative / Trade-offs

- A campaign cannot express "do this even though the actor is not authorized";
  that stays a permission change made elsewhere.
- Every decision carries audit fields, which adds write volume.

### Neutral

- Hard tenancy remains the importing product's concern (ADR-019).
