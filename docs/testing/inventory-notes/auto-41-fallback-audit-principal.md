---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# auto-41-fallback-audit-principal

The workspace-scoped submission suite now also pins the engine-less fallback
path of `POST /v1/tasks` (`routes/missions.py`): when no engine is configured
the route mints the mission into the in-memory stores, and that receipt's
`mission_create` audit entry names the authenticated principal rather than a
literal "system" actor, with the minted mission id as the audit target.

This is the companion of the engine-path audit test in the same file, and it
closes the diff-coverage gap that failed the quality workflow's per-file diff
gate at head 1c3a4b97 (`missions.py`: 50% of 2 changed lines, the fallback
`log_audit` line uncovered). The line is also part of develop's #364 content
after the b43175c1d merge; the test keeps it exercised regardless of which
side of the merge the gate scores.
