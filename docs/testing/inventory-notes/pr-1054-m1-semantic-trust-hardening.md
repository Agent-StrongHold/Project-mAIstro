---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/hive-conductor/backend/tests: +3
---
# pr-1054-m1-semantic-trust-hardening

M1 semantic-trust hardening (PR #1054) pins four adversarial repairs with nine
net new node IDs — six in `packages/maistro-core/tests`, three in
`packages/hive-conductor/backend/tests`.

maistro-core (+6), each pinning one mutation this PR exists to kill:

- `tests/graph/durable_runs/test_launch_state_trust.py` (new file): a crash
  after admission but before checkpoint 1 must never execute empty launch
  state (non-empty launches are refused without a durable
  `durable_graph_launch` snapshot), and bootstrap recovery must rehydrate the
  exact admitted inputs/blackboard metadata, detached from caller-owned
  mutable data. Equality is asserted through `thaw_json_value` because
  `GraphExecutionState` deliberately freezes JSON-shaped state (nested
  mappings become read-only proxies, lists become tuples) on both the fresh
  and recovery construction paths.
- `tests/graph/durable_runs/test_pause_redispatch_trust.py` (new file): an
  elapsed answer-gated pause (remote delegation/harness class) must not
  redispatch physical work merely because a timeout timestamp elapsed, while
  an elapsed timer-resumable polling pause still redispatches.
- `tests/events/test_event_replay_trust.py` (new file): replaying the same
  recovery fact twice reuses one canonical Event identity/sequence, and
  mutating a nested legacy-bus Event payload cannot reach the canonical
  envelope (deep-copy before mutable legacy projection).

hive-conductor backend (+3), in `tests/test_dag_condition_trust.py` (new
file): legacy `condition="if x"` remains an unconditional dependency edge with
provenance instead of silently suppressing successors, natural-language
`if x == y` text is not mistaken for a syntactic predicate, and a two-node
legacy DAG with `condition="if x"` still physically runs the successor.

The six core node IDs were counted against the frozen-state equality fix in
`test_bootstrap_recovery_rehydrates_exact_admitted_launch_snapshot`; no
existing node IDs were removed or renamed.
