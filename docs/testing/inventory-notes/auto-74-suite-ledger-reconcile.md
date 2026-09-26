---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-74-suite-ledger-reconcile

Reconciles the one-node ledger drift the #74 verify pass surfaced
(`check-4.log`: expected 10992, collected 10993) and that survived both
develop merges since. Measured, not guessed — collection was executed at
three revisions with each revision's own tree and `src` on `PYTHONPATH`
(`git archive` snapshots; the base measurement matched its ledger exactly,
which validates the method):

- lane start `3e9f7525b` (develop #1403): expected 10045, collected 10045 —
  green baseline.
- `88f6fa900` (pass-7 head): expected 10939, collected 10940 — the +1 is
  already here, so the earlier "check-suite-inventory 13/13" claim in
  `auto-74-repair.md` pass 7 was false.
- `777f626d8` (after merging develop `5fff24e1d`): expected 11007, collected
  11008 — the last develop merge was exactly balanced (+15 recorded, +15
  collected; #1193 +11 and #1108 +4).

Where the +1 comes from: node-ID diffs between the snapshots show the lane's
own recorded deltas (+6 `auto-74-repair.md`, +2 `auto-74-fc3c.md`) undercount
the lane commits' net additions by 3 — the lane's `test_sentinel_policy.py`
grew +9 nodes and `test_warden_regex_equivalence.py` +1 across
`8d728180d`/`435c24cca`, and `test_react.py` net +1 — while develop commits
merged inside the same range over-record by 2 net. The compensating errors
leave exactly +1 unaccounted. No suite stopped collecting (the failure mode
this gate exists for): maestro-core GREW to 11008 and the other twelve
suites are byte-for-byte green.

Per the ledger's design (ADR-082526-547c and the script's own failure text),
a base-move drift is recorded as the net delta in the contributor's own
note; this note is that record. Nothing about which tests run changed in
this commit — the number above is the whole change.
