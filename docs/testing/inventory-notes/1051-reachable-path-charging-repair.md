---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/hive-conductor/backend/tests: +3
---
# Issue #1051 — repair: make per-Run budget charging reachable (and prove it)

Verification of the original change found that the durable budget ledger was
charged per *context read*, not per Run: the `discovery_context` Protocol's
`context_for` had no cycle-key parameter, so no production caller could tell
the host which Run a read belonged to — `HiveDiscoveryContext` defaulted
`cycle_key=""`, `_charge` billed every read, and one seed cycle with five
sources landed as `fetches=20 curated=4 cycles=[]` instead of `5 / 1 /
[run-id]`. Consequences: `daily_curate_budget` could never exhaust in
production (the `cycles` list stayed empty) and the fetch budget over-charged
~4x. The Hive tests passed anyway because they called
`cycle_context(cycle_key=...)` directly — a call shape production never made.

## What changed

- `discovery_context.py`: the Protocol and the bare provider take
  `cycle_key: str = ""`. Documented contract: a node always passes
  `ctx.run_id`; an unkeyed read is a look, never a fresh charge.
- `discovery_source_fetch.py` / `discovery_scout.py` / `discovery_curate.py`
  (both reads): every node read now carries `cycle_key=str(ctx.run_id)`.
- `services/discovery.py`: `_charge` charges keyed reads idempotently and
  ignores empty keys; `cycle_context` skips the gate for an already-charged
  cycle, so exhaustion stops *new* cycles without closing under a Run that
  was admitted and billed mid-flight (the charged spend otherwise reads as
  fresh spend to the per-node-read gate — the partially-charged state the
  budget must never create).
- `providers/discovery_source.py`: a redirect hop refused by the outbound
  policy surfaces as `EffectNotApplied` (Invocation recorded FAILED with the
  reason), not as an UNKNOWN outcome — redirects are followed, and the shared
  client's guarded transport already re-validates every hop, so the refusal
  is now pinned at the provider seam too.

## What the +2 (core) is made of

`graph/nodes/test_discovery_pipeline.py`:

- `test_every_node_read_carries_the_run_id_as_its_cycle_key` — the missing
  link the prior round lacked: scout, curator and fetch-refusal reads must
  pass `ctx.run_id` to the provider, or per-Run charging is unreachable no
  matter what the host does. Mutation-checked: reverting one node to the
  3-arg call fails this test while every behavior test stays green.
- `test_provider_redirect_into_a_private_target_is_refused_at_that_hop` —
  the discovery provider rides the guarded shared client: a declared feed
  302-ing at the metadata address is refused at that hop (custom transport,
  not `MockTransport`, which `guarded()` deliberately leaves unwrapped), and
  the provider surfaces the refusal as the honest no-effect contract.
  Mutation-checked: dropping the `SSRFBlockedError` translation fails the
  test (raw `OutboundBlockedError` escapes).

## What the +3 (conductor) is made of

`test_discovery_service.py`:

- The two charge tests now call through
  `discovery_context_provider().context_for(...)` — the exact object
  `adapters.maistro_core` wires into the node resolver, with the Protocol
  signature the nodes use — instead of the service-level call shape
  production never makes.
- `test_an_unkeyed_read_is_look_only_and_never_charges` — three unkeyed
  reads leave `cycles/fetches/curated` untouched.
- `test_an_admitted_cycle_is_not_re_refused_mid_run_by_its_own_charge` — a
  tight fetch budget: the charging read succeeds, a fresh cycle is refused,
  the admitted Run's later reads still carry full context.
- `test_the_real_scout_node_charges_once_through_the_wired_provider` — the
  cross-package seam executed end to end: the real `DiscoveryScoutNode` with
  the real Hive provider charges once for a Run, a retried execution of the
  same Run charges nothing, a different Run charges again.

## Claim reconciliation

The original change's note and commit message said budgets are "charged once
per Run id". That was the intended contract, not the reachable behavior; this
repair makes the reachable path perform it and pins both halves (nodes pass
the key in core; the host charges once per key in the conductor). The claim
is now true by construction rather than by assertion.
