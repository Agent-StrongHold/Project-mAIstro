---
id: SPEC-082926-f1c3
title: The reachability baseline is written in module identities
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
  - maistro-engine#ADR-082526-aef8
implements:
  - maistro-engine#ADR-082526-aef8
related:
  - maistro-engine#ADR-082226-ff3c
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_reachability_baseline_identity.py
source:
  - scripts/check-reachability.py
ac-modules:
  AC-1: '@tool/check-reachability'
  AC-2: '@tool/check-reachability'
  AC-3: '@tool/check-reachability'
  AC-4: '@tool/check_ac_state_impl'
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-f1c3: The reachability baseline is written in module identities

## Context

`check-reachability.py` walks production code and produces a **scoped module
identity** for everything it finds: `maistro.builders.runtime` for a package
module, `@flat/hive-conductor/routes.projects` for a module in a flat app,
`@tool/ac_state_notes` for a repo script. It then renders each identity into a
**report label** — the thing a person reads and greps for — before writing the
unreachable set out:

```python
unreachable = sorted(_display_name(key, flat_apps) for key in set(mods) - seen)
```

`quality/reachability-baseline.json` therefore stored labels, and the ratchet
compared labels to labels. Self-consistent, and for two years nobody had cause
to look: the labels *are* the better name for a human, and no other reader
existed.

SPEC-082926-c2d7 created that other reader. It made an `ac-modules` anchor
**required** to resolve to an identity, so that a criterion cannot claim the
`reachable` rung by naming something the graph has never heard of. The rung is
then decided by `check_ac_state_impl._is_reachable`, which looks that identity
up in this baseline:

```python
return not any(".".join(parts[: i + 1]) in unreachable for i in range(len(parts)))
```

Two spellings, one lookup, and **absence reads as reachable**. Forty of the 187
baseline entries were labels rather than identities:

| stored (label) | produced (identity) |
|---|---|
| `services.canonical_corpus` | `@flat/hive-conductor/services.canonical_corpus` |
| `routes.projects` | `@flat/hive-conductor/routes.projects` |
| `middleware.privilege` | `@flat/hive-conductor/middleware.privilege` |
| `scripts/ac_state_notes.py` | `@tool/ac_state_notes` |

A criterion anchored — correctly, as c2d7 now demands — to
`@flat/hive-conductor/services.canonical_corpus` asks a baseline that spells it
`services.canonical_corpus`, gets "not listed", and clears the top rung for a
module that is *in the baseline as unreachable*. `design_coverage` is derived
from those rungs and enforced as a floor, so the merge button is trusted
against a number inflated by a name mismatch.

This is the same shape of fault the ledger it feeds was built to catch, one
level down: a gate confirming its own spelling rather than the property it
stands for.

## Decision

**One canonical form in storage; labels at the edges that print them.**

`unreachable_modules()` returns identities. `display_name()` renders one for a
reader. The forty stray entries are rewritten in
`quality/reachability-baseline.json` and, because it is required to stay 1:1
with the baseline, in `quality/reachability-dispositions.json`.

`check-convergence-matrix.py` translates identities to labels **on read**. Its
Modules column is written in the prefixes a person types — `services`,
`routes`, `scripts` — and its census subtracts the unreachable set from the
module set. Leaving the baseline in identity form there would have silently
emptied the unreachable share ADR-082526-aef8's census derives.

`check-reachability.py` fails on any baseline entry it cannot resolve. The two
ways an entry can fail to resolve take **opposite** fixes and are reported
apart: an entry that is some module's report label is a live module written the
wrong way, and the message names the identity to rename it to; an entry
matching nothing at all is a phantom, and the message says to delete it. An
unresolvable entry never matches and never retires, so it is a hole in the
ratchet, not a stricter one.

**The ratchet's own report does not regress.** A newly-unreachable module is
still announced by the label a person can grep for, with the identity beside it
so the baseline line can be written without consulting this document.

## Measured effect

No verdict moved. 1010 modules and the same 187 unreachable before and after —
the rewritten set is provably equal to the identity set — and
`check-convergence-matrix.py --census` output is **byte-identical**.

Stated plainly rather than implied as a recovered number: what this buys is not
a corrected measurement today but a lookup that cannot silently miss tomorrow.
Before it, the forty modules were unreachable *and* unfindable by the gate that
grades them, and any criterion anchored to one of them would have been graded
`reachable`. The corpus happened not to anchor to any of the forty yet;
SPEC-082926-c2d7 made anchoring to them the correct thing to do.

**One existing test did anchor to one, and it caught the change.**
`TestToolingReachesTheTopRung::test_the_real_ledger_agrees_with_both` asks the
committed baseline whether `scripts/mutation_ratchet.py` — a dead script behind
a disabled workflow — grades below `reachable`. It answered `passing` for as
long as both sides said `scripts/mutation_ratchet.py`, and answered `reachable`
the moment the baseline said `@tool/mutation_ratchet`. That test is the defect
stated as the grade it produced: a class whose whole purpose is to pin *both*
directions, written in the spelling that made the wrong direction invisible.
Its case analysis moves to identities here, and `ADR-082526-aef8/AC-6` — which
it proves — returns to `reachable`.

## Consequences

### Positive
- The `reachable` rung and the reachability ratchet name modules the same way,
  so a criterion anchored to a baselined-unreachable module reports `passing`.
- An entry the walk cannot resolve fails, with the fix named — so the baseline
  cannot re-acquire strays the way it acquired these forty.
- The dispositions ledger, which must mirror the baseline, mirrors identities.

### Negative / Trade-offs
- Baseline entries are longer and less obvious to read than the labels they
  replace. The gate's report keeps the label, and prints the identity next to
  it, so nobody has to derive one from the other.
- `check-convergence-matrix.py` now imports `check-reachability.py` for
  `display_name` where it previously read the file alone. That coupling is the
  point: one definition of the mapping, used in both directions.

### Neutral
- No change to how reachability itself is computed, nor to the matrix's
  human-facing Modules column.

## Acceptance Criteria

```gherkin
Feature: The reachability baseline is written in module identities

  @AC-1
  Scenario: Every baseline entry is an identity the walk produces
    Given the committed reachability baseline
    When each entry is looked up in the module universe
    Then every entry resolves

  @AC-1
  Scenario: The scoped forms are present, not their labels
    Given the committed reachability baseline
    When it is read
    Then it holds flat-app and tooling identities
    And it holds none of their report labels

  @AC-2
  Scenario: A baseline entry that is a report label fails the gate
    Given a baseline entry written as some module's report label
    When the reachability gate runs
    Then it fails
    And the message names the identity to rename it to

  @AC-2
  Scenario: A baseline entry naming nothing at all fails the gate
    Given a baseline entry matching no module and no report label
    When the reachability gate runs
    Then it fails
    And the message says to delete it

  @AC-2
  Scenario: An unresolvable entry is not also called newly reachable
    Given a baseline entry the walk cannot resolve
    When the reachability gate runs
    Then it is reported as unresolvable
    And it is not listed among the modules that became reachable

  @AC-3
  Scenario: The rewrite moves no module's verdict
    Given the baseline as identities
    When the reachability gate runs against the tree
    Then the unreachable set is unchanged
    And the convergence census reports the same unreachable share

  @AC-4
  Scenario: A criterion anchored to a baselined module is not called reachable
    Given a criterion anchored to a module the baseline lists as unreachable
    When its rung is computed
    Then it reports passing rather than reachable
```
