---
inventory-delta:
  packages/maistro-core/tests: +49
  packages/maistro-server/tests: +9
---

Issue #103 (M3-C6, SPEC-092626-1831) adds Workspace work campaigns:
eligibility policy, value-based selection and autonomy controls.

`packages/maistro-core/tests/workspaces/test_campaign_policy.py` (+24) runs the
pure policy through `CampaignSelector` — the shipped selection path: constraint
axes and protected areas and budget stops (AC-1), the four autonomy modes with
human-only absolute even under pin-next (AC-2), explicit human priority kept
separate from the system score with both inputs and both rule versions on the
selection audit record (AC-3), linked-Goal eligibility read through a
read-only reader and never copied (AC-4), parking with evidence and attributed
un-parking (AC-6), the no-widening and no-Goal-write invariants (AC-7), and
actor/policy-version attribution on every decision (AC-8).

`test_campaign_stores.py` (+13) is one conformance suite over the in-memory
reference and the SQLite durable twin (round-trips, versioning, control
clearing, park evidence, usage accumulation, audit scoping), plus the AC-5
restart test that closes the writing connection, reopens the database, and
reads every operator control back with its actor and time before exercising
the `delete_campaign` retention path.

`test_campaign_consumer_contract.py` (+3) proves AC-9: a consumer selects work
through the shared contract, the campaigns package has no import edge to
`maistro_rsi`, and RSI keeps `trace_notes.read_campaign` as a trace
reconstructor with no private campaign policy model.

`packages/maistro-server/tests/api/test_campaigns_api.py` (+9) drives the UI
write path over HTTP: owner-authored policy versions, member-steering of the
four operator controls with actor and policy version on every record,
clearing as its own decision, parking with evidence, whole-record item
updates, the 503 when no campaign store is wired, and 404s that leak no
Workspace or campaign existence.

## Repair round (CI gates, urllib3 supply-chain bump)

No tests added or removed in this round — the delta above is unchanged and
both suite inventories still match. The repair is `uv.lock`-only:
`urllib3 2.7.0 -> 2.8.0` clears CVE-2026-97687/97688/97689 so
`scripts/pip_audit_gate.py` passes without any new allowlist entry (the gate
mandates upgrading when a fixed version exists; the only remaining advisory
is the already-triaged `ecdsa` PYSEC-2026-1325 pair).

Postgres-backed verification at this head (pgvector:pg17 container,
`alembic upgrade head` applied, `MAISTRO_TEST_PG_DSN` set):
`packages/maistro-core/tests/workspaces/` = **174 passed, 2 skipped** (the 2
skips are the documented single-writer interleavings that cannot occur, not
infra gaps — every previously DSN-skipped campaign store leg ran, including
the AC-5 restart test and the claim/eligibility conformance),
`test_campaigns_api.py` = **9 passed**; `bandit` Medium+ = **0** over
core/server/hive-conductor; `mypy` = **0 errors in 734 files**;
`check-vulture-baseline.py` = **0 unclassified** (1402/1402 reviewed);
`ruff check` / `ruff format --check` clean.
