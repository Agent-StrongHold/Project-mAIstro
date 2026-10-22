---
inventory-delta:
  tests/: +60
---
# Backup artifact and escrow isolation

The 60 cases in `tests/test_backup_isolation.py` execute the production shell
scripts against temporary files. Only Docker transport is replaced: the real
copy shell and SQLite online-backup program run, including a committed WAL row.
They cover allowlisted capture and preserved ciphertext/snapshot data, absent
optional stores, canonical root overlap (including aliases and `/`), nonempty, unreadable
or unsafe dated destinations, symlink/directory/FIFO inputs, sealed contaminated
captures, linked captures, escrow overlap the Conductor opt-out path and repeated immutable verification of a WAL-derived
snapshot without creating new sidecars.
No live services, production data or security settings are touched.

Existing test counts are unchanged: the Conductor drill fixture now moves its
age identity into escrow instead of retaining a leaked artifact copy, and the
readiness structural check scopes itself to the actual 120-iteration loop
rather than accidentally inspecting an earlier `done`. The production
PostgreSQL readiness/semantic-oracle code is unchanged.

This is filesystem/shell regression evidence, not a full Docker backup/restore
drill. The latter requires a Docker daemon and remains separately gated.
