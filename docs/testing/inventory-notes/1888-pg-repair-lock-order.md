---
inventory-delta:
  packages/maistro-core/tests: +11
---
# 1888-pg-repair-lock-order

Normalizing `PgRunStore.repair_attempt_result` to the store-wide parent-first
lock order (Run → NodeRun → Attempt, #1888) adds one file with eleven tests in
two legs.

Ten run everywhere on the statement-shape stand-in seam
(`test_eval_on_run_pg_internals.py`'s pattern): the order the repair actually
issues — lineage read, Run FOR UPDATE, NodeRun FOR UPDATE, Attempt FOR UPDATE,
then both writes; the identity-only Run lock (no payload or archive_key
column, so a repair never hydrates or validates the parent Run's payload); a
terminal Run over a terminal Attempt staying repairable; the missing-attempt
refusal locking nothing; a lineage deleted between the unlocked read and the
locks reporting the target gone (AttemptNotFound, not a parent-only failure);
the nonterminal refusal landing after the locked re-read but before any write;
two payload-vs-relational-lineage corruption refusals (the locked re-read
trusting the promoted columns, not a payload that names a different parent);
and the accepted-outcome copy moving with the Attempt while an unaccepted one
repairs without a NodeRun write.

The ninth runs only against a migrated PostgreSQL: a real `record_eval_score`
holds the Run and NodeRun row locks while paused before its Attempt lock, and
the repair must be observed — via `pg_blocking_pids` on an independent
connection between three pinned backends — blocked behind it without holding
the Attempt lock, then complete once the eval writer commits. This is the
fail-before/pass-after oracle: under the retired Attempt-first order the pair
deadlocks and the test fails, which was verified by running it against the
pre-change store.
