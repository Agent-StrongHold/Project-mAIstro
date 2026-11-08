# Issue #860 — repair checkpoint ab268f36

## Frozen scope

- Issue #860 only; branch `auto-860`, clean starting head
  `3f389d299d561bd86028d07de2cb7b84fca251fb`.
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inspect supplied dispatch snapshot and prior check-3/result artifacts, repository
  instructions, relevant ADRs, soak driver/profile and adjacent promotion tests.
- Run the explicitly assigned vulture gate; amend only reviewed retained identities
  if that gate produces evidence. No speculative runtime changes or ledger edits.
- Candidate edit scope: this checkpoint and `quality/vulture-baseline.json` only.
  No tests are added in this bounded CI repair.

## Initial observations

- `git status --short`: clean; `git rev-parse HEAD`: matches assigned head.
- Current job directory contains no check-*.log files at initial inspection.
  The supplied prior check-3.log and result.json exist and will be inspected.
- The issue has ten acceptance criteria, including an exact-RC long-running soak.
  Historical shakedowns do not prove the current artifact's acceptance.
- Ambiguity: dispatch calls this a CI repair but also requests full acceptance.
  Proceed with the explicit vulture repair and record unproven acceptance rather
  than inventing a release candidate/configuration or approving promotion.

## Reproduced CI results

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed
  identities / 1323 findings; zero unclassified or never-allowlist findings.
  No ledger amendment is supported by this scan; ledger left untouched.
- Prior check-3.log asserts 24 schema statements versus 21 expected. Fresh
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: PASS, 37 passed / 6 skipped. The reported failure does not reproduce;
  no speculative schema/test change is warranted. Skips are not live DB proof.
- Supplied previous result is BLOCKED on exact-RC acceptance, not an unresolved
  merge conflict. No develop fetch/merge is warranted by this evidence.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 66 tests. Includes real production limiter instances (ASGI transport),
  independent replica allowances, fail-closed exact-artifact checks and retryable
  task concurrency backpressure. This is not deployed multi-replica load proof.

## Architecture and acceptance evidence

Read repository AGENTS.md, the load profile, driver promotion gate and adjacent
production-middleware tests. Accepted ADR-081226-69ee requires Graph snapshots
and NodeRun/Attempt identity. ADR-081626-f383 places lease authority in the
canonical Run store; the deployment ADR-081 is Proposed, not an authority to
supersede accepted execution contracts. No scheduler, authorization or execution
path is changed here.

Read the later accepted ADR-082526-b36a: TTL renewal and reclaim extend the
older fencing contract. Do not treat the older ADR's deferred expiry paragraph
as a waiver of the issue's recovery criterion. ADR-085's per-principal keying
does not itself supply cluster-wide limiter state.

Production wiring confirmed: `maistro_server/main.py:648` installs
`RateLimitMiddleware`; `api/rate_limit.py:93` constructs an instance-local
`InMemoryRateLimiter`. The executed test at
`tests/test_soak_promotion_gates.py:439` demonstrates the same credential/IP
receiving fresh allowance on replica two after exhausting replica one. Thus
local 429 coverage is not proof of the issue's non-bypass criterion.
`deploy/docker-compose.prod.yml:26` and `:75` define two application services,
but that reference topology is not a designated immutable RC deployment.

| Issue acceptance criterion | Evidence / disposition this round |
| --- | --- |
| Representative RC profile | UNVERIFIED: `m3a-load-profile.md:155` explicitly lists missing multi-user/Workspace, Graph fan-out, successful tool/model, Canvas and Goal traffic. No selected RC configuration closes these gaps. |
| At least two deployed application replicas | UNVERIFIED: Compose declares two, but no RC deployment run was executed. ASGI limiter instances are not deployed replicas. |
| Sustained saturation, growth, expiry/reclaim, backoff and leaks | UNVERIFIED: unit checks do not exercise a sustained window. |
| Physical-work uniqueness across canonical admissions/reconciliation | UNVERIFIED: admission identity and fence mechanisms alone are not a physical-work witness under concurrent deployment load. |
| Rate/security/degraded non-bypass | Independent per-replica allowance reproduced with actual middleware in the 66-test run; cluster non-bypass and deployed security/degraded acceptance remain UNVERIFIED. |
| Complete telemetry with pass/fail thresholds | UNVERIFIED: no current RC observations; profile distinguishes driver loop lag from application loop lag and lists missing worker/pool observations. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED: no production restart performed; promotion tests only establish rejection of absent/bad gate evidence. |
| Long soak of exact RC artifact/config | UNVERIFIED / BLOCKED: `scripts/soak/run_soak.py:730` explicitly returns a failed exact-artifact check. Tests execute the fail-closed path, including a synthetic four-hour preflight. No designated immutable RC image/config supplied. |
| Findings disposition before promotion | Local findings recorded here; external filing/reclassification UNVERIFIED and no GitHub mutation permitted. |
| Hash-bound machine/human soak evidence | UNVERIFIED for this RC. Historical evidence cannot certify the current artifact. This validation note is not a soak evidence pack. |

## Final checkpoint

- `uv run python scripts/check-suite-inventory.py`: PASS, all 17 suites,
  31128 unique identities, zero duplicate evidence.
- `git diff --check`: PASS before final note update.
- Only this report changed. No runtime, test or ledger edits; no inventory delta
  needed because no tests were added/removed. Existing work preserved.
- Verdict: **BLOCKED**, not merge-ready. The assigned stale CI failure and
  requested vulture scan are checked successfully, but release acceptance is
  not proven. Avoid another speculative CI repair for this same passing scan.
- Next input required: designated immutable RC image/config and representative
  workload scope; then an exact-topology runner and >=4-hour observations with
  physical-work/recovery witnesses and full telemetry. A longer host preflight
  cannot substitute for that work.
- Progress: checked 1 issue, done 0 (acceptance incomplete), skipped 0,
  reproduced command errors 0. Finish by committing this report locally.

