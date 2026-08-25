---
id: ADR-082526-547c
title: "The suite-inventory count is a sum of per-change deltas, not a shared row"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-25
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-547c: The suite-inventory count is a sum of per-change deltas, not a shared row

## Context

`docs/testing/SUITE-INVENTORY.md` records one collected node-ID count per
suite, and `scripts/check-suite-inventory.py` fails the build when a suite
drifts from its recorded number. The gate earns its keep: a `conftest` import
error or a changed `testpaths` turns a 400-test suite into 0 collected, and
"0 tests ran" is not a pytest failure, so every downstream job still goes
green. Comparing against a recorded number is the only thing that makes that
loud.

The recording is the problem. #208 measured the cost: merging two PRs put
**11 of 32 open PRs into conflict simultaneously**, every one on this single
file and nothing else, and resolving the two that were themselves bases pushed
the identical conflict into five stacked descendants — 16 branches touched by
two merges.

#209 fixed half of it. The free-prose narrative that every branch rewrote moved
out to `docs/testing/inventory-notes/`, one file per change, which cannot
conflict because two PRs never write the same path. What #209 left behind, and
what reopened #208, is the generated table:

```
| `packages/maistro-core/tests` | 7698 | `ci.yml` |
| `packages/maistro-evolve/tests` | 629 | `ci.yml` |
```

Two PRs that both add tests both rewrite a count. The conflict is now
mechanically resolvable — regenerate, do not hand-merge — but #208's first
acceptance criterion says such PRs *no longer conflict*, and they still do.

Two things make it worse than "one line, easily fixed":

1. **Different suites still collide.** Table rows are adjacent lines. Git needs
   unchanged context between two changes to merge them, so a PR touching
   `maistro-core/tests` conflicts with a PR touching `maistro-evolve/tests`
   even though the two changes are unrelated and both are correct.
2. **Every base move costs a full re-collection.** Regenerating means running
   `pytest --collect-only` across thirteen suites. A branch that has not
   changed a single test still pays it, every time its base moves, because the
   number it recorded was an absolute that someone else's merge invalidated.

Both follow from one decision: the recorded value is an **absolute**, written
where everyone writes.

## Decision

Record the **delta**, not the total. Expected count becomes

```
expected(suite) = baseline(suite) + Σ delta(suite) over every recorded change
```

- `docs/testing/inventory/baseline.json` holds the counts as of the last
  compaction. It is touched at compaction and effectively never otherwise.
- Each change that moves a count writes its own delta into the front matter of
  its own note in `docs/testing/inventory-notes/<slug>.md` — the one-file-per-
  change convention #209 already established, extended to carry the number
  beside the prose that explains it.
- `SUITE-INVENTORY.md` stops carrying counts. It keeps the prose that explains
  what the gate measures and why; the numbers are rendered on demand with
  `--show`.

Two PRs never write the same path, so they never conflict — including when
both change the same suite. And because deltas are additive, a branch whose
base moves needs no regeneration at all: its own delta is still true, and the
sum absorbs the other branch's. The re-collection cost disappears with the
conflict.

The tripwire is unchanged. A suite that stops collecting still produces an
actual that does not match an expected, and still fails.

Compaction folds deltas into the baseline and records the folded note slugs in
`baseline.json`, so notes themselves are never edited — `inventory-notes/` is a
record of what was written, not a document kept current.

## Consequences

### Positive
- #208's first acceptance criterion becomes literally true: two PRs that both
  add or remove test node IDs do not conflict, whatever suites they touch.
- A base move no longer forces a thirteen-suite re-collection on a branch that
  changed no tests. This is the larger practical saving.
- The number and the prose explaining it live in one file, written by one
  change, so they cannot drift apart.
- Merge-queue scaling inverts: today more open PRs means more conflicts per
  merge; here it means more delta files, which do not interact.

### Negative / Trade-offs
- `SUITE-INVENTORY.md` loses its at-a-glance table. `--show` renders it, but a
  reader browsing the docs no longer sees the numbers inline. Judged worth it:
  the table's whole cost was that it was a single shared place to write.
- Expected counts are now derived rather than read, so a corrupt or malformed
  delta file is a new way for the gate to be wrong. Mitigated by failing
  loudly on unparseable front matter rather than skipping it.
- Delta files accumulate. Compaction is a deliberate maintenance action; until
  it is run, the sum walks over every note. Thirteen integers per note makes
  that cheap for a long time, but it is not free forever.

### Neutral
- Counts, not node-ID sets, remains the measurement. That trade-off is argued
  in the script's docstring and #208 puts it explicitly out of scope; this
  record changes where the number is stored, not what it counts.
- A note is still not mandatory per change. Requiring one belongs to the AC
  gate, not here; a change that moves no count needs no delta.
