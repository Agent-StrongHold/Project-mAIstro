---
inventory-delta:
  packages/maistro-core/tests: 0
---
# B2 merge repair — 9c47bc40

Source parents: a7c1aa48e5031a6615c2186fe925e030619ac02c and
ac69535ef165ded3ca82cd3428728569de3251fa (the supplied develop snapshot).

Resolve the conflict in `tests/extensions/test_pack_contracts.py` by keeping
both parents' collision regression tests, each with its decorators and empty
registry assertion. Their +1 deltas already exist in the inherited inventory
notes; this resolution adds no unaccounted node. Retain one production guard
(the develop implementation), removing only the redundant guard created by
the automatic merge. No codec behavior, gate, or quality ledger is changed.

Pre-fix evidence: job 9c47bc40 check-1 through check-4 fail at the conflict
marker at line 874 (Ruff, format, pytest, suite inventory). Post-fix commands
and results are recorded in `REPAIR-NOTES-1893-9c47bc40.md`. The existing
collision tests call the production registry and require rejection before
any record is created; they do not mock the outcome. Admission database skips
will not be counted as durability proof.
