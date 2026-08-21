---
id: ADR-062226-674b
title: "Constant tunability ladder — config-backed defaults that mature toward locked constants"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-06-22
substrate:
  - maistro-engine#ADR-078
related:
  - maistro-engine#SPEC-240
  - maistro-engine#SPEC-248
  - maistro-engine#SPEC-062126-5d56
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-062226-674b: Constant tunability ladder

## Context

The codebase has accumulated many module-level numeric constants whose values were picked as
reasonable starting points rather than derived or proven optimal — feedback boost/drop
factors (`memory/episodic/tiers.py`), RLPHD cold-start theta parameters
(`security/sentinel/rlphd.py`), quota/rate limits, retry/backoff parameters, scoring weights,
and others scattered across subsystems. Today these are hardcoded Python constants: changing
one requires a code change and a deploy, and there is no record of which values were actually
tried in production or why a given value was chosen.

ADR-078 already specifies a `ConfigStore` for admin-editable configuration but it remains
partially implemented ("ConfigStore sketched, missing RBAC online-edit + export/restore").
This ADR is not about ADR-078's mechanism — it's about which constants should use it, and a
policy for how a constant's tunability should evolve as the team learns more about it.

## Decision

Every implementation-defined numeric constant (i.e., not derived from an ADR/SPEC invariant
such as ADR-016's `WEIGHT_BOUNDS` floors) follows a three-stage maturity ladder:

1. **Tunable.** The constant ships as a `ConfigStore`-backed value with a documented starting
   default. An admin can set it to any value within its type's declared range. This is the
   default state for any newly-introduced implementation-defined constant — SPECs should not
   hardcode a bare module constant when introducing one; they should specify it as a
   `ConfigStore` entry with a default.
2. **Enumerated.** Once production usage shows only a small, known-good set of values actually
   work (the rest cause regressions, instability, or are simply never used), narrow the type
   to an enum of the known-good values. The constant remains `ConfigStore`-backed and
   admin-visible, but the admin now picks from a closed set instead of a free-form value. This
   is a refinement, not a removal of control.
3. **Locked.** Once exactly one value is ever correct — no deployment has benefited from a
   different value, and no plausible future deployment would — the constant is removed from
   `ConfigStore` and hardcoded again as a plain module constant, no longer admin-visible. This
   is the only stage where control is actually withdrawn, and it should be rare: it represents
   a constant that turned out not to be a tuning knob at all, just an invariant that hadn't yet
   been proven as such.

A constant's stage is a property of *evidence*, not of how long it's existed: a constant moves
from Tunable to Enumerated/Locked only when there's a documented basis (production data, a
formal/property test, or an explicit ADR amendment) for narrowing it — never by default or by
guesswork, and never in the absence of supporting evidence just because no one has changed the
default yet.

This ADR does not mandate migrating every existing constant immediately. It sets the policy
new SPECs must follow when introducing implementation-defined constants, and gives existing
subsystems (memory decay/feedback rates, RLPHD theta schedule, quota limits, etc.) a documented
target to migrate toward as their own follow-up SPECs land.

## Consequences

### Positive
- Constants get a paper trail: why a default was chosen, what range was considered safe, and
  what evidence (if any) narrowed it.
- Admins can tune behavior per-deployment without code changes or redeploys, for any constant
  still in the Tunable or Enumerated stage.
- Prevents premature hardcoding of values nobody has actually validated as singular truths.

### Negative / Trade-offs
- Adds `ConfigStore` wiring overhead to every new implementation-defined constant, even ones
  that will likely never need tuning in practice.
- Requires ADR-078's `ConfigStore` (RBAC online-edit + export/restore) to actually be finished
  before this policy can be applied uniformly — until then, this ADR's ladder describes a
  target state, and constants stay as plain module constants in the interim.
- Risk of enum/lock decisions being made on insufficient evidence (e.g., "nobody changed it
  yet" mistaken for "nobody could benefit from changing it") — mitigated by requiring an
  explicit evidentiary basis before narrowing, not silence.

### Neutral
- Existing hardcoded constants are not required to migrate by this ADR alone; each subsystem's
  own follow-up SPEC (e.g. SPEC-062126-5d56 for memory decay/feedback constants) decides whether and
  when to adopt the ladder for its own constants.
