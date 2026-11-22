---
inventory-delta:
  packages/maistro-core/tests: +13
---
# auto-977: metering diff-coverage repair (+13)

CI-repair round for #977 after the merge-queue coverage gate flagged
`packages/maistro-core/src/maistro/extensions/metering.py` at 77.7% of 130
changed branch arcs against the 80% per-file floor. No production code
changed in this round — every flagged arc is behavior the quota ledger
declares (docstrings and refusal messages) that no test had ever driven.

`test_metering.py` (+13 node IDs), by cluster:

- **Configuration refusals (2)** — `ExtensionQuotaPolicy` construction
  refuses an unknown unit, a reserve above the limit, an empty or inverted
  billing period, a half-specified rate limit, and a `rate_limit` of zero
  (a limit that refuses every call is a declaration error, not a runtime
  one); both ledger constructors refuse `:memory:` and blank paths, because
  per-process private budgets would silently void server-side enforcement.
- **Policy identity and clock (3)** — verbatim policy re-declaration is a
  no-op while changed facts under the same `policy_id` conflict (new limits
  need new ids to stay auditable); `policy_balance` names an unknown policy;
  admission samples the clock after taking the write lock and refuses a
  non-finite reading rather than reserving against a nonsense timestamp.
- **Scope and period gating (1)** — a Workspace-scoped policy does not
  govern other Workspaces (gap refusal, never ungoverned admission), and
  the billing period is half-open: at `period_end` the policy stops
  applying, so post-period admissions are refused rather than charged to a
  closed period.
- **Non-token units (1)** — a `micro_usd` policy settles spend in micro_usd
  and a `requests` policy settles in requests, with `requests` admitted
  without any caller-supplied upper bound (one reservation is one request).
- **Terminal-state guards (4)** — a denied reservation has no provider
  outcome to settle; settlement replays idempotently but changed amounts
  under the same identity conflict; a settled reservation can no longer be
  released (refunding executed work would un-charge reported spend); and
  provider corrections apply only to settled reservations, with revision
  zero reserved for the canonical settlement.
- **Aggregation and cancellation (2)** — `totals` with no org filter
  aggregates across every org (the unfiltered clause is a real code path,
  not a default that never runs); cancelling a caller awaiting admission
  propagates `CancelledError` only after the in-flight SQLite transaction
  completes, so the hold is neither lost nor doubled and the identical
  retry is an idempotent no-op.

The cancellation case is deterministic: the test gates
`asyncio.to_thread` behind an event rather than racing a real thread.
