---
inventory-delta:
  packages/maistro-core/tests: +8
  packages/maistro-turing/backend/tests: +12
---
# PR 1622 — one canonical Turing chat retention window

Turing's per-Workspace admitters share one ordered process budget and sweep
lock. Each entry retains its admitting Workspace's validation and liveness
checks. The existing limit, dispatch-pending/CREATED/QUEUED/live-Attempt
shields, oldest-first ordering and store integrity refusals remain canonical.
The dispatch seam sweeps again when each turn settles, including compensated
admission and cancellation exits.

Core gains eight parameterized cases: refusing a shared budget across different
stores or limits, and rechecking Workspace and chat provenance before deleting
a previously tracked Run, plus preserving the already-created identity without
an extra fallible/cancellable read before returning admission, and proving a
forged Run snapshot cannot authorize foreign-Workspace or task deletion. Turing gains the final-burst regression plus eleven
composition cases: five users sharing two slots, seven liveness states across
Workspaces, and foreign-Workspace/task/missing-Run tracking refusals. The
existing final-burst test now uses three separate users and admits no fourth
turn. The missing-entry test registers a real Run before simulating external
deletion. No tests were removed or skipped by this change.

Fail-first evidence: restoring the reviewed PR's independent per-Workspace
window wiring and summed `retained` projection makes the five-user and
three-user final-burst tests fail (five and three retained against two).
Normal shared composition passes these same assertions. All test stores are
isolated in-memory fixtures; no live user data is accessed or deleted.

This change does not close the broader retention/reference-integrity work in
#1175. In particular, `InMemoryRunStore.delete_run` does not reclaim Graph
continuations, unlike the separate purge API. The existing shared continuation
store and all current security/cancellation paths are preserved; this PR does
not add purge authority or a new retention policy. #131 is historical, already
closed independently.
