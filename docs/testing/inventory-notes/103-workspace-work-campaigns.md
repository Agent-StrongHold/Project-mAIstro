---
inventory-delta:
  packages/maistro-core/tests: +43
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
