---
inventory-delta:
  packages/maistro-core/tests: +20
---

# auto-977-extension-metering

Implements extension usage metering and Workspace/org quota enforcement
(M9-I2, #977): `packages/maistro-core/src/maistro/extensions/metering.py`
(physical-use identity keyed to canonical Invocation ids, nested delegation
lineage, aggregation by Workspace/extension/publisher/capability/time window,
atomic reservation/commit/release/correct quota ledger with fixed-window rate
limits), exports wired through `maistro/extensions/__init__.py`, and durable
schema declared in `quality/durable-table-retention.json` (5 accounting
tables). Attribution only: canonical provider totals stay with
`maistro.quota`; this module never writes to them.

**+20 `packages/maistro-core/tests/extensions/test_metering.py`**
(collect-only verified on this head), each cluster naming the #977 acceptance
criterion it pins:

- **Physical use recorded once (2)** — a provider call routed through an
  extension charges once in canonical totals (`SqliteInvocationQuota`) and
  attributes once at the extension seam; canonical re-observation, event
  retries, and an alternate extension alias re-reporting the same
  `invocation_id` conflict instead of charging; `event_id` idempotency with
  changed-facts conflicts; incomplete nested lineage refused.
- **Nested delegation without double counting (1)** — root and delegate rows
  stay two physical records with ordered causal lineage; the delegate's usage
  re-attributed to the orchestrator conflicts; per-extension breakdown
  partitions the same rows `totals` sums.
- **Aggregation by scope and time (2)** — filters across Workspace, extension,
  publisher, capability, half-open time windows; breakdowns per dimension;
  host-measured resources (CPU/memory/network) sum only where measured and
  report `None`, never a measured zero, when unmeasured.
- **Quota admission and bypass resistance (4)** — hold→settle→refund
  round-trip; exhaustion survives retries (refusal evidence re-raises),
  fact-reshaping under a reused id conflicts, and new Agents/extension
  aliases are refused from the same Workspace budget; an org-wide policy
  backstops alias Workspaces; opening spend and reserve headroom shrink the
  ceiling.
- **Refunds and corrections (3)** — released reservations refund their holds
  and can never settle afterwards; commit above the hold records truthful
  overage (negative availability); provider-reported corrections are
  absolute with monotonic revisions — replay is idempotent, revision reuse
  conflicts, a stale revision is kept as evidence without rolling accounting
  backwards.
- **Rate limits and admission gaps (3)** — fixed-window rate limit refuses
  inside the window (same-instant admissions included), refusals consume no
  rate budget, and a new window admits; unconfigured tables admit while a
  populated table covering nothing applicable refuses (mirroring the
  canonical Invocation quota's `_admission_reason`); missing upper bounds
  refuse without holding.
- **Concurrency (3)** — four concurrent admissions against one remaining
  budget admit exactly one; six concurrent duplicate reservations hold
  exactly once; two OS processes (`spawn`) racing the same remaining budget
  serialize at `BEGIN IMMEDIATE` with one admitted and one denied.

Mutation-checked on this head: removing the `invocation_id` UNIQUE constraint
fails the both no-double-count tests; narrowing the rate-window boundary back
to `created_at < now` fails the rate-limit test. Both mutations were reverted
and the suite is green as committed.
