---
inventory-delta:
  packages/hive-conductor/backend/tests: +25
---
# 2470 eval-judge scoring permission

## What moved

`packages/hive-conductor/backend/tests` gains 23 collected node IDs: 20 in the
new `test_eval_judge_scoring_authorization.py` and 3 in `test_eval_judge.py`
(the follow-ups below). `test_eval_judge.py` keeps its
36 node IDs: three trigger tests were rewritten in place (same counts) because
the #2470 route contract changed what a successful POST means — the caller now
needs the assigned-and-elevated `eval.score` capability, and the scored target
must be a terminal canonical Run rather than whatever the projection returned.

## Why

Issue #2470 separates eval-judge *scoring* (a billed model effect that
overwrites the shared verdict evidence the optimizer ranks on) from Run *read
visibility* (the #1174 Workspace-scoped inspection). The suite now pins each
gate the fix installs, at the layer that owns it:

- 2 node IDs pin the route-permission table's method split directly
  (`required_permission`) and through the real ASGI middleware (403 without
  the capability, GET untouched).
- 7 node IDs drive the two-principal same-Workspace, administrator, and
  cross-Workspace-link scenes through the real app against the canonical
  Run/Workspace/Project stores — the same rig the #2466 cancel suite uses —
  asserting refusals precede every physical effect (scorer spy stays empty,
  no verdict row, no audit-success entry), plus the five non-terminal
  statuses (parametrized) and the projection-only (no canonical Run) row.
- 4 node IDs pin the evidence contract on the service: a valid verdict is
  terminal evidence that erroring, unparseable, or unavailable attempts
  cannot downgrade; error receipts stay retryable; a valid-verdict retry
  (double-click or post-restart) returns the stored row verbatim with no new
  model invocation.
- 4 node IDs cover provenance and single-flight: the verdict carries actor/
  Workspace/evaluator-version provenance with one audited success, and two
  concurrent authorized scores join one in-flight invocation (one paid model
  effect, identical verdicts, one evidence row).

The route-level happy path in `test_eval_judge.py` additionally asserts the
verdict is keyed by the canonical Run id — not a projection alias — which is
what makes the idempotency and cross-id read guarantees above hold.

## Follow-up (+3): one logical score across producers

Three further node IDs pin the seam where the automatic score meets the
manual one — the chat producer's `_eval_judge_score` and the route's
evidence guard — because a logical score must be one paid model effect and
one evidence row whoever triggers it:

- The chat producer's automatic score keys its evidence by the canonical
  Run the facade result names (`run_id`, #35/#1332) — never a second
  alias-keyed row the optimizer would count twice — and the route's retry
  honors it verbatim with zero further model calls.
- A durable verdict recorded before canonical keying (stored under the
  projection alias) is honored by the POST verbatim after the same
  mutation gate: no second paid score across the upgrade, no rewrite, no
  duplicate row.
- The automatic score carries the same canonical actor/Workspace/
  evaluator-version provenance a manual score records — the turn's
  initiator rides through to `_persist`, so the shared evidence the
  optimizer ranks on is attributable.

## Follow-up (+3): the shared invocation survives its callers

Three further node IDs pin the single-flight contract's cancellation
semantics — the cases where the in-flight dedupe itself could leak a second
paid model effect or drop started evidence:

- Cancelling a joiner must not cancel the shared invocation it joined
  (`asyncio.shield`): the leader completes, the verdict is persisted, and
  exactly one paid model call is made — an abandoned retry tab can no longer
  tear down the score other principals are waiting on.
- Cancelling the leader's caller mid-await keeps the in-flight registry
  entry until the scoring task itself finishes (release via done-callback,
  not caller-scoped `finally`), so the next caller joins the running
  invocation instead of paying for a second one; the registry is empty
  after the task settles.
- A projection-id read serves canonical-keyed evidence only when the alias
  itself is proven — the scoped reader admits the caller to the canonical
  Run and the Run is filed in the projection row's own Workspace — the
  read-side twin of the POST gate's association rule (#2466); every
  refusal degrades to the ordinary "no verdict" answer.

## Follow-up (+2): alias evidence for canonical-ID requests

Two more node IDs close the canonical-ID gap: a POST addressed by canonical
Run id skipped the alias-evidence check entirely, so a pre-upgrade verdict
stored under the projection alias was invisible and the same Run was scored
a second time (billed) with a duplicate evidence row for the optimizer to
count twice:

- A canonical-ID POST resolves and honors the durable alias-keyed verdict
  verbatim — one logical score across the upgrade boundary, no second paid
  model call, no rewrite, no duplicate row.
- Alias discovery itself stays inside the scoped boundary (inspection-seam
  resolution, rows filed in the Run's own Workspace, caller admitted to the
  canonical Run) — a foreign-Workspace link cannot serve or place evidence.
