# Issue #860 — cbeb42cc repair checkpoint

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting head: `b91f3a591cb527f2f609f97813523665f4c86d70`.
- Supplied base: `b672b799aba6d3db9edc3e1be18b1a3335dd3bc0`.
- Worktree was clean at entry; no incoming edits to salvage.
- Inputs: supplied dispatch-context.json, prior result if present, repository instructions,
  relevant ADRs, existing soak implementation/tests/evidence, exact vulture gate.
- Planned write set: this report; `quality/vulture-baseline.json` only for reviewed
  identities found by the explicitly authorized CI-repair scan; genuinely dead code
  only if demonstrated by that scan. No new runtime architecture or promotion claim.
- No check-*.log files were present in the supplied job directory at entry.
- Ambiguity: this is a writer repair assignment, not a verifier-only assignment.
  Proceed with focused validation and a local commit; no remote mutations.

## Progress

Initial inspection confirms the assigned head. Acceptance requires an exact-RC,
long-running, multi-replica soak; prior artifacts cannot establish current acceptance.
Exact requested vulture scan passed: 1,338 findings / 1,338 reviewed identities,
zero unclassified and zero never-allowlist findings (exit 0). Therefore no ledger
amendment or dead-code repair is supported by the current evidence. The prior
result was read; its BLOCKED conclusion will be independently checked below.
The profile explicitly identifies the runner as a host-process preflight and lists
representative-workload gaps. No exact-RC execution has been established.
An exploratory ADR-index glob did not exist (`rg` exit 2); use actual ADR files,
not a guessed index.

Focused validation passed: Ruff check, Ruff format check (2,943 files),
`git diff --check b672b799aba6d3db9edc3e1be18b1a3335dd3bc0 HEAD`, and
61 tests across `tests/test_soak_promotion_gates.py`,
`tests/test_prod_stack_boot_contract.py`, and
`packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`.
The passing tests include real production-middleware counterexamples: identical
principals exhaust replica 1 and receive a fresh allowance on replica 2.
These tests demonstrate a blocker, not a cluster-wide enforcement success.

Read accepted ADR-081226-a66b (one Run/NodeRun/Attempt lifecycle) and
ADR-081626-f383 (durable Attempt authority and stale-writer fencing; explicitly
not implicit expiry takeover), plus proposed ADR-081 deployment guidance.
Reconciliation: #860 cannot justify a second scheduler or invented reclaim
semantics, and admission deduplication does not prove physical-work fencing.
No runtime or authority changes are made in this repair.

## Executed commands and outcomes

All validation used the assigned worktree with 1,200-second command timeouts.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,338 exact identities. Output retained locally at `/tmp/issue-860-cbeb42cc-vulture.log`. This is the exact workflow command; its resolved trusted base was `cd5618223cbd`, not a claim that the supplied develop tip is an ancestor.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2,943 files.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 61 tests in 2.39 seconds.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 49 quality JSON consumers have explicit provenance (delegated checks passed).
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `git diff --check b672b799aba6d3db9edc3e1be18b1a3335dd3bc0 HEAD`: PASS; supplied historical whitespace findings do not reproduce against this supplied base/head.
- `git diff --check`: PASS.
- `uv run python` importing the current soak module and evaluating retained round-6 JSON: assertion PASS that failures are exactly `sustain_duration` and `exact_rc_artifact`. Observed 90.43 seconds; minimum 14,400; evidence head `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head. Current `preflight_artifact_check()` reports `ok: false`, `host-uvicorn-preflight`.

## Acceptance assessment

| #860 criterion | Current executed evidence / disposition |
|---|---|
| Representative users/Workspaces and workload mix | UNVERIFIED. Profile exists but explicitly lacks multiple users/Workspaces, fan-out, successful model/tool/Canvas traffic and Goal/background-worker coverage (`m3a-load-profile.md:152-165`). |
| At least two supported application replicas | UNVERIFIED for this RC. Production Compose defines two services; focused boot-contract tests pass, but no current production deployment was exercised. |
| Sustained saturation, queue, reclaim, retry, memory and leak observations | UNVERIFIED. Retained evidence has 90.43 seconds and fails the 14,400-second gate. No new soak was run. |
| Schedule/task/Run/Attempt/Goal no duplicate physical work | UNVERIFIED. Probe regression tests verify admission evidence validation, not physical execution. Existing schedule probe cancels its queued Run (`run_soak.py` and profile lines 197-200). |
| Security/degraded behavior and no replica-selection bypass | NOT MET as a cluster-wide budget claim. Both authenticated and pre-auth production-middleware counterexamples pass (`tests/test_soak_promotion_gates.py:439-488`): replica 2 admits after replica 1 is exhausted. `main.py:593` installs this middleware in the application. The middleware documents process-local scope; local enforcement is not proof of the stronger #860 claim. |
| Required telemetry and explicit thresholds | UNVERIFIED in production. Profile defines some thresholds, but driver-loop latency is not application-loop latency, and worker/reclaim/long-window observations remain missing. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED for the RC. Retained rejoin data cannot prove physical-work fencing; no active production work was killed/restarted in this round. |
| Long-running exact RC artifact/configuration soak | NOT MET. Current evaluator rejects retained evidence; `run_soak.py:635-646` explicitly rejects its own host-process topology as exact-RC proof. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for a complete production soak. Existing local records are preserved; no GitHub mutation was made. |
| Published human/machine evidence bound to exact hashes | UNVERIFIED for the current RC. Historical JSON and human profile exist, but the evaluated JSON is bound to an older commit and lacks current production artifact evidence. |

## Handoff / residual risks

Verdict: **BLOCKED**, not merge-ready. Only this report changed; no tests were added,
so no inventory delta note is required. No ledger changes are justified by the
passing exact scan. No guessed RC ref, image digest, credentials or reclaim
semantics were introduced. A longer run of this preflight would still fail the
artifact gate, so repeating it is not a repair of the acceptance blocker.

Next: identify the immutable RC and runtime configuration with the release owner;
implement/exercise the representative workload against that actual production
artifact, resolve or explicitly govern the rate-budget requirement, then collect
at least four hours of hash-bound evidence including physical fencing/recovery
and missing application telemetry. Any code/runtime-config change requires a new
soak. This round provides no integration approval.

Progress: checked 1 assigned issue, done 0 acceptance-complete issues, skipped 0,
errors 0 validation failures; one exploratory missing-index glob was recorded
above. Finish with a local report commit and confirm a clean worktree.
