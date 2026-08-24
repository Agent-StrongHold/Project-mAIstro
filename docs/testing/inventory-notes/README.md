# Inventory notes

One file per change, explaining why the suite counts in
[`../SUITE-INVENTORY.md`](../SUITE-INVENTORY.md) moved.

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

Nothing here is machine-parsed, so there is no schema to satisfy. It is read
by people trying to understand a number that changed.

## Archives

- `0000-historical.md` — every note written before the split, verbatim.
- `0001-restored-resource-floors-75-127.md` — two notes lost to a conflict
  resolution and recovered from history.
