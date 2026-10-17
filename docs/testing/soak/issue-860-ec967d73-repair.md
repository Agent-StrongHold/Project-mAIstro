# Issue #860 — ec967d73 repair checkpoint

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD
  `0a63c640542aa4941b20973778da2db32aa9e117`, supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Clean initial worktree; no incoming edits to salvage.
- Process the requested vulture exact-debt-ledger repair and focused soak
  validation only. Candidate edits: this report and
  `quality/vulture-baseline.json` only if the requested scan demonstrates debt.
  No speculative production or test changes.
- Read-only validation scope: repository instructions, relevant ADRs, supplied
  dispatch/prior evidence, `scripts/check-vulture-baseline.py`, CI workflow,
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, adjacent server admission tests.
- Job directory snapshot contains no `check-*.log` files. Prior result is
  BLOCKED, not a verification claim accepted here.
- Ambiguity: no designated RC artifact/configuration is supplied in the lane
  brief. Do not substitute host preflight or a newly invented deployment for
  release acceptance. Check the supplied evidence and report remaining gaps.

## Reproduced checks

- Requested exact vulture scan: exit 0, 1323 reviewed identities / 1323 findings,
  zero unclassified (`/tmp/860-ec967d73-vulture.log`). It used provenance base
  `4aa68edc0b6b`; no unbanked identity exists to amend. Changing the ledger
  without a finding would be cosmetic, so it remains untouched.
- Supplied prior `98a11313.../check-3.log` actually reports a learnings-schema
  test failure (24 statements observed versus 21 expected), not vulture debt.
  Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  exit 0, 37 passed / 6 skipped (`/tmp/860-ec967d73-pg.log`). The historical
  failure is not reproducible at the assigned HEAD; skipped database tests
  are not live concurrency proof.
- Current profile explicitly excludes representative RC workloads and identifies
  its host-process harness as preflight only. No immutable RC/configuration was
  designated by the supplied assignment. Continue focused local validation;
  do not manufacture release evidence.

## Additional executed validation

All commands ran in the assigned worktree with 1200-second command timeouts:

| Command | Outcome | Log |
| --- | --- | --- |
| `uv run ruff check .` | exit 0; all checks passed | `/tmp/860-ec967d73-ruff.log` |
| `uv run ruff format --check .` | exit 0; 3270 files already formatted | `/tmp/860-ec967d73-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | exit 0; 66 passed | `/tmp/860-ec967d73-soak-tests.log` |
| `uv run python scripts/check-suite-inventory.py` | exit 0; 17 suites, 31128 unique identities, no duplicate evidence | `/tmp/860-ec967d73-inventory.log` |

No tests added or changed: inventory delta is zero; no inventory note needed.

## Architecture and reachable behavior

Read repository `AGENTS.md`, documentation authority map, and accepted
ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a, ADR-085. The renewal/reclaim
ADR extends the original lease ADR's deferred boundary; expiry/reclaim cannot
be waived on the strength of the older text. Preserve the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model, with no competing execution
or authorization authority. No architectural change is made this round.

Production `packages/maistro-server/src/maistro_server/main.py:648` installs
`RateLimitMiddleware`; `api/rate_limit.py:93` constructs an instance-local
limiter. The executed regression at `tests/test_soak_promotion_gates.py:439`
uses that middleware for the same credential/client on two instances: each
admits two requests then rejects with 429. This proves independent allowances,
not replica-selection non-bypass or a shared cluster budget. ADR-085's
per-principal keying does not justify advertising cluster-wide enforcement.
Resolving that release claim needs a governed deployment/rate-policy decision,
not an unrelated speculative CI repair.

`run_soak.py:730` returns `ok: False` for host-preflight artifact identity and
line 1552 places it in emitted evidence. The CLI regression executes the
fail-closed gate against synthetic four-hour evidence; no four-hour soak was
performed. Admission tests use canonical receipt identities and the real
router/spine backpressure path, but are not physical-work uniqueness witnesses.
The process-group sampler test observes a real child process; it does not prove
long-window leak freedom. Driver event-loop lag (`run_soak.py:1410`) is not
application event-loop lag.

## Acceptance matrix

| Issue criterion | Executed evidence and remaining gap |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `m3a-load-profile.md:155` explicitly lists missing multi-user/Workspace, fan-out, successful model/tool, Design/Canvas and Goal/worker workloads. Applicability needs the designated RC configuration. |
| At least two application replicas | UNVERIFIED for deployed RC. Two ASGI middleware instances exercised; not two deployed application images. |
| Sustained saturation, queue, reclaim/retry and leak observations | UNVERIFIED. Sampler regressions pass, but no sustained deployed load ran in this round. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | UNVERIFIED. Receipt/admission checks pass; they cannot establish physical execution uniqueness. |
| Rate/security/degraded non-bypass across replica selection | UNVERIFIED at deployment grade; independent production-middleware allowances reproduced. Admission backpressure/recovery tests pass but prove neither shared budgets nor the complete degraded security contract. |
| Full telemetry with explicit thresholds | UNVERIFIED. Profile thresholds exist; application-loop, worker, saturation/reclaim and long-window telemetry are missing at RC grade. |
| Active-work replica kill/restart, drain/fencing/recovery | UNVERIFIED. Boot cleanup regression passes; no active deployed RC replica was killed/restarted. |
| Long soak of exact RC artifact/configuration | BLOCKED / UNVERIFIED. No designated immutable RC/configuration supplied; the existing runner explicitly cannot certify it. |
| Findings filed/reclassified before promotion | Local rate/security correctness disposition above; external filing/reclassification UNVERIFIED and GitHub mutation prohibited. |
| Machine/human evidence tied to exact image/package/commit/config hashes | UNVERIFIED for RC. This source validation report is bound to starting HEAD, not a deployed image/configuration or completed soak. |

## Handoff

Only this report changed. Existing branch work is preserved, not certified by
these focused checks. No merge conflict was present, no ref was fetched, and
no ledger, grant, production code or test was changed. No actual scanner debt
or reproducible historical CI failure justifies a repair in this snapshot.

Verdict: **BLOCKED** on release evidence. Next: provide the immutable RC image,
normalized runtime configuration and applicable workload scope; exercise that
exact topology with physical-work witnesses, complete telemetry and active-work
recovery for the profile's minimum four-hour soak. Reconcile replica-selection
rate semantics before promotion. Repeating CI or lengthening host preflight
cannot close this acceptance gap.

Progress: checked 1 issue, done 0 (acceptance incomplete), skipped 0,
validation errors 0. Local commit is a handoff, not integration approval.
`git diff --check` is required before committing this report.
