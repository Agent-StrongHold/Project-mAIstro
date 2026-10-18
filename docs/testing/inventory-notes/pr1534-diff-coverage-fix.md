---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
---

Closes the diff-coverage gap the Coverage gate flagged on PR #1534
(#1064/#1065 — Evolve battle/finalize replay-safety and the restart
resolver): `services/evolution.py` at 50% of 2 changed lines (uncovered
286), `services/evolution_graph.py` at 70% of 20 changed branch arcs
(partial at 484, 499, 507, 968, 971, 973), and `services/evolution_recovery.py`
at 85% of 40 changed lines (uncovered 40, 50-53, 57). Eight tests added
across four existing files, none padding — each targets one of the gaps
above.

`test_evolution_service.py` (+1): `build_llm_call` is the new public
accessor a restart-recovery resolver uses to reach `_EvolutionService`'s
private LLM-call builder (#1064) — nothing previously called it, so its one
line was dead in coverage terms. `test_build_llm_call_public_accessor_delegates_to_private_builder`
proves it actually delegates, both when the private builder declines (no
base URL) and when it succeeds.

`test_evolution_canonical_graph.py` (+2): every existing `_finalize_cycle`
test passes a real `ctx` (`NodeContext`), so the three `if marker_id is not
None:` guards in `_finalize_cycle` — around idempotency-marker
read/record on start, on a mid-mutation fault, and on commit — only ever
exercised their True arm. `_finalize_cycle` is also called with `ctx=None`
by any caller outside a durable graph Attempt (it is the parameter's
documented default), which is a real, distinct code path: no NodeRun to
key a marker on, so `marker_id` stays `None` and all three guards must take
their False arm instead. Two tests added, mirroring the existing
success/fault pair but with `ctx` omitted: one proves finalize still runs
and returns a real output with no marker recorded, the other proves a
mid-mutation fault still propagates to the caller with no marker recorded
either (finalize is not made idempotent for callers outside a durable graph
Attempt).

`test_evolution_recovery.py` (+2): `_recovery_resolver`'s fallback chain —
provenance's frozen `evolve_membership_ids`/`evolve_battle_capacity`, else
the Graph's own frozen metadata, else (for battle capacity only) half the
membership count — only ever saw provenance already carrying both fields in
the existing tests, so every fallback branch was unreached.
`test_recovery_resolver_falls_back_to_graph_metadata_when_provenance_omits_the_plan`
covers a Run whose provenance has neither field (an older Run, or one
rehydrated without them), pulling both from the Graph's metadata instead.
`test_recovery_resolver_computes_battle_capacity_when_wholly_absent` covers
battle capacity missing from *both* provenance and Graph metadata, falling
back to `len(membership_ids) // 2`. Both patch `evolution_graph._resolver`
to capture the resolved `membership_ids`/`battle_slots` directly rather than
inferring them indirectly through a resolved node, which is what actually
exercises the branch outcomes instead of just one path through them.

`test_evolution_recovery_cadence.py` (+3): the new restart-recovery cadence
module (`evolution_recovery.py`) had its bootstrap-recovery half's
`CancelledError` re-raise, and its entire timed-wakeup half (success log,
`CancelledError` re-raise, and the failure/log arm) uncovered — the
existing cadence tests only drove the bootstrap-recovery half's failure arm
and a wakeup half that always returned 0 (falsy, so its own success log
never ran). Three tests added:
`test_recovery_cadence_survives_a_failing_wakeup_tick_and_logs_resumptions`
mirrors the existing bootstrap-failure test for the wakeup half (one
malformed tick, then a productive one, asserting both the failure log and
the `resumed=N` success log); `test_run_propagates_cancellation_from_bootstrap_recovery`
and `test_run_propagates_cancellation_from_wakeup` each call `_run()`
directly (not via the task machinery) with one half raising
`asyncio.CancelledError`, proving that guard re-raises instead of falling
through to the broader `except Exception` beside it — cancellation must
still stop the cadence.
