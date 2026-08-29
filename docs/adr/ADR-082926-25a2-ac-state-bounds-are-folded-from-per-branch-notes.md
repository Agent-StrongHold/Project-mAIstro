---
id: ADR-082926-25a2
title: "AC-state bounds are folded from per-branch notes, not held on one shared line"
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
  - maistro-engine#ADR-082226-ff3c
  - maistro-engine#ADR-082526-ef55
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_ac_state_notes.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082926-25a2: AC-state bounds are folded from per-branch notes, not held on one shared line

## Context

`quality/ac-state-ceilings.json` holds eleven counters — ten debt ceilings and
the `design_coverage` floor — and `check-ac-state.py --ratchet` demands **exact
equality** on every one of them in both directions. So any PR that moves any
counter must `--bank`, and the moment one such PR merges every other open one
conflicts on that file. `quality/ac-state.json`, the 4,700-line per-decision
measurement, is rewritten in the same breath.

Observed on one pass through the queue: #555, #569, #577 and #582 were each
clean on the code they changed and conflicted on exactly these two files. Every
resolution costs a `--run-tests --ratchet --bank` cycle and holds only until the
next merge. With N such PRs the queue needs O(N²) rebanks to drain.

This is #208's defect — *one narrative slot rewritten by every PR* — which was
fixed for `SUITE-INVENTORY.md` by per-branch note files with a derived
aggregate. The AC-state ledger never got the same treatment.

It is worse here than a merge-hygiene annoyance. The rebank is not mechanical:
each one re-derives a **safety floor** under time pressure, on a file whose whole
purpose is to be hard to weaken. #534 exists because a candidate that can
rewrite its own oracle is not gated by it. Requiring everyone to rewrite that
oracle on every base move is pressure in exactly the wrong direction, and #508 —
a PR that banked a floor `develop` could not meet — is what that pressure
produces.

## Decision

**No shared line. The bounds are folded from per-branch notes read at the base
revision.**

1. **`quality/ac-state-notes/<slug>.json`** — one file per branch, written by
   `--bank`, recording that branch's own measured counters and the mode they
   were measured in. A branch touches only its own file, so two branches cut
   from the same base never conflict.

2. **The effective bound is a fold, not a stored value.** For the ten debt
   counters the bound is the **minimum** across notes; for `design_coverage` it
   is the **maximum**. Both folds are monotone, so the bound can only tighten —
   which is the same guarantee the single line gave, without the single line.

3. **The fold reads notes as of the base revision**, through #534's
   `ratchet_provenance`. A candidate's own note is written locally and is
   deliberately *not* part of the fold it is judged against: a note that could
   relax its own bound would be the self-approving oracle #534 closed.

4. **A note enters the bound only by merging.** This is what makes staleness a
   non-problem rather than a cleanup chore, and it is what prevents #508: an
   abandoned branch's note never reaches the base revision, so it can never hold
   a floor `develop` cannot meet.

5. **`quality/ac-state.json` stops being committed.** It is a generated
   measurement, it is the larger half of the conflict, and nothing reads the
   committed copy as an oracle now that the note carries the numbers. The gate
   writes it as a run artefact.

`quality/ac-state-ceilings.json` is retired, its final content seeded as
`quality/ac-state-notes/_baseline.json` so no bound loosens across the change.

**Compaction is defined rather than left to grow.** A note is *stale* when every
counter in it is dominated by the fold of the others — it contributes nothing
the rest do not already say. `--compact` folds the notes into `_baseline.json`
and removes those; it is a maintenance action a human runs, never part of the
gate, because a gate that deletes evidence is a gate that can lose it.

## Consequences

### Positive
- Two PRs raising `design_coverage` from the same base no longer conflict, and
  after both merge the fold reflects both. The queue drains in O(N).
- The oracle a candidate is judged against is no longer a file the candidate
  rewrites, which extends #534's property from the wiring ledger to this one.
- #508's failure mode — banking a floor the trunk cannot meet — becomes
  unreachable rather than merely unlikely.
- The 4,700-line generated file leaves the diff entirely.

### Negative / Trade-offs
- The bound is now computed from several files rather than read from one, so
  "what is the current floor?" needs a command (`--show-bounds`) instead of a
  glance at a line. The gate prints it on every failure, which is where it is
  actually needed.
- `quality/ac-state-notes/` accumulates until someone compacts it. That is a
  deliberate trade: the alternative is a gate that prunes evidence on its own.
- The notes directory is a new governance surface. A note is data, not a
  decision, and the fold ignores unknown keys — but a malformed note is a
  non-passing state, never a skipped one.

### Neutral
- The ratchet's meaning does not change: the same eleven counters, the same
  directions, the same refusal. This ADR moves where the number is written.
- The other ledger ratchets (`vulture`, `radon`, `wiring-reads`, `reachability`)
  have the same shape and are not touched here; they are #319's.
