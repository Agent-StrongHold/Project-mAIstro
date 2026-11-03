# Issue #860 repair checkpoint (d3d43708)

## Frozen scope

- Issue: #860 only; no GitHub mutations.
- Worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `aa0b6048cd6885c34f21548bbf42166650657e3d`.
- Supplied develop base: `a8258ee24dd957d0f0b302db4eee90661fe23439`.
- Clean starting status; no incoming diff to salvage.
- Inputs: supplied dispatch snapshot, prior result, repository instructions,
  relevant ADRs, existing soak harness/tests/profile and CI gate configuration.
- Write scope: this report; evidence-backed fixes to existing soak harness/tests
  and an inventory delta if tests change; `quality/vulture-baseline.json` only
  if the requested exact scan identifies reviewed retained debt.
- No check-*.log files were present in the supplied job directory at initial
  inspection. Prior verification claims will not be treated as executed evidence.

## Ambiguity and assumption

The prompt includes both verifier and writer instructions. The explicit assigned
repair and local-commit requirement identify this as a writer run. No develop
sync conflict is present, so no fetch or merge is warranted. The supplied prior
result is BLOCKED on missing RC deployment evidence, not a merge conflict.

## Progress

The requested exact vulture scan exited 0: 1336 reviewed identities match
1336 findings, unclassified=0, never_allowlist=0. Its default resolved trusted
base was `56332162cf63`. Repeating with
`RATCHET_BASE_REV=a8258ee24dd957d0f0b302db4eee90661fe23439` also passed and
resolved the same merge base.
No missing identity exists to justify ledger amendment or dead-code deletion.
The existing load profile explicitly labels the harness a host-process preflight,
not a production Compose RC soak. No promotion acceptance claimed.

Focused pytest passed: 61 tests in 4.53s across
`tests/test_soak_promotion_gates.py`, `tests/test_prod_stack_boot_contract.py`,
and `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`.
This includes the real middleware's independent-replica allowance counterexample
for authenticated and unauthenticated callers, not a claim of deployed load.
`docker compose -f deploy/docker-compose.prod.yml config --quiet` exited 1:
required `LITELLM_BASE_URL` is missing. No RC deployment was launched or substituted.
An attempted read of `docs/adr/ADR-081-production-deployment.md` was not found;
skipped in favor of the discovered `ADR-081-deployment-backup-dr.md`.

## Architecture reconciliation

Accepted ADR-081226-a66b owns Run/NodeRun/Attempt lifecycle;
ADR-081626-f383 owns Attempt execution leases and fencing;
ADR-082126-f69c rejects a second schedule runtime; ADR-082426-82c7 makes
occurrence admission a canonical Run-store claim. A single raced admission
cannot prove absence of duplicate physical work. No alternative scheduler,
execution authority, authorization path, or state store was introduced.
ADR-081 is still Proposed, not an accepted authority overriding those contracts.
The deployed rate limiter explicitly promises process-local enforcement
(`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30,72-78`).
That narrower promise does not discharge #860's replica-selection criterion.

## Executed validation

All commands ran in this worktree against the assigned code, with only this
report added. No production code, tests, configuration, ledger or grants changed.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1336/1336 identities; repeated with supplied `RATCHET_BASE_REV`, also PASS |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS, 61 tests |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3003 files already formatted |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 49 consumers; delegated gates pass |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check a8258ee24dd957d0f0b302db4eee90661fe23439...HEAD` | PASS; prior whitespace failure not reproduced |
| `docker compose -f deploy/docker-compose.prod.yml config --quiet` | FAIL, missing required `LITELLM_BASE_URL` |
| `uv run python` importing the current soak evaluator and asserting failures for `evidence/m3a-round6-shakedown.json` | PASS: rejects `sustain_duration` and `exact_rc_artifact`; 90.43s versus 14400s minimum |

The last check re-evaluates old evidence; it is not a new soak. That evidence's
`git_head` is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned
HEAD. The missing gateway configuration is an environmental prerequisite, not
a reason to weaken Compose validation or substitute a failing model endpoint.
No tests were added, so no suite-inventory delta is required.

## Acceptance disposition

| #860 criterion | Evidence and disposition |
| --- | --- |
| Representative RC users/Workspaces and request mix | UNVERIFIED: profile lines 152-165 explicitly omit user population, Graph fan-out, successful tool/model, Canvas and Goal/background-worker workloads. |
| At least two deployed application replicas | UNVERIFIED for RC: Compose config fails; host preflight is not the artifact. |
| Sustained saturation, queues, reclaim, retries, leaks | UNVERIFIED: historical 90.43s window is insufficient; current evaluator rejects it. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: admission identity tests pass, but profile lines 197-200 distinguish a cancelled schedule probe from physical-work fencing. |
| Replica-selection-safe rate/security/degraded behavior | NOT PROVEN: passing tests at `tests/test_soak_promotion_gates.py:439-488` reproduce `[200,200,429]` on each separate replica for the same identity. Broader deployed security/degradation remains UNVERIFIED. |
| Complete production telemetry and thresholds | UNVERIFIED: profile lines 158-165 distinguish process groups from container/worker telemetry and driver lag from application loop lag. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED for current RC; terminal Run counts or rejoin alone cannot establish this. |
| Long soak of exact RC artifact/configuration | UNVERIFIED: evaluator rejects historical duration and artifact; `scripts/soak/run_soak.py:635-646` always rejects host preflight as RC evidence. |
| Load findings filed/reclassified to earliest invariant | UNVERIFIED: existing issue references are not proof of complete triage; no GitHub mutation performed. |
| Machine/human evidence tied to current artifact hashes | UNVERIFIED: historical JSON names another commit and no current RC image/config identity was exercised. This report is validation evidence only. |

## Handoff

Verdict: **BLOCKED**. The requested CI ledger failure is not reproducible;
changing its already-exact ledger would be unsupported. The previous deployment
and acceptance blocker remains unresolved. Resume only with a selected immutable
RC artifact/configuration, reachable authenticated model gateway and required
runtime settings, a representative production-path workload and instrumentation,
and an uninterrupted >=4-hour run after any code/runtime-config changes. Resolve
or explicitly govern the replica-budget mismatch without inventing a parallel
authorization mechanism. Publish fresh artifact-bound evidence and triage observed
failures before promotion. No integration approval is implied.

Progress: checked=1, done=0, skipped=0, errors=0; next=external RC prerequisites
and missing production soak coverage. Only this report is to be committed.
