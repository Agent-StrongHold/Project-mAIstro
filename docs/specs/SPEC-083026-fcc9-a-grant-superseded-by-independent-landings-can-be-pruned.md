---
id: SPEC-083026-fcc9
title: "A grant independent landings have durably superseded can be pruned"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-30
accepted: 2026-08-30
implemented: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
  - status: AC Defined
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-082926-25a2
implements:
  - maistro-engine#ADR-082926-25a2
related:
  - maistro-engine#SPEC-082926-6f49
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_ac_state_authorized_floor.py
source:
  - scripts/check_ac_state_impl.py
ac-modules:
  AC-1: '@tool/check_ac_state_impl'
  AC-2: '@tool/check_ac_state_impl'
  AC-3: '@tool/check_ac_state_impl'
  AC-4: '@tool/check_ac_state_impl'
  AC-5: '@tool/check_ac_state_impl'
  AC-6: '@tool/check_ac_state_impl'
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-fcc9: A grant independent landings have durably superseded can be pruned

## Context

`SPEC-082926-6f49` gave `design_coverage` a floor-lowering grant so a
methodology correction (#631/#662) could beat a stale, over-counted merged
note without `ac_state_notes.fold`'s `max` reasserting it. That spec names its
own accepted trade-off in "Consequences / Negative":

> A grant persists after the fall lands, because the fold still holds the old
> note's higher value... It is pruned when the notes themselves fold to its
> value or below, which `_stale_grants` enforces.

That release condition assumes the fold eventually falls back toward the
grant. It does not hold for a counter that only rises: `design_coverage`'s
one legitimate fall was the correction itself; every note since has measured
honestly, post-correction, and the fold has done nothing but grow. Verified
against `develop` on 2026-08-30: a grant at `27.8791` (#631/#662), a raw fold
of `31.7134`, and nineteen independently-merged notes — none of them the note
the grant corrects — each individually above the grant on their own.

The consequence `_removed_binding_grants` was built to prevent
(`SPEC-082926-6f49` AC-8) fires unconditionally whenever the base fold sits
above the floor, which by construction is now every future base:

```python
if counter in counters and counters[counter] > floor and present.get(counter) != floor
```

`counters` is the base's own raw fold — untouched by whatever a candidate
measures or bank — so this is true of every PR from now on, regardless of its
diff. `_stale_grants` fires on the opposite condition and, for the same
reason, can never fire again. The two conditions are complementary by
`SPEC-082926-6f49`'s own design (`AC-9`'s test class documents this exact
deadlock for the prior instance of it), so once a floored counter's honest
growth outpaces a grant this durably, **no PR, however constructed, can ever
remove that grant** under the existing rules. Observed three times in one
afternoon: `#713`, `#715`, and `#720` each independently hit "unbanked
improvement" against the same un-prunable grant, though none of their diffs
touched anything the grant corrects.

## Goals

- A grant whose correction is no longer what holds the floor up can be
  pruned, without weakening the self-approval guard `SPEC-082926-6f49`
  AC-3/AC-8 exist to keep.
- The signal must not be manufacturable by the change that benefits from it:
  one contributor, one PR, contributes at most one note.
- No change to a grant that is still doing the work `SPEC-082926-6f49`
  describes — a floor sitting near a fold a single or a few merged notes
  still prop up.

## Non-goals

- Making every "unbanked improvement" fail self-resolving. The ordinary case
  — this branch's own measurement is fresh and simply needs `--bank` — is
  unchanged and still needs it.
- Auto-pruning. This spec makes a superseded grant *removable* by a reviewed
  change; it does not remove one on its own.
- Metric-version invalidation (`ratchet_provenance.require_metric_version`),
  which `SPEC-082926-6f49`'s own "Alternative considered" already rejected
  for discarding every counter in every older note, not just the one in
  question.

## Decision

A grant is **superseded** for a floored counter when at least
`MIN_SUPERSEDING_NOTES` (3) notes at the base revision *individually* — not
via the fold's `max` — carry a value for that counter above the grant. Three
is deliberate: a single contributor can add at most one note per PR, so this
cannot be satisfied by the change that wants to prune it, or by any run of
PRs from one author; it takes that many separately-reviewed landings, each
already trusted enough to merge, independently agreeing the floor no longer
describes the repository.

```python
def _superseded_grants(notes: list[Note], floors: dict[str, float]) -> dict[str, list[str]]:
    ...  # counter -> the note names that, on their own, clear its floor
```

Computed from `notes` at the base revision — the same source `floors` itself
comes from — so it answers a base question exactly like permission does, and
carries the same self-approval guarantee: nothing the candidate does can
manufacture supersession, only what is already merged and reviewed can.

**Two call sites, two readings of the file, matching `SPEC-082926-6f49`'s own
split.** `superseded_by_floor` (against `authorized_floors`, the base's file)
answers `_removed_binding_grants`'s question — "is the grant this change
spends still needed" — and gates whether removal is refused. `superseded_by_present`
(against `candidate_grants`, this tree's file) answers what
`_report_superseded_grants` reports — "is a grant still sitting in the file
after independent work overtook it" — and gates the run exactly the way
`_stale_grants` already gates a spent one. They agree except in the one run
that prunes, where `superseded_by_present` is correctly empty: there is
nothing left in the candidate's own file to report on.

**The comparison itself excludes a superseded grant, not only the removal
refusal.** Without this, the one PR that prunes the grant would still measure
against the un-pruned floor for want of a fresh note of its own — the exact
shape `SPEC-082926-6f49`'s AC-12 closed for the ordinary case, reopened here
because supersession is a new way for a grant to stop mattering. `floors`
filtered to exclude superseded counters (`effective_floors`) feeds both the
regression comparison (`_lowered(bound.counters, effective_floors)`) and
`_exact_target`. This is not the candidate loosening its own bound: supersession
is computed from the base's history alone, so every PR against the same base
computes the identical answer, independent of anything it itself contributes.

**`_removed_binding_grants` gains one exclusion, nothing else.** A binding
grant this change also deletes still refuses — *unless* it is superseded, in
which case removing it is exactly the maintenance this spec exists to permit.

## Acceptance criteria

```gherkin
Feature: A grant independent landings have durably superseded can be pruned

  @AC-1
  Scenario: One note above the floor does not supersede a grant
    Given a grant with only the ordinary "unbanked improvement" case against it
    When fewer than three already-merged notes individually clear the floor
    Then the grant is not reported as superseded
    And removing it while it is still binding is still refused

  @AC-2
  Scenario: Three independent already-merged notes supersede a grant
    Given at least three already-merged notes, none the note the grant corrects, each individually above it
    When the ratchet runs with the grant still present in the candidate file
    Then the run fails
    And the failure names the grant and the notes that superseded it

  @AC-3
  Scenario: A superseded grant may be pruned
    Given a grant superseded by three or more independent notes
    When a change removes it from the authorization file
    Then `_removed_binding_grants` does not refuse the removal
    And the run passes if nothing else fails

  @AC-4
  Scenario: Pruning a superseded grant does not require a fresh note
    Given a grant superseded by three or more independent notes
    When a change removes it and measures the unclamped fold exactly, banking nothing new
    Then the run passes

  @AC-5
  Scenario: Supersession cannot be manufactured by the candidate's own note
    Given a grant with only one or two already-merged notes above it
    When the candidate's own worktree note also clears the floor
    Then the grant is still not reported as superseded

  @AC-6
  Scenario: A grant still doing real work is unaffected
    Given a grant with no independent notes above it
    When the ratchet runs
    Then removing it while it is still binding is refused exactly as before
```

## Testing

`tests/test_ac_state_authorized_floor.py`, extending the existing
`repo`/`gate`/`_run` harness with a way to seed multiple independently-named
base notes (not only `_baseline`), since supersession is a property of *how
many separate notes* clear a floor, which a single-note fixture cannot
exercise. Each AC above gets one or more `@pytest.mark.ac` tests against a
real synthetic git repository, matching `SPEC-082926-6f49`'s own convention
of never testing this mechanism against a stub.

## Open questions

- `MIN_SUPERSEDING_NOTES = 3` is a judgment call, not derived from anything
  in the repository. Revisit if it proves too eager (a short run of related
  PRs retiring a correction that still matters) or too conservative (a
  genuinely dead grant blocking merges longer than it should).
- This spec only reaches floored counters, because only `design_coverage` is
  floored today and only floors can carry a grant at all
  (`_grant_floors` refuses a grant naming a debt ceiling). A ratcheted
  (debt) counter that someday gains grant support would need its own
  direction-appropriate reading of "superseded."

## References

- `maistro-engine#SPEC-082926-6f49` — the grant mechanism this extends.
- `#631`, `#662` — the correction the grant `27.8791` records.
- `#713`, `#715`, `#720` — three independent PRs the un-prunable grant blocked
  in one afternoon, none touching anything it corrects.
