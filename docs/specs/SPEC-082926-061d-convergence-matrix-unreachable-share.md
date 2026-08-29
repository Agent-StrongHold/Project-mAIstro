---
id: SPEC-082926-061d
title: Convergence Matrix Unreachable Share
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
  - maistro-engine#ADR-082926-061d
implements:
  - maistro-engine#ADR-082926-061d
related:
  - maistro-engine#ADR-082526-aef8
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_check_convergence_matrix.py
source:
  - scripts/check-convergence-matrix.py
ac-modules:
  AC-1: @tool/check-convergence-matrix
  AC-2: @tool/check-reachability-dispositions
  AC-3: @tool/check-convergence-matrix
  AC-4: @tool/check-convergence-matrix
  AC-5: @tool/check-convergence-matrix
  AC-6: @tool/check-convergence-matrix
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-061d: Convergence Matrix Unreachable Share

- **Status:** Active
- **Decision:** ADR-082926-061d
- **Closes:** #605

## Scope

The `Unreachable` column of the disposition table in
`docs/architecture/CONVERGENCE-MATRIX.md`, and the part of
`scripts/check-convergence-matrix.py` that checks it.

Out of scope: the partition check, the ownership table and its `(unreachable)` /
`(planned)` / `(delegated)` annotations, the disposition vocabulary, the citation
check, `quality/reachability-baseline.json` and `quality/reachability-dispositions.json`.
None of those change.

## The share

The cell holds one word from a fixed vocabulary, in a code span:

| Word | Share of the subsystem's production modules that no entry point reaches |
|---|---|
| `none` | zero |
| `few` | greater than zero, at most one fifth |
| `some` | greater than one fifth, at most one half |
| `most` | greater than one half, but not all |
| `all` | every module (and the subsystem owns at least one) |

Boundaries are inclusive at the top: exactly 20% is `few`, exactly 50% is `some`.

## Where it comes from

Both inputs already exist and are already gated:

- the module set — `check-reachability.py`'s `_collect_modules()`, the same scan that
  decides what counts as a production module for the reachability ratchet;
- the unreachable set — the `unreachable` list in `quality/reachability-baseline.json`,
  the ledger `check-reachability.py` ratchets.

The matrix therefore cannot disagree with the reachability gate: there is one
measurement, read by two gates.

## The census

`python scripts/check-convergence-matrix.py --census` prints, per subsystem, the
unreachable count, the total, the share as a percentage, and the word. It is the
answer to "what is the exact number" and it is what the failure message points at.

## Acceptance Criteria

```gherkin
Feature: Convergence matrix unreachable share

  @AC-1
  Scenario: Two branches adding a module to one subsystem do not collide
    Given a matrix row whose subsystem holds some unreachable modules
    And two branches that each add one reached module to that subsystem
    When each branch is audited with the other's module also present
    Then the stated share is still correct for both
    And neither branch had to edit the row

  @AC-1
  Scenario: The old transcribed count would have failed the same pair
    Given the same subsystem and the same two added modules
    When the count is stated as unreachable-over-total
    Then the row is wrong for both branches

  @AC-2
  Scenario: An undispositioned unreachable module is still refused
    Given a subsystem that gains a module no entry point reaches
    And no disposition group naming it
    When the disposition ledger is audited
    Then it fails and names the module

  @AC-2
  Scenario: A dispositioned unreachable module is admitted
    Given the same module named by a disposition group
    When the disposition ledger is audited
    Then it passes

  @AC-3
  Scenario: The prose of the row is not derived
    Given a row whose disposition cell carries a hand-written rationale
    When the matrix is audited
    Then the rationale is read only for its verdict word and its citations

  @AC-4
  Scenario: The share is computed from the reachability data
    Given a module the reachability baseline lists as unreachable
    When the share is computed
    Then that module counts against its subsystem
    And no other source of truth is consulted

  @AC-5
  Scenario: The census reports the exact counts
    Given a subsystem with a known unreachable count and total
    When the census is rendered
    Then it names the subsystem, the count, the total, the percentage and the word

  @AC-6
  Scenario: A wrong share says what to do
    Given a row stating a share the code contradicts
    When the matrix is audited
    Then the failure names both words, the exact counts, and the census command

  @AC-6
  Scenario: A word outside the vocabulary is refused
    Given a row whose Unreachable cell holds an invented word
    When the matrix is audited
    Then the failure lists the five words that are allowed
```
