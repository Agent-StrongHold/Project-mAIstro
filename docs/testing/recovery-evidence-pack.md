# Adversarial kill-recovery evidence pack (#1611)

This pack is the public durability claim for the canonical Run spine.
It does not invent a second recovery authority. It records expected
dispositions for named failure injections against `AttemptLifecycleReconciler`,
lease reclaim, and `CanonicalRecoveryEventSink`.

Command:

```bash
uv run pytest packages/maistro-core/tests/runs/test_recovery_evidence_pack.py -q
```

Ledger: `docs/testing/recovery-evidence-ledger.json`

## Scenarios

| id | Injection | Expected disposition |
|---|---|---|
| kill-mid-attempt | lease expires / worker gone while Attempt RUNNING | `recovered_and_parked`; Event on `run.recovery_disposition` |
| dual-worker-fence | stale worker commits after reclaim | `StaleExecutionFence`; historical Attempt outcome not rewritten |
| version-skew-resume | replay same recovery fact | same canonical `event_id`; no second fact |
| mixed-queue-restart | QUEUED / leased / parked coexist after reconcile | each row keeps its status; no silent COMPLETED |
| crash-loop-replay | same settled Attempt reconciled twice | one logical Event identity; Attempt history intact |

Postgres parity for the same contracts is still owned by #62 / #1151 production wiring.
This pack is fail-closed on the in-memory + SQLite-equivalent store APIs used here.
