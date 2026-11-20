---
inventory-delta:
  packages/maistro-core/tests: +37
---
# cursor-m1-b-p4a-recovered-disposition-8551-ad86

#232 P4a `apply_recovered_attempt_disposition`: spine-parametrized parking /
refusal / fixed-point cases (+30 with memory+sqlite collected; postgres leg
skipped without DSN), two memory-only REQUESTED/CREATED refusals, one pure
planner lineage refusal, two PG lock-order stand-ins (Run→all NodeRuns FOR
UPDATE, no Attempt locks), plus Codex follow-ups: archive_key hydrate
assertion and SQLite CancelledError rollback coverage.
