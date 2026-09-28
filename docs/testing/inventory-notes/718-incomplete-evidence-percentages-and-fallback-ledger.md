---
inventory-delta:
  packages/maistro-core/tests: +21
  packages/maistro-rsi/tests: +3
---

Repairs the two evidence-backed findings from the 2026-09-08 final verifier
round (head caa54de7, verdict NEEDS-REPAIR) against the #718 quota ledger.

## Finding 1: the raw fallback bypassed the quota ledger

`agents/conductor.py` recorded raw-gateway fallback calls only on the
`InMemoryUsageLog`; a process that *carried* a quota ledger could still
present complete per-provider rows while omitting that call class. The
fallback now also writes to a process-default quota ledger
(`quota/default_tracker.py:get_default_quota_tracker`/
`set_default_quota_tracker`, mirroring the default usage-log singleton; the
registry lives outside `quota/tracker.py` because the promotion path imports
that module and must not inherit the protocols package), registered once by
the Container
composition root (`container.py:create_container`, all three backends
converge there). Reported fallback tokens reach the ledger as usage; a
missing report becomes an unreported marker — never a measured zero, never a
fabricated Invocation identity (the call crossed no canonical authority by
construction, so it never touches `record_invocation`). The ledger write is
isolated: a failing ledger logs
`conductor_ungoverned_quota_ledger_write_failed` and cannot take down a
provider call that already succeeded. Authoritative recording stays on the
canonical Invocation terminalization path — the default only receives the one
ungoverned call class's non-Invocation evidence, per the issue's stop
condition. `recorder.py`'s module docstring names both live paths.

## Finding 2: incomplete evidence presented as 0% used / full headroom

The verifier's executed reproduction: after
`record_invocation(..., usage_reported=False)` the ledger reported
`usage_complete=False` yet `get_usage_pct` returned `0.0` and
`ModelQuota.headroom_tokens` returned the full free allowance — a percentage
presented as complete over evidence that is explicitly incomplete. All three
trackers (`InMemoryQuotaTracker`, `SqliteQuotaTracker`, `PgQuotaTracker`) and
the `QuotaTracker` protocol now return `float | None`: `None` when the
provider/cycle carries unreported evidence, `0.0` only for a cycle with no
recorded call at all (vacuously complete). `maistro_rsi.ModelQuota.used_pct`
is `float | None`; unknown usage yields no assertable headroom
(`headroom_tokens == 0`) and ranks last in quota-burn scheduling, with an
`rsi_model_quota_evidence_incomplete` warning so the operator sees why. The
in-memory read no longer fabricates a zero usage row for a never-called
provider.

## Tests

- `quota/test_tracker.py` (+5): unreported/mixed evidence → `None`; no
  evidence at all → measured `0.0` with no fabricated row; reported evidence
  still computes the ratio; default-ledger singleton round-trip with
  save/restore.
- `persistence/test_sqlite_quota.py` (+2) and `persistence/test_pg_quota.py`
  (+2): the same unreported/mixed → `None` contract on the durable backends.
- `persistence/test_backend_conformance.py` (+9 node IDs: three tests × the
  memory/sqlite/postgres parametrization): the contract pinned identically
  across all three backends, including the one-unreported-call-keeps-the-
  cycle-unknown case and the no-fabricated-rows read property.
- `agents/test_conductor.py` (+3, `TestUngovernedFallbackUsageEvidence`): a
  registered ledger receives reported fallback tokens; a missing report
  becomes `unreported_count`/`usage_complete=False` and the provider's
  percentage reads `None`; an exploding ledger is isolated from the call.
  The `fallback_usage_log` fixture now also isolates the default ledger, and
  the suite conftest's `_reset_singletons` clears it after every test (a
  container-creating test registers it via the composition root).
- `maistro-rsi/tests/test_quota_burn.py` (+3): the verifier's exact
  reproduction scenario — unreported usage must not present
  `used_pct=0.0`/full headroom, must rank behind a measurably busier
  provider, and `next_model` must not route burn toward unknown budget
  state; mixed evidence stays unknown.

The remote-PR findings from the same round (PR body closure keyword, CI
checks IN_PROGRESS) are GitHub-side facts this lane cannot mutate (no GitHub
mutations permitted); they remain for the integrating human.
