# Issue #860 — job 0af1d125 repair checkpoint

## Frozen scope

Only issue #860 on `auto-860`, starting at
`ac729614febb1a9411145dd10d44fcd1842a2c96`, with supplied base
`eec7a587039e632500942dd390f82d743863f5e3`. Both refs resolved locally;
the initial worktree was clean. No GitHub mutations or ref enumeration.

Write scope: this report; `quality/vulture-baseline.json` only if the exact
requested scan identifies retained unbanked debt; existing #860 inventory
notes only if fresh suite validation demonstrates an incorrect delta.
Read/validation scope: supplied dispatch context and prior result, repository
instructions, relevant accepted ADRs, existing soak harness/profile/evidence,
production rate limiting, and their adjacent tests and CI gates.

## Initial executed result

The requested command
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
passed: 1322 reviewed identities, 1322 findings, zero unclassified or
never-allowlist findings. No ledger amendment is justified by this scan.

No `check-*.log` files were present in the supplied job directory at startup.
Assumption: this is a writer repair, so run focused validation locally rather
than treating absent driver logs or earlier claims as passing evidence.
The supplied prior result is BLOCKED, not a develop-sync conflict; do not
merge an unrelated newer ref or manufacture RC evidence.

Fresh lint and inventory validation passed:

- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 3306 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: all 17 suites match,
  31,489 unique identities; root `tests/` collects 5354. The reported
  5353/5354 discrepancy is not reproduced. No inventory change is warranted.

The supplied issue body contains ten acceptance criteria. The profile explicitly
calls the runner a non-promoting host-process preflight and lists unmeasured
representative-workload and physical-work surfaces. Additional acceptance
validation results follow; passing CI is not an acceptance waiver.

- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: 84 passed (1.82 s).
  This includes both authenticated and unauthenticated independent-replica
  allowance tests using the real production middleware.
- `uv run pytest packages/maistro-server/tests -x -q`: 566 passed, 8 skipped
  (44.26 s), 22 HTTP-status deprecation warnings. The prior aiosqlite thread
  teardown warning did not recur in this execution; this does not prove
  production leak freedom.
- `.github/workflows/vulture-ratchet.yml:82-85` confirms the exact requested
  scanner arguments. No speculative scanner or inventory repair performed.

## Architecture and reachable behavior

Read accepted ADR-085, ADR-081626-f383, ADR-082426-82c7 and ADR-082526-b36a.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`: occurrence claims belong
on canonical Runs; physical execution fencing and renewal/reclaim belong to
canonical Attempts and the existing execution/store lifecycle. The later reclaim
ADR fills the earlier fencing ADR's intentionally deferred expiry boundary.
`Container.recover_abandoned_attempts` delegates to canonical Run-store reclaim
at `packages/maistro-core/src/maistro/container.py:1260`; lack of live soak
observations is not lack of architectural authority to reclaim.

The application installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`. The middleware creates
an in-memory limiter per instance and explicitly documents N-times aggregate
allowance (`api/rate_limit.py:32-37`). The executed regression at
`tests/test_soak_promotion_gates.py:477-526` exhausts one instance with
`[200, 200, 429]`, then obtains another `[200, 200, 429]` from its peer for the
same identity. This is genuine local enforcement, not proof of a
replica-independent principal budget. ADR-085 does not waive #860's
replica-selection criterion. Changing this authority is not an evidenced
vulture repair; a coordinated solution must preserve canonical authentication.

The production Compose file declares two replicas (`deploy/docker-compose.prod.yml:26-76`)
and requires an external model gateway. Merely declaring that topology, or
executing two ASGI middleware instances, is not a deployed exact-RC soak.

## Acceptance evidence

Executed `uv run python` to import the current soak evaluator and assert that
`docs/testing/soak/evidence/m3a-round30-shakedown.json` fails exactly
`['sustain_duration', 'exact_rc_artifact']`. Both assertions passed, including
that the current `preflight_artifact_check()['ok'] is False`. The recorded
window is 420.08 seconds, versus the profile's 14,400-second minimum, on
historical commit `c4f45b309fd622f2e8a4b315dad35e721d81aad3`, not this candidate.
`git diff --check` also passed.

| Issue acceptance criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED** in full. `m3a-load-profile.md:167-183` explicitly omits concurrent users/Workspaces, Graph fan-out, successful tools/models, Canvas and sustained Goal reconciliation. |
| At least two deployed application replicas | **UNVERIFIED for current RC**. Compose declaration and executed ASGI tests are not deployed-image evidence. |
| Sustained pool/queue/reclaim/retry/leak/restart observations | **UNVERIFIED**. Fresh evaluator rejects the 420.08-second historical window; long-window and pool/reclaim observations remain absent from this validation. |
| Exactly-once/fenced operations do not duplicate physical work | **UNVERIFIED**. Historical occurrence probe cancels its admitted Run without execution (`m3a-round30-shakedown.json:11-15`); admission uniqueness is not physical-work or Goal reconciliation proof. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **NOT PROVEN**. Executed real-middleware regression reproduces independent budgets for both identity classes. Passing local 429 checks cannot establish this criterion. Sustained security/degraded behavior remains unverified. |
| Complete telemetry with explicit thresholds | **UNVERIFIED in full**. Profile contains partial thresholds, but identifies driver-loop versus application-loop and process-group coverage limits; no current RC production telemetry was gathered. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. Historical process exit/rejoin and terminal Run counts are not active physical-work fencing/recovery evidence. |
| Long-running exact RC artifact/configuration | **NOT MET by evaluated evidence**. Current evaluator rejects both duration and exact artifact. No selected immutable promoted RC/configuration was supplied. |
| Findings filed/reclassified at earliest broken invariant | Local blockers preserved here; **external filing/reclassification UNVERIFIED**. No GitHub mutations permitted or performed. |
| Machine/human evidence tied to exact promoted hashes | **UNVERIFIED for current RC**. Historical JSON is explicitly tied to an older host-process preflight; no new promotion-grade artifact evidence was produced. |

## Outcome and handoff

**BLOCKED**. The assigned vulture failure and prior inventory discrepancy do
not reproduce; do not amend passing ledgers or counts merely to create a repair.
The previous acceptance block remains unresolved, not a develop-sync conflict.
A longer execution of the unchanged preflight cannot resolve its artifact or
workload gaps. No live soak was attempted, and no production acceptance is
claimed from unit tests.

Changed file: this report only. No code, tests, historical evidence, gates,
ledgers, grants or inventory counts changed. Existing meaningful regressions
ran afresh; no test additions require an inventory-delta note.

Next: select the immutable RC image/configuration and enabled workload surfaces;
resolve replica-budget requirements via the existing canonical authentication
and limiter path; supply production-path workload and application telemetry;
execute the >=4-hour exact-topology soak with physical-work, lease reclaim,
Goal reconciliation and active-work recovery observations. Preserve the existing
canonical execution authority throughout. Re-dispatching the unchanged vulture
repair cannot produce missing promotion evidence.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
blocked 1; failed validation commands 0. Commit this checkpoint locally; no
push or other remote mutation.

