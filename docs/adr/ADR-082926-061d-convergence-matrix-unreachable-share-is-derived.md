---
id: ADR-082926-061d
title: "The convergence matrix states an unreachable share, not a transcribed count"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-29
accepted: 2026-08-29
history:
  - status: Proposed
    date: 2026-08-29
  - status: Accepted
    date: 2026-08-29
substrate:
  - maistro-engine#ADR-082526-aef8
implements: []
related:
  - maistro-engine#ADR-082226-ff3c
  - maistro-engine#ADR-082926-25a2
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_check_convergence_matrix.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082926-061d: The convergence matrix states an unreachable share, not a transcribed count

## Context

`docs/architecture/CONVERGENCE-MATRIX.md` carried a per-subsystem cell of the shape
`` `19/62` `` — unreachable modules over total production modules in that subsystem —
and `scripts/check-convergence-matrix.py` failed when a row disagreed with the code.

The denominator is the number of production modules in the subsystem. **Any pull
request that adds or removes a module anywhere invalidates that row for every other
open pull request**, on a line none of them wrote. Measured in one pass through the
queue on 2026-08-29: #536, #513, #496 and #589 each went red on
`test_the_shipped_matrix_matches_the_shipped_code` after unrelated work merged, and
#334, #333, #585 and #593 each needed a hand edit to a row whose subject they had not
touched. Each fix is a one-character edit that goes stale the moment the next pull
request merges — made under time pressure, on a file whose whole purpose is to
describe the architecture honestly.

This is the shape #208 named for `docs/testing/SUITE-INVENTORY.md` and #585 named for
`quality/ac-state*`:

> one narrative slot is rewritten by every PR

Both of those were fixed by splitting a hand-maintained aggregate into per-branch
notes and folding them at gate time. That mechanism is **rejected here**, and the
reason matters: a note exists to carry a measurement the gate cannot recompute — a
test count, a coverage figure that costs ten minutes of test time. The matrix's
count is not that. It is recomputed from the import graph on every single run, from
the same data `check-reachability.py` ratchets. There was never anything to fold;
there was only a number transcribed into a shared file by hand.

## Decision

The Unreachable cell states a **share**, from a fixed five-word vocabulary, and the
gate derives the share from the code:

| Word | Meaning |
|---|---|
| `none` | no module in the subsystem is unreachable |
| `few` | up to a fifth of them |
| `some` | up to half of them |
| `most` | more than half, but not all |
| `all` | every module in the subsystem |

The share is computed from `_collect_modules()` — the same scan `check-reachability.py`
uses to decide what a production module is — and the `unreachable` set in
`quality/reachability-baseline.json`, which is the set that gate already ratchets. The
matrix and the reachability gate therefore cannot disagree: there is one measurement,
read twice.

`scripts/check-convergence-matrix.py --census` prints the exact per-subsystem counts,
shares and words. The gate's failure message names that command.

Three things do **not** change:

- The partition check. Every production module still belongs to exactly one subsystem,
  longest prefix wins, and an unclassified module still fails by name.
- The disposition requirement. An unreachable module with no group in
  `quality/reachability-dispositions.json` still fails `check-reachability-dispositions.py`.
- The prose. Dispositions, ownership claims and the `(unreachable)`/`(planned)`/
  `(delegated)` annotations #378 added stay hand-written and reviewed.

## Consequences

### Positive
- Two pull requests that each add a module to the same subsystem no longer edit the
  same line, so they neither conflict in git nor redden each other in CI.
- The number a reader sees can no longer be stale in the direction that matters: it is
  recomputed, not transcribed, so a wrong share is a wrong *word*, which a reviewer can
  argue with.
- The exact counts are still available, and are now reproducible in one command rather
  than by reading a line someone typed.

### Negative / Trade-offs
- A reader of the raw markdown sees `some` where they used to see `19/62`. The exact
  figure costs one command. This is the deliberate trade: the precise number was
  precise and wrong roughly once per merge.
- A small subsystem can still cross a boundary on a single addition — a seven-module
  subsystem at `4/7` becomes `some` when it gains an eighth module. That edit is rare
  and it is architecturally real, which is the kind of edit the matrix should attract.

### Neutral
- The five words are a fixed vocabulary like the disposition vocabulary above them, and
  are checked the same way: an invented word fails.
