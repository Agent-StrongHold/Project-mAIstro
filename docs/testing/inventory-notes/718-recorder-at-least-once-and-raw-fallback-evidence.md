---
inventory-delta:
  packages/maistro-core/tests: +7
---

Repairs the two findings from the 2026-09-08 verifier round against the
#718 quota ledger, both about truthful at-least-once evidence:

1. `CanonicalInvocationUsageRecorder.record` pre-marked the Invocation before
   the awaited durable tracker write, so a transient ledger failure
   permanently omitted durable quota evidence (the retry was a silent no-op).
   The recorder now marks only after the durable write and the usage-log
   append both succeed (durable-first ordering), and the Invocation authority
   helps the retry happen: a recorder failure at terminalization is isolated
   to an error log (never crashes an already-completed physical effect, which
   an attempt-level retry could duplicate), and every deduplicated hand-out of
   a COMPLETED effect re-confirms evidence — the recorder and the durable
   trackers are idempotent on Invocation identity, so a healthy ledger sees a
   no-op and a failed one is repaired. At-least-once recording, at-most-once
   charging.
2. `run_task`'s raw-gateway fallback (no `governed_egress`) crossed no
   canonical Invocation and left no evidence at all. The fallback now records
   its usage on the process default usage log with explicit provenance —
   actual tokens when the gateway reported usage, an explicit
   `usage_reported=False` marker when it did not, never a fabricated
   Invocation identity — plus a `conductor_ungoverned_llm_call` warning so the
   ungoverned call class stays visible to operators. `recorder.py`'s module
   docstring names both live recording paths after the cutover.

Tests added (packages/maistro-core/tests):

- `quota/test_canonical_invocation_recorder.py` (+2):
  `test_transient_ledger_failure_is_retried_not_permanently_lost` (the exact
  verifier reproduction: fail-first identity-keyed tracker, retry succeeds,
  charged exactly once, one usage event, no half-evidence on the failed
  attempt) and `test_repair_retry_after_success_does_not_double_charge`.
- `capabilities/test_binding_invocation.py` (+1):
  `test_deduplicated_handout_repairs_quota_evidence_after_ledger_failure` —
  real `InvocationExecutionService.invoke` with the canonical recorder as
  `on_completed`; the first invoke completes despite the ledger outage (error
  surfaced via the `maistro.capabilities.invocation` logger), the second
  (attempt-2) invoke makes no second provider call and repairs the ledger.
- `agents/test_conductor.py` (+4, `TestUngovernedFallbackUsageEvidence`):
  reported usage recorded with provenance and no invented Invocation identity;
  missing usage recorded as an unreported marker; the governed egress path
  leaves the fallback log silent (canonical path owns recording); the
  ordinary `run_task` entry point without an egress records its usage.
