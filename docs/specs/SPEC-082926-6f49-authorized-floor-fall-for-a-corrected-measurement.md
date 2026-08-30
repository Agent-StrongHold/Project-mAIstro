---
id: SPEC-082926-6f49
title: A corrected measurement can lower an AC-state floor; a regression still cannot
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-29
accepted: 2026-08-29
history:
  - status: Proposed
    date: 2026-08-29
  - status: Accepted
    date: 2026-08-29
  - status: AC Defined
    date: 2026-08-29
substrate:
  - maistro-engine#ADR-082926-25a2
implements:
  - maistro-engine#ADR-082926-25a2
related:
  - maistro-engine#ADR-082226-ff3c
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
  AC-7: '@tool/check_ac_state_impl'
  AC-8: '@tool/check_ac_state_impl'
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-6f49: A corrected measurement can lower an AC-state floor; a regression still cannot

## Context

`design_coverage` is a floor. `ac_state_notes.fold` takes `max` across every
note, read at the base revision, so no branch can lower a floor another branch
established — the property ADR-082926-25a2 exists to hold.

Notes outlive the branches that wrote them. A merged branch's note therefore
holds the floor permanently, and `--bank` writes only the running branch's own
note. There is consequently **no way to say that a recorded number was wrong**.

That is not hypothetical. #631 makes an `ac-modules` anchor resolve; combined
with #651, `SPEC-082926-25a2`'s own seven criteria stop matching
`@tool/ac_state_notes` as absent and start matching it as baselined-unreachable:

```
ADR-082926-25a2  before: 7/7 reachable (100.0%)   after: 0/7 (0.0%)
```

`ac_state_notes.py` is loaded with `spec_from_file_location`, so the import
graph genuinely cannot reach it. Those seven criteria were graded `reachable`
on a module the reachability baseline lists as unreachable — the exact
over-count the top rung exists to prevent. Coverage falls 27.2395 → 26.4762,
**correctly**, and the floor blocking it is held by
`chatgpt-m1-335-pool-lifecycle-current.json`, a note from an already-merged
branch, recording a number the correction proves was never true.

The gate's own message says to "bank the fall with `--bank` and justify it in
the diff". Banking cannot do it: `max` keeps the higher note.

## Decision

A **grant** in `quality/ratchet-authorizations.json`, under the `ac-state`
ratchet, lowers one floor to one named value:

```json
{ "ac-state": { "design_coverage@26.4762": {
    "owner": "...", "issue": "#662", "reason": "..." } } }
```

`ratchet_provenance.load_authorizations` reads grants **at the base revision**,
so the change that lowers the floor cannot also be the change that permits it.
That is the whole point, and it is not a new property — it is the one the
helper already enforces for the wiring ratchet, reused rather than reinvented.

**The value is in the key.** A grant licenses one specific fall, to a stated
number, and not the next one. A bare `design_coverage` key would be an open
season on the floor for as long as it sat in the file.

**Both comparisons, including the one the merge queue makes.**
`check-ac-state.py` measures the actual base revision in a merge group and
compares it to the candidate independently of any note. That comparison has to
apply the same grant, or the fall passes every check on the branch and is then
rejected by the queue — working everywhere except the one place it has to work.

**Permission is a base question; bookkeeping is a candidate one.** They are
different questions and must be read from different revisions. Stale-ness read
from the base made pruning unfollowable: once the notes overtook a grant, every
later run failed on it, *including the run whose only change removed it*.
Conversely, a binding grant must still be present in the candidate — permission
is read at the base, so a change could otherwise spend a grant and delete it in
the same commit, landing the fall and leaving the next run with a number nobody
can account for.

**Only a floor moves, and only downward.** `min(folded, granted)`: a grant
naming a value the fold is already below raises nothing, and is reported stale
rather than silently ignored. A grant naming a debt ceiling is refused
outright — a ceiling is raised by banking, never by permission.

**The grant is the record.** Both comparisons fold with `max`, the worktree
one included, so a branch cannot *record* a lower value either: its own note at
26.4762 beside a `_baseline.json` at 27.2395 folds to 27.2395. Lowering only
the regression floor would leave the exact comparison demanding the number the
correction just disproved. The grant therefore carries the owner, the issue and
the reason — it is a better record than a note, being prose a reviewer reads
rather than a number in a file.

What the exact comparison still enforces is that the measurement **is** the
authorized value: below it is a regression the grant does not cover, above it
is slack that must be banked. A grant is not a floor a branch may sit anywhere
under.

### The alternative considered, and why not

Give notes a `metric_definition_version` and have `fold` ignore older ones —
the concept `ratchet_provenance.require_metric_version` already implements.

Rejected. A version bump discards **every** counter in every older note, not
just the one whose meaning changed: the ten debt ceilings would go with the
floor, and their values were never in question. It also empties the bound, and
an empty bound is a refusal here, so the first change after any bump could not
pass. A grant moves exactly the number under review and leaves the rest folding.

## Consequences

### Positive
- A measurement found to be over-counting can be corrected, which was
  previously impossible once any merged note recorded the inflated value.
- The unlock is prior, reviewable, and names an owner, an issue and a reason —
  the same shape as every other floor-raise in the repository.
- Nothing changes without a grant: with an empty `ac-state` section the gate
  behaves exactly as before.

### Negative / Trade-offs
- A grant persists after the fall lands, because the fold still holds the old
  note's higher value, so it keeps doing work rather than becoming inert
  immediately. It is pruned when the notes themselves fold to its value or
  below, which `_stale_grants` enforces rather than leaving to memory — read
  from the candidate file, so the pruning change is one that can actually pass.
- The authorization file is now read at two revisions, which is one more moving
  part than a single read. It is the minimum: a single revision either makes
  self-approval possible or makes pruning impossible, and neither is acceptable.
- A second reader of `ratchet-authorizations.json` means two ratchets now
  depend on its shape. That is the cost of not building a second grant file.

### Neutral
- No change to `fold`, to the notes' schema, or to how any counter is measured.

## Acceptance Criteria

```gherkin
Feature: A corrected measurement can lower an AC-state floor

  @AC-1
  Scenario: With no grant the floor is the fold, unchanged
    Given no ac-state grants at the base revision
    When the ratchet runs
    Then a measurement below the folded floor still fails

  @AC-2
  Scenario: A landed grant lowers the floor to the value it names
    Given a grant naming a floor below the folded one
    When the ratchet runs against a measurement at that value
    Then the fall is permitted
    And the run reports the authorized floor and its reason

  @AC-3
  Scenario: A grant written in the same change does not take effect
    Given a grant present in the worktree and absent at the base
    When the ratchet runs against a measurement the grant would permit
    Then the fall is still refused

  @AC-4
  Scenario: A grant may only lower, and a spent one must be pruned
    Given a grant naming a value at or above the folded floor
    When the ratchet runs
    Then the floor is not raised to it
    And the grant is reported as lowering nothing

  @AC-5
  Scenario: The authorized floor is a value, not a range
    Given a grant naming a floor
    When the measurement is above it
    Then the run fails as unbanked slack rather than passing

  @AC-6
  Scenario: A malformed grant is refused rather than ignored
    Given a grant naming a debt ceiling, omitting its value, or a malformed section
    When the ratchet runs
    Then the run fails and names what is wrong with the grant

  @AC-7
  Scenario: The comparison against the actual measured base honours the grant
    Given an authorized fall and a measurement of the actual base revision
    When the base and the candidate are compared
    Then the fall is not reported as a regression from that base

  @AC-8
  Scenario: A change may not spend a grant and delete it
    Given a landed grant that is lowering the floor for this change
    When the change also removes it from the authorization file
    Then the run fails and says the grant has to stay
```
