# Issue #860 — assigned CI repair 106579cb

## Frozen scope

- Writer lane: issue #860 only, branch `auto-860` in the assigned worktree.
- Starting HEAD: `b996f01367ee20a84a6e4321e67b1d1705b98bcb` (resolved and matched).
- Base: `c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250` (resolved by diff).
- Dispatch source: job `106579cb6add4f45a3fade59dfa4cbd6/dispatch-context.json`;
  no remote re-enumeration or mutations.
- Clean starting worktree; no uncommitted salvage needed.
- Repair candidates frozen to `quality/vulture-baseline.json` and identities
  actually reported by the mandated scan; otherwise this evidence note only.
- Acceptance review scope: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `tests/test_prod_stack_boot_contract.py`,
  `packages/maistro-server/src/maistro_server/api/rate_limit.py`,
  `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`,
  `docs/testing/soak/m3a-load-profile.md`,
  `docs/testing/soak/evidence/m3a-round6-shakedown.json`, and governing ADRs.

## Initial observations

No `check-*.log` files were supplied in the assigned job directory at entry.
The prior result reports BLOCKED but is not accepted as current validation.
The assignment is a writer/CI-repair lane, not the read-only verifier role.
The requested CI repair does not authorize changing the release profile,
weakening the duration/topology gates, or replacing the execution authority.

## Validation

The exact required vulture scan passed on the assigned head: 1342 findings,
1342 reviewed identities, zero unclassified and zero never-allowlist findings.
No unbanked identity or genuinely dead code was reported, so no ledger amendment
is warranted. Repair write scope is now this report only; no test additions or
inventory deltas. No promotion claim is made.

Fresh commands executed in this worktree (all exit 0):

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1342/1342 identities; exact arguments confirmed in both CI workflows |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | 2985 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 61 passed, no skips |
| `uv run python scripts/check-doc-links.py` | Zero broken relative links |
| `git diff --check c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250...HEAD` | PASS; prior whitespace failure not reproduced |

A fresh `uv run python` import of the current soak module evaluated retained
`m3a-round6-shakedown.json`: 90.43 seconds against the required 14400 seconds;
failed checks are exactly `sustain_duration` and `exact_rc_artifact`. Assertions
also verified the current artifact check returns false. These are evaluator
checks, not a new load run. Tool output is the execution record for this round.

## Architecture reconciliation

Read accepted ADR-081626-f383 (Attempt leases/fencing) and ADR-082426-82c7
(occurrence identity). The canonical Run store owns authority; occurrence
admission uniqueness is not physical-work uniqueness. The fencing ADR explicitly
does not define expiry takeover, so no competing recovery scheduler is introduced
to satisfy the issue wording. ADR-081, referenced by the profile, was also read:
its front matter is **Proposed**, not accepted governance.

The production middleware explicitly documents process-local budgets and creates
`InMemoryRateLimiter` per instance (`rate_limit.py:25-30,72-78`). The passing
production-middleware counterexample observes `[200, 200, 429]` on each of two
instances for the same identity; it demonstrates local enforcement, not a shared
budget. The issue's non-bypass claim needs a release-contract resolution, not a
speculative ledger edit or another authorization path.

## Acceptance review

| Issue criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC profile | UNVERIFIED: profile lines 152-167 explicitly lack concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Canvas and reconciliation coverage. |
| At least two application replicas | UNVERIFIED for deployed RC: passing boot-contract tests check rendered configuration and startup validation, not a live two-replica deployment. |
| Sustained saturation, growth, expiry/reclaim, retries and leaks | UNVERIFIED: retained window is 90.43 seconds, and no new long production run was executed. Expiry/reclaim must respect the accepted ADR boundary. |
| Schedule/task/Run/Attempt and Goal physical-work uniqueness | UNVERIFIED: admission-probe tests pass but cannot prove physical execution uniqueness. Profile lines 197-201 explain the schedule probe cancels its queued Run without executing it. |
| Rate/security/degraded behavior without replica-selection bypass | NOT MET for a cluster-wide allowance: both actual middleware instances independently allow requests in the passing counterexample at `tests/test_soak_promotion_gates.py:439-488`. Backpressure tests pass; full concurrent security acceptance remains UNVERIFIED. |
| Full telemetry and explicit thresholds | UNVERIFIED: sampler tests cover wrapper/child RSS and descriptors, not a sustained production observation or application-loop latency/complete worker coverage. Profile lines 158-167 retain these gaps. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: neither rendered LB policy tests nor process rejoin counters demonstrate no physical loss/duplication; no current deployed recovery run. |
| Long exact-RC artifact/config soak | NOT MET: current runner's artifact gate remains false at `scripts/soak/run_soak.py:635-646`; executed CLI tests reject even synthetic four-hour preflight evidence. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness: no new load observation or remote issue mutation occurred. Historical classification cannot establish completeness for a current RC. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for current RC: retained preflight is not current image/config evidence. This report records validation only. |

## Handoff

**BLOCKED.** The explicit CI-repair scan has no defect to repair. No source,
ledger, grants, gates, tests, inventory counts, or historical soak evidence were
changed. Only this report is added and committed locally. The previous block is
not resolved by the passing scanner: select an immutable RC and representative
production profile, provide production-path workload/telemetry and physical
Attempt/recovery proof, resolve the rate-limit scope discrepancy, then execute
a new long exact-RC soak. Do not repeat the ledger-repair lane absent a newly
failed scan. No GitHub mutations were performed.

Progress: checked 1 issue; done 0 issue acceptance completions; skipped 0;
errors 0 final validation-command failures. An initial staged whitespace check
caught a trailing blank line in this new report; corrected before commit.
Next: production-soak prerequisite work.
