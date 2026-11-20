---
inventory-delta:
  packages/maistro-core/tests: +35
---
# cursor-m1-b-p4a-recovered-disposition-8551-ad86

#232 P4a `apply_recovered_attempt_disposition`: spine-parametrized parking /
refusal / fixed-point cases (+30 with memory+sqlite collected; postgres leg
skipped without DSN), two memory-only REQUESTED/CREATED refusals, one pure
planner lineage refusal, and two PG lock-order stand-ins that assert Run→all
NodeRuns FOR UPDATE with no Attempt locks.
