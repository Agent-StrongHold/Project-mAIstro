---
inventory-delta:
  packages/maistro-core/tests: +1
---

# issue-1194 parentage-guard branch arc

Round-3 repair for lane auto-1194: the diff-coverage gate against the round's
develop base (`b1f49ce1`) failed on exactly one file —
`agent_delegate_remote.py`, 75% of 4 changed branch arcs (floor 80%), partial
arc at the `_reserve_child` parentage refusal (`parent_node_run is None or
parent_node_run.run_id != parent.run_id` → `RunIntegrityError`). The prior
round's diff-coverage repair note had measured against an earlier merge base
whose diff no longer contains this line set; against `b1f49ce1` the guard's
rejection arm is changed-but-unexecuted. No production code was altered.

## What the repair adds

`test_agent_delegate_remote_child_run.py::
TestParentageIsVerifiedBeforeAdmission::
test_a_delegation_binding_another_runs_node_run_is_refused` — a delegation
whose `ctx.node_run_id` names a real NodeRun of a *different* Run is refused
with `RunIntegrityError` ("does not belong"), before any child Run is
reserved and before anything reaches the A2A transport (`delegator._tasks`
stays empty, no child Run under the delegating parent). This is the
executable form of the #1194 stable-identity criterion: the child Run binds
to the NodeRun that admitted it, so a lease-loss retry can adopt its own
reservation but can never file delegated work under parentage no resume
could trace.

## Same round: develop sync completed

The preserved develop-sync merge was completed in two commits: `05eb4870b`
(resolves the `runs/__init__.py` `__all__` conflict — both develop's
`RunConcurrencyExceeded`/`RunConcurrencyLimits` exports and the branch's
`RunEffectClaim` kept) and `9ec85241a` (merge of `origin/develop`
`b1f49ce1`, the round's stated base, auto-merged).

## Net suite delta (+1 core)

- `uv run pytest packages/maistro-core/tests/graph/nodes/
  test_agent_delegate_remote_child_run.py` — 26 passed.
- `scripts/check-diff-coverage.py` against `b1f49ce1` — exit 0, every
  measured file at or above 90% lines / 80% branch arcs.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `scripts/check-suite-inventory.py` — PASS with this note.
