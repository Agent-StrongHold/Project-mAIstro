---
inventory-delta:
  packages/maistro-core/tests: +9
---

# auto-1114 dispatch-claim repair

Nine net new collected nodes in `tests/tasks/test_admission.py`, closing the
three verifier findings from the #1114 verify pass at head `1b0c59753`:

1. **The RUNNING-with-no-evidence crash gap.** A worker wrote the Run's
   QUEUED→RUNNING transition (the receipt's PLANNING move) before creating the
   NodeRun/Attempt, and `TaskQueue.recover` scanned only QUEUED Runs — a death
   in that window stranded a RUNNING Run no restart could reach. The repair
   makes first dispatch on a claiming store go through the canonical atomic
   consumer claim (`claim_consumer_run`, #544): RUNNING, the NodeRun and a
   leased Attempt commit together, so a death before the claim leaves the Run
   QUEUED (recoverable) and one after it leaves leased evidence for the
   Attempt sweep (#232). `record_transition` no longer writes the dispatch
   transition on claiming stores, and a duplicate delivery that loses the
   claim abandons without terminalizing the winner.
   - `test_a_phase_transition_does_not_write_the_dispatch_claim`
   - `test_death_after_the_dispatch_phase_leaves_the_run_queued_and_recoverable`
   - `test_first_dispatch_writes_running_together_with_its_evidence`
   - `test_a_duplicate_delivery_loses_the_claim_without_touching_the_winner`

2. **Nonterminal malformed-payload disposition.** `_fail_unrecoverable_run`
   could land the intermediate RUNNING write and lose the FAILED write, and
   nothing ever re-examined that Run. Recovery now also scans task-source
   RUNNING Runs with no NodeRun and terminalizes them, so a refused FAILED
   write is retried on this and every later restart (the extended
   `test_recovery_survives_a_refused_terminalization` proves the second pass
   lands).
   - `test_recovery_terminalizes_a_stranded_running_claim`
   - `test_recovery_leaves_a_claimed_run_to_the_attempt_sweep`

3. **PostgreSQL coverage at both boundaries.** The boundary-2 crash (receipt
   committed, enqueue notification never sent) had no durable-store test, and
   the new claim-boundary crash plus the stranded-claim disposition need
   durable proof. All three run under `MAISTRO_TEST_PG_DSN`:
   - `test_postgres_death_after_receipt_before_notification_executes_original_identity`
   - `test_postgres_death_between_dispatch_phase_and_claim_executes_original_identity`
   - `test_postgres_stranded_running_claim_gets_a_terminal_disposition`
