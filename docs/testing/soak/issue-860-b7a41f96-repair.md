# Issue #860 — bounded CI repair validation

## Frozen scope

- Job: `b7a41f965ead435f9ef795d6ca5b3e0c`; issue #860 only; branch `auto-860`.
- Starting head: `63d3582ed81ab09e744bdd96bbe74eb1c746b574` (verified).
- Assigned base: `7334621bf797178dd992622d55aaead33bf9d094` (resolved by diff).
- Initial worktree clean; no incoming edits to salvage.
- Inputs: supplied dispatch snapshot and prior result; no GitHub refresh/mutation.
- Repair targets: exact vulture scan and only identities it actually reports;
  existing soak gates and server rate-limiter/backpressure tests; this handoff.
- No driver `check-*.log` files were present in the supplied job directory.
- Ambiguity: dispatch requests a ledger repair but supplies no current scanner
  failure. Run the exact scan first; do not manufacture ledger edits.
- No new execution or authorization authority will be introduced. An existing
  short host preflight is not an exact-RC production soak.

## Validation checkpoint

- Exact dispatched vulture command passed: 1,336 findings, 1,336 reviewed
  identities, zero unclassified, zero never-allowlist. The scanner reports
  comparison base `56332162cf63`. No ledger amendment is justified.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3,003 files.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  75 passed in 2.73 seconds.
- `git diff --check 7334621bf797178dd992622d55aaead33bf9d094...HEAD`:
  passed; prior whitespace complaint not reproduced against the assigned base.

- `uv run python scripts/check-ratchet-provenance.py`: passed (49 consumers).
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `uv run python` imported the current soak driver and evaluated retained
  `evidence/m3a-round6-shakedown.json`: asserted exactly
  `['sustain_duration', 'exact_rc_artifact']` failed. Also asserted
  `preflight_artifact_check()['ok'] is False`. Observed 90.43 / required
  14,400 seconds; evidence commit `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`.

Commands used 600–1,200 second tool timeouts. No tests were added, removed or
renamed; inventory delta is zero. No inventory or quality ledger edits.

## Architecture reconciliation

Read accepted ADR-081226-a66b, ADR-081626-f383 and ADR-085, and proposed
ADR-081. Preserve Goal → Graph → Run → NodeRun → Attempt. Canonical Run
persistence owns fencing; the accepted fencing ADR explicitly does not define
lease-expiry takeover. Do not invent takeover to satisfy the issue wording or
count schedule admission as physical-work fencing. ADR-085's per-principal
limiting does not waive the issue's replica-selection criterion. Proposed
ADR-081 does not authorize substituting a host emulator for an RC deployment.

## Acceptance audit

| Criterion | Fresh check and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** Read `m3a-load-profile.md:152-164`: multi-user/Workspace, Graph fan-out, successful tools/models, Canvas and background reconciliation remain gaps. The documented preflight is not the required workload. |
| Two supported application replicas | **UNVERIFIED for the RC.** `deploy/docker-compose.prod.yml:26-78` defines two services, but no production deployment was exercised this round. Middleware test instances are not deployed replicas. |
| Sustained saturation, queue growth, reclaim, retry and leak observations | **UNVERIFIED.** Retained JSON lines 163-165 and 221-225 records 90.43 seconds, not the profile's 14,400 seconds. No new long soak executed. |
| No duplicate physical work; Goal reconciliation | **UNVERIFIED.** Retained JSON lines 12-16 cancels the admission-probe Run. `m3a-load-profile.md:197-200` acknowledges no physical Attempt proof or sustained schedule workload. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Counterexample reproduced.** Executed `tests/test_soak_promotion_gates.py:439-488` for both authenticated and unauthenticated cases: each instance independently returns 200,200,429 to the same identity. Production registers this middleware at `packages/maistro-server/src/maistro_server/main.py:628`; `api/rate_limit.py:72-76` constructs an in-memory limiter. Adjacent rate and admission-backpressure tests pass, not cluster-wide enforcement. |
| Complete thresholded application/DB/worker/resource/error telemetry | **UNVERIFIED.** `m3a-load-profile.md:158-164` distinguishes process-group sampling from workers and driver lag from application-loop lag. No current sustained telemetry pack exists in this validation. |
| Active-work kill/restart drain, fencing and recovery | **UNVERIFIED.** Historical rejoin and terminal Run counts do not prove physical-work fencing; no live recovery scenario executed. |
| Long exact-RC artifact/config soak | **Not met.** Current evaluator rejects retained JSON for duration and artifact. `scripts/soak/run_soak.py:635-646` explicitly rejects the host-uvicorn preflight even if run longer. |
| Findings classified to earliest broken invariant | **UNVERIFIED for completeness.** Prior finding references in the profile do not establish complete classification of the unresolved acceptance gaps. No GitHub filing or mutation performed. |
| Published machine/human evidence bound to exact artifact/config | **UNVERIFIED for current RC.** Retained JSON line 70 names a different commit; this handoff is not a replacement soak pack. |

## Outcome and required next work

**BLOCKED on #860 acceptance.** The dispatched CI failure did not reproduce;
there is no evidence-backed vulture repair. Only this handoff changed. No
source, test, runtime config, gate, grant or ledger changed. Do not rerun this
same audit expecting it to produce deployment evidence.

Next requires a selected, immutable promotable artifact/configuration; a
production-path representative workload and application telemetry; resolution
of replica-selection enforcement through the existing security path; and an
actual at-least-four-hour exact-RC soak with physical-work recovery assertions.
Do not start a longer host preflight as a substitute. Any code/config repair
requires a new soak. No missing service or credential is asserted as a blocker
without a check; the demonstrated blocker is the insufficient runner/evidence
and unresolved behavior, not a guessed environment limitation.

Progress: checked 1 issue; done 1 bounded validation/handoff; skipped 0 issues;
command errors 0; issue acceptance remains incomplete. Local commit required
for this report; no integration approval implied.
