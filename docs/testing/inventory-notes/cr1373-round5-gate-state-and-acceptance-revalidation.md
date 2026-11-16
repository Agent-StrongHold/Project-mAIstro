---
inventory-delta:
  tests/: +0
---

# Round-5 validation at `ec2931d54`: pushed-head gate state and independent acceptance re-derivation

Validation round for the CR1373 lane (PR #1373, branch `auto-62`, head
`ec2931d547080fa63350aa98c6d2d9f82b00a8f9`, develop base `f8a2df966a1d`).
No source, test, workflow or ledger file changed in this round. Three things
are re-derived rather than inherited from prior rounds' notes.

## 1. The lane's named gate is green at the pushed head

The round's dispatch named one CI gate failure to repair: "Container scan +
SBOM + cosign". At `b455001e2` (the pushed head, `origin/auto-62`), the
captured check-runs show that gate **success**, along with `exact-debt-ledger`
and `block` success and every `Quality/*` gate success — the repair chain
`b868e47f9` -> `4295a40c1` -> `b455001e2` landed. CI itself, not a local
rebuild, is the evidence for this leg.

## 2. The three remaining failures at `b455001e2` are diagnosed, not guessed

- `hive-conductor-e2e-ui` (job 133264998608): one test failed, twice
  (`tests/e2e/rsi-polling-resilience.spec.ts:459`, "a prolonged outage backs
  off exponentially"): `Expected <= 10, Received 1000` — the first backoff
  stamp deviated by exactly one 1000 ms clock step from `flipEnd + 7500`.
  The branch diff vs `origin/develop` touches no frontend, RSI-polling, or
  hive RSI-endpoint file; the same gate **passed** at `b868e47f9` and
  `4295a40c1`, whose frontend code is identical to `b455001e2`'s. A
  latency-bound UI assertion failing on a diff that cannot reach it is the
  documented flake class (AGENTS.md: "tests that assert a transient UI state
  or a latency bound, fail on PRs that cannot have caused them").
- `Coverage gate (publish-set floor + diff coverage)` (job 133270152047):
  failed inside `combine` because
  `tests/test_devskim_scan_scope.py::test_no_shipped_source_file_is_excluded_from_the_scan`
  exceeded the 30 s pytest-timeout (stack parked in `yaml/reader.py` reading
  the workflow). The test walks only `SHIPPED_TREES` (`packages/*/src`,
  hive backend/frontend, canvas frontend, `templates`, `scripts`) — this
  round adds nothing under those trees (new notes live in `docs/`, suffix
  `.md`). Locally it passes in ~17 s, and the gate **passed** at `b868e47f9`
  and `4295a40c1`. Slow-loaded-runner flake, not a diff effect.
- `integration-scope` (job 133264574926): a pure waiter — its log ends with
  "`hive-conductor-e2e-ui is required by integration scope but concluded
  failure`". It inherits leg 1's verdict and nothing else.

No code repair is made for these legs: the only honest fixes are a CI re-run
(mutation, outside this lane's authority) or edits to files this PR does not
touch.

## 3. The M1-E2 acceptance behavior is re-proven from this tree

Re-ran locally (driver logs cross-checked, not substituted):

- Full `packages/maistro-core/tests/graph/durable_runs`: **795 passed,
  76 skipped, 4 xfailed** — includes `test_m1_e2_recovery_convergence.py`
  (parked-waker mechanical proof `PAUSE_REASON_WAKERS`, external-result crash
  window, stranded-Run replay), `test_cross_store_crash_reconciliation.py`
  and `test_stores_gaps.py` (120 passed / 31 skipped for those three files
  together).
- `packages/maistro-core/tests/a2a`: 295 passed (delegation wake seam).
- Conductor recovery (`test_dag_recovery.py` +
  `test_registered_dag_recovery.py`): 28 passed.
- `packages/maistro-core/tests/graph/nodes/test_agent_delegate_remote.py`:
  21 passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI-exact args): clean,
  1238 reviewed identities = 1238 findings, unclassified 0.
- mypy strict, canonical path set: Success, no issues in 952 files.
- ruff check + format on the changed packages: clean.

Reachability chain read from production code (not tests): the conductor tick
(`canonical_dag_runner.py:586/:604`) and registered-DAG recovery
(`registered_dag_recovery.py:96/:118`) call `poll_external_results` /
`resume_due_graph_runs` / `recover_queued_graph_runs`; each calls
`_reconcile_if_supported` -> `CanonicalDurableRunStore.reconcile_persistence`
(`canonical_store.py:394`), the bounded stranded-RUNNING/PAUSED re-derivation;
recovery dispositions reach the canonical Event stream through
`CanonicalRecoveryEventSink` wired at `canonical_dag_runner.py:553/:601/:609`;
`Container.wake_external_graph_result` (`container.py:2326`, registered
`:2372`) is the production answer-path waker; the production container wires
`graph_run_store=CanonicalDurableRunStore(...)` (`container.py:3068`). The
spine-only sweep `reconcile_stranded_runs` (`runs/reconciliation.py:585`)
is covered by `test_m1_e2_recovery_convergence.py` and its dispositions are
the same `AttemptLifecycleReconciler` the store sweep uses.

Ledger integrity after the develop merge: `git diff --numstat origin/develop
-- quality/` shows only `ac-state-notes/auto-62.json` (+17) and
`image-pins.json` (9/9); `vulture-baseline.json` is byte-identical to
`origin/develop` (multiset preserved). Child #1151 is **closed** (captured
evidence); merged PRs #1952 (harness wait wake, refs #1192) and #2144
(recovery-claim fencing) are in the base.

## Not claimed

OS-kill process-restart durability, cross-release checkpoint compatibility,
and the closure of #837/#1192 (their states are outside this capture's scope)
remain UNVERIFIED, as prior rounds' notes record. Flaky legs 1–2 need a CI
re-run at the pushed head to flip green on GitHub; the evidence here is that
they are not caused by this diff. This round performs no push, PR, review or
issue mutation, and grants no integration approval.
