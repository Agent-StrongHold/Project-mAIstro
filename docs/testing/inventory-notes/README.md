# Inventory notes

One file per change: the delta it made to the suite counts, and the prose
explaining why. Both live here, in the same file, written by the same change —
see [`../SUITE-INVENTORY.md`](../SUITE-INVENTORY.md) and `ADR-082526-547c`.

## Why this is a directory and not a section

It used to be a section. Every branch that added tests rewrote the same block
of prose in place, so any two such branches conflicted the moment either
merged — one merge to `develop` put 11 of 32 open PRs into conflict on that
one file, and the conflicts were genuine prose disagreements that no
regeneration could settle (#208).

A directory removes the collision rather than managing it: two changes never
write the same path, so git has nothing to reconcile. The cost is that the
notes no longer read as one continuous narrative, which is the right trade —
the narrative was never actually continuous, it was overwritten.

## Writing a note

Name the file after the change: `<issue>-<slug>.md`, e.g.
`133-archive-tier.md`. Any unique name works; the number just keeps the
directory sorted roughly by age.

Say what moved and why, not just how much. The count alone hides compensating
changes — when #130 added nineteen maistro-core node IDs while the PM-demo
retirement removed eighteen backend node IDs and one e2e case, the total
barely moved and a reader checking only the number would have seen nothing.
That is the case these notes exist for.

## The one machine-read part

A note may open with front matter recording what it moved:

```markdown
---
inventory-delta:
  packages/maistro-core/tests: +12
  tests/: -3
---
```

`check-suite-inventory.py` sums these over every note and adds
`../inventory/baseline.json` to get the count it expects. Do not write the
block by hand — `check-suite-inventory.py --update` measures it and writes it
into the note named after your branch, which is what keeps two changes off the
same path.

Everything below the front matter is prose, parsed by nobody, read by people
trying to understand a number that changed. A note with no front matter records
no delta, which is correct both for a change that moved no count and for every
note written before the ledger existed.

A block that is present but unreadable is an error, not a zero. A delta the
gate cannot parse would otherwise quietly contribute nothing, which is the
class of silent wrong number this gate exists to catch.

## Archives

- `0000-historical.md` — every note written before the split, verbatim.
- `0001-restored-resource-floors-75-127.md` — two notes lost to a conflict
  resolution and recovered from history.
