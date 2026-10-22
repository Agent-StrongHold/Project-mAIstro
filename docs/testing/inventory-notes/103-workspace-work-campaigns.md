---
inventory-delta:
  packages/maistro-core/tests: +79
  packages/maistro-server/tests: +17
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

## Repair round 2 (radon ratchet + per-file diff-coverage floor)

CI at the previous head failed two gates on this change's own code, and the
repair addresses the evidence directly — no baseline growth, no gate edits.

*Radon CC ratchet:* the campaigns code introduced six new C-or-worse blocks
(`evaluate_item` at E(32), `evaluate_items`, `_constraint_reasons`,
`order_candidates`, both `clear_control`s). All six were refactored to B or
better by extracting the seams the functions already had — scoped record
filtering, the control/park reason lists, the fail-closed Goal-state paths,
the selection sort key, and a shared `restored_mode` helper that both stores
use for the human-only clear decision (its override logic also collapsed to
the two-branch form it always meant). `quality/radon-baseline.json` is
unchanged: 67 reviewed blocks -> 67 current, 0 new, 0 regressed.

*Diff-coverage gate (per file, branch arcs ≥80%):* four files sat below the
floor, and the new tests cover the exact arcs it named. New files:
`test_campaign_model.py` (+6) pins the six record guards — non-empty actor
identity, area value, campaign workspace/name, park reason and item identity,
and the only-a-pause-may-be-campaign-wide scope rule. `test_campaign_wiring.py`
(+3) asserts the backend selection: a SQLite pool yields the durable store
with its schema, no pool yields the in-memory reference loudly, and
`warn=False` stays silent without changing the (non-durable) store type.
`test_campaign_stores.py` (+15 across both store legs) covers explicit
campaign_id/created_at/set_at replay inputs, cross-Workspace listing,
the three restored-mode outcomes of clearing a human-only control,
read-idempotent unparking, the no-record `append_audit` no-op, and — over two
connections to one database — the concurrent clear/unpark races where the
conditional UPDATE matches zero rows and the database's record, not the
writer's stale read, must win (`require_control`/`require_park` included).
`test_campaigns_api.py` (+8) covers the 503 with no container at all and with
a container lacking the attribute, the 404s for clearing/unparking unknown
and cross-campaign control/park ids (the existence-leak check), the item-record
listing route, and usage recording with actor attribution and accumulation.

Both suite inventories re-verified after the round.

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
