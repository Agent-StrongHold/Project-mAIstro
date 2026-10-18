---
inventory-delta:
  packages/maistro-core/tests: +12
---
# #1897 — the durable Graph re-entry carries the node's own current pause

`executor._build_ctx` used to rebuild `resumed_pause` only from
`hitl_answers[node_id]["_pause"]` — the server-stamped copy of a pause an
answer already settled. A node that pauses again after its answer (an elapsed
poll re-parking beside a stale answered approval) read the old answered pause
instead of its own current `graph_state.metadata["pauses"][node_id]` entry,
and every carry was a shallow dict copy over the frozen
`MappingProxyType`/`tuple` state containers rather than detached JSON.

`packages/maistro-core/tests/graph/durable_runs/test_resumed_pause_context.py`
(+12) drives the real durable Graph/Attempt path — `run_durable_graph`,
`submit_hitl_answer`, `resume_durable_graph` — with a scripted probe node and
fixed timestamps (timer pauses carry fixed past `resume_at` values so
`_requires_continuation_redispatch` re-dispatches them without a wall clock;
HITL deadlines sit far future so the deterministic `at=` answer is never
refused as expired):

- an elapsed pause's arbitrary metadata and wrapper `resume_at` arrive
  unchanged at the same node on resume, as ordinary `dict`/`list` containers
  (not the frozen shapes);
- the wrapper `resume_at` wins a conflicting same-name value the node wrote
  inside its own pause metadata;
- a current ordinal-1 pause beats the prior ordinal-0 answered pause on the
  same node — deleting the current-pause-first branch flips the assertion to
  the stale ordinal-0 payload (verified by mutation);
- an absent current pause preserves the existing answered-`_pause` fallback
  byte for byte;
- in a parallel two-branch frontier whose singleton `pause` names `right`,
  each member carries only its own pause (`left` never sees the singleton's
  payload);
- a first reach with no pause anywhere keeps the previous context shape (no
  `resumed_pause` key, `hitl_answers`/`synth_depth` intact);
- a present-but-malformed pauses container, entry (`None` counts as present),
  or metadata field terminalizes the resume `PhysicalExecutionError` before
  the node ever executes, with a stale answered pause available — it is never
  silently borrowed;
- mutating the carried pause (nested mapping and list) — through a real
  answered-`_pause` carry and through a focused `_build_ctx` unit test over
  the frozen state — leaves the persisted record byte-identical.

Existing answer-driven HITL and pause-reason waker coverage is unchanged and
passes (`packages/maistro-core/tests/graph/durable_runs/`: 615 passed,
39 skipped).
