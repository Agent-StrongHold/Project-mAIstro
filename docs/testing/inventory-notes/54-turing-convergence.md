---
inventory-delta:
  packages/maistro-turing/backend/tests: -1
  packages/maistro-turing/tests: +1
---

# Issue #54 Turing execution convergence

The reachable Turing chat path now resolves a Workspace/Project-scoped canonical
`model.chat` Binding and records the provider call as a canonical Invocation
under the Run's NodeRun and Attempt. Coverage proves successful and unknown
provider outcomes retain Run/NodeRun/Attempt/Invocation correlation, and that
canonical admission failures return a fixed 503 instead of replaying the user
turn outside the execution spine. The chat session exposes prompt preparation and response recording only; it
cannot dispatch through its provider bridge. The canonical chat Node performs
the provider Invocation and then records the response in the session.
No reactor or autonomous cognitive runtime is started by this convergence.

## Salvage record (2026-09-22)

A prior run died mid-merge of `71d0c1120` into this branch. The salvage
completed that merge (single docstring-only conflict in
`maistro/capabilities/invocation.py`, resolved by combining the honest
Turing-reachability statement from this branch with #1310's
lifecycle-authority statement) and repaired the outstanding verifier finding:
`backend/execution.py` `run_chat` previously documented that the HTTP boundary
"may preserve chat availability by executing the domain turn without a Run",
which `routes/chat.py` never does. The docstring now states the proven
fail-closed behavior: admission failures cancel the incomplete admission,
raise `TuringAdmissionUnavailable`, and surface as a fixed 503, and nothing
replays the turn outside the Run/NodeRun/Attempt spine
(`test_create_run_failure_rejects_uncorrelated_chat`,
`test_checkpoint_admission_failure_is_compensated_without_uncorrelated_chat`).
Docstring-only change; no test inventory delta.

Known unrelated failure carried from develop:
`scripts/check-shipped-surface-truth.py --require-clean` still reports
pre-existing Hive-Conductor production-enabled unresolved surfaces (Gate D);
this branch never touched `packages/hive-conductor/` and the failures are
identical on the develop side. After merging develop `ba2f1f077` the count is
six surfaces (develop resolved one of the seven); still develop-side, still
out of scope for #54.

## Merge-forward record (2026-09-23)

A repair run found the worktree mid-merge of develop `ba2f1f077` into this
branch with one conflict in `backend/execution.py`: this branch had added
`invocation_for_run`/`_invoke_chat` (canonical Invocation convergence) while
develop's #1175 re-scoped `_track_admission` to take a per-Workspace
`workspace_id` and sweep with `WorkspaceRetentionScope`. Resolved by keeping
both: our Invocation machinery plus develop's scoped retention signature, and
the auto-merged caller passes `workspace_id=`. The same merge auto-merged a
duplicate `external` key into root `pyproject.toml` `[tool.ruff.lint]` (both
sides had added one); resolved as the union of the Vulture authorization codes
(`V102`, `V105`, `V106`, `V107`). Post-merge validation: 42 turing backend
tests pass, ruff check/format pass, mypy 710 files pass,
`check-m1-convergence-freeze.py --base ba2f1f077` and
`check-convergence-matrix.py` pass. No test inventory delta beyond what each
side already carried.
