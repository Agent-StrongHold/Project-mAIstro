# Issue #860 — assigned-head CI repair revalidation

## Frozen scope

- One item: issue #860, branch `auto-860`, starting head
  `f13b43461111fcd173cc25127f4192bc5e8c6c6b`.
- Assigned base resolves to `4e7ef1ab1ceb41edb175baa06557ab18f4657162`;
  no develop-sync conflict was reported and no integration is attempted.
- Inspect existing `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/`, adjacent task backpressure / PG learnings tests,
  production rate limiter, relevant ADRs and vulture checker/ledger.
- Edit this handoff and only evidence-backed issue-860 or requested vulture
  repairs if validation establishes a defect. No unrelated base divergence work.
- Initial worktree was clean. Prior result was read, not accepted as fresh proof.
- Job `94915f75b5334cd4b55c797762bf9632` contains no `check-*.log` files at
  initial inspection; driver checks are unavailable, not assumed green.

## Ambiguity / assumption

No exact release-candidate image/configuration is assigned. Existing host-process
preflight evidence cannot substitute for a designated production-artifact soak.
Revalidate local gates and report any remaining promotion criteria as unverified;
do not invent release designation or file GitHub findings (mutations prohibited).

## Results

- Required vulture command passed freshly (1800-second timeout): 1402 findings /
  1402 reviewed identities, unclassified=0, never_allowlist=0. No unbanked
  identities were emitted, so no speculative code or ledger amendment is justified.
- Read accepted ADR-081426-1f7c (Attempt physical identity), ADR-081626-f383
  (canonical store fencing), ADR-082426-82c7 (occurrence admission), ADR-085
  (principal rate limits). Admission-only probes cannot prove physical execution;
  no competing scheduler, authority or authorization path is introduced.
- Source inspection confirms per-instance `InMemoryRateLimiter` in production;
  the historical shared-store claim has already been corrected at this head.
  Complete exact-RC acceptance remains distinct from preflight regression gates.

## Fresh executed validation

Commands used 1800-second timeouts in the assigned worktree:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1402 reviewed identities / findings, no unbanked identities |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 102 passed, 5 skipped, 11.62 seconds |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 2624 files already formatted |
| `uv run python -` importing the actual soak driver and evaluating preserved round-6 JSON | PASS: asserted failures exactly `sustain_duration`, `exact_rc_artifact`; 90.43 seconds observed against 14400 required; current artifact check false |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs` | 27 passed, 5 skipped; all skips explicitly require `MAISTRO_TEST_PG_DSN` pointing to migrated PostgreSQL |

The middleware regressions execute real limiter instances for both authenticated
and unauthenticated identities. Each replica returns `[200, 200, 429]` for the
same identity; a healthy local limiter is not a shared allowance. Backpressure
coverage exercises the real task router and canonical in-memory spine. Neither
this nor the fake-connection DDL tests are PostgreSQL multi-replica soak evidence.
No live PostgreSQL or production Compose soak was executed this round.

## Acceptance disposition

| Criterion | Evidence and remaining requirement |
| --- | --- |
| Representative RC profile | PARTIAL: inspected `m3a-load-profile.md`; one-key degraded workload omits concurrent users/Workspaces, Graph fan-out, successful model/tools, Design/Canvas, Goal/background work. RC applicability UNVERIFIED. |
| Two production replicas | UNVERIFIED: `deploy/docker-compose.prod.yml` declares two services, but existing driver boots host processes rather than those images. |
| Sustained saturation, reclaim, retry and leak observation | UNVERIFIED: actual evaluator rejects preserved 90.43-second shakedown against 14400 seconds. Regression execution does not replace sustained traffic. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: schedule probe admits then cancels a queued Run. One durable admission does not establish physical Attempt effects/fencing or Goal convergence. |
| Rate/security/degraded non-bypass across replicas | NOT MET for a shared allowance: fresh middleware regression confirms independent budgets. Canonical identity/security tests pass locally; complete degraded RC traffic UNVERIFIED. |
| Required metrics and explicit thresholds | PARTIAL: sampler regression observes real uv-child RSS/FD growth, but no fresh soak series. Driver loop lag is not application loop lag; full pool/worker/queue pressure and leak/error thresholds UNVERIFIED. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED: no fresh RC restart or physical-effect correlation; preserved exit/rejoin evidence is insufficient. |
| Long-running exact RC and re-soak after code/config changes | BLOCKED: no designated immutable RC/configuration supplied; current host driver explicitly rejects exact-artifact equivalence, including at four hours in executed CLI regressions. |
| Findings classified/filed before promotion | PARTIAL: existing F1–F12 local classification retained. External filing UNVERIFIED; GitHub mutations prohibited. |
| Hash-tied machine/human evidence | PARTIAL: preserved JSON/human pack ties historical preflight to hashes, not a promotable exact-RC soak. RC evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not promotion or integration approval. Existing shared-store and
wrapper-metrics overclaims were already corrected at the assigned head. No
fresh scanner failure or runtime repair is established by this validation.
Only this report changes; no tests added/removed (inventory delta zero), no
ledger/grant amendment, no runtime/configuration edits, no evidence rewritten.

Next: designate the exact promotable images/configuration, resolve cluster-rate
semantics with the owning security/deployment work, complete production-path
workload/physical-effect/metric oracles, and publish a new >=4-hour exact-RC soak.
Do not repeat a host preflight and count elapsed time as artifact proof.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and sustained soak}`.
Local checkpoint commit required; final diff validation recorded below.

## Revalidation at assigned head `cd1c4d7e24e9` (job `491961ec77874eb880d641ddc0ff9113`)

This section records a new validation, not a runtime repair or a new soak. Scope
was frozen to issue #860, its existing branch evidence/tests, and the explicitly
requested Vulture CI gate. Starting HEAD matched the assignment exactly; the
worktree was clean. Assigned base: `8e8db3ad21dc7deaa5c75097e281ecbc52fd7ac5`.
The supplied previous result was read. No `check-*.log` files were present in the
job directory at initial inspection; no driver success is assumed.

Read `AGENTS.md`, `CLAUDE.md`, accepted ADR-081426-1f7c, ADR-081626-f383 and
ADR-085, plus proposed ADR-081. Reconciliation: durable admission is not proof
of physical-work uniqueness; the accepted lease contract does not itself define
expiry takeover. Do not invent a scheduler/reclaim authority to satisfy this
soak issue. Per-principal rate policy does not establish shared replica state.
No canonical execution, authorization, store or event ownership changes.

Fresh commands (1200–1800 second timeouts), with logs under the job directory:

| Command | Outcome | Log |
| --- | --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1402 reviewed identities / 1402 findings; zero unclassified or never-allowlist findings. No ledger delta justified. | `worker-vulture.log` |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q -rs` | 102 passed, 5 skipped in 11.03s. All skips require a migrated `MAISTRO_TEST_PG_DSN`; no live PostgreSQL proof. | `worker-pytest.log` |
| `uv run ruff check .` | PASS | `worker-ruff-check.log` |
| `uv run ruff format --check .` | PASS: 2624 files | `worker-ruff-format.log` |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS: 4198 tests | `worker-inventory.log` |
| `uv run python -` importing the current harness and evaluating preserved round-6 JSON | PASS: assertions confirm 90.43 < 14400 seconds; failed gates are `sustain_duration` and `exact_rc_artifact`; current artifact check is false. This does not rerun the soak. | `worker-evidence-check.log` |

Reachability inspected: `maistro_server/main.py:478` installs the limiter;
lines 544/559 mount the task router. The executed middleware counterexample
(`tests/test_soak_promotion_gates.py:439`) gives the same identity an independent
`[200, 200, 429]` allowance on each instance, for authenticated and unauthenticated
traffic. The backpressure test uses the production router and canonical in-memory
spine; the DDL fence regression uses a fake connection. Neither substitutes for
production multi-replica traffic. The old H3 shared-store overclaim is already
corrected in `m3a-soak-evidence.md:171`; no redundant repair is needed.

Current acceptance disposition (all ten criteria reviewed):

| Criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC profile | PARTIAL: profile inspected; its declared missing multi-user/Workspace, fan-out, successful tool/model, Design/Canvas and Goal/background workloads remain UNVERIFIED. |
| Two application replicas | UNVERIFIED: production Compose declares two, but no designated RC deployment was executed. |
| Sustained saturation/reclaim/retry/leak observation | UNVERIFIED: current evaluator rejects the historical 90.43-second run; sampler unit coverage is not long-window observation. |
| No duplicated physical work / Goal reconciliation | UNVERIFIED: admission-oracle tests pass; physical-effect and sustained Goal recovery oracles are absent from this validation. |
| Rate/security/degraded non-bypass | NOT MET for a cluster-wide principal allowance: real middleware regression confirms replica selection gains another allowance. Full RC security/degraded traffic remains UNVERIFIED. |
| Complete resource/DB/loop/queue/error metrics and thresholds | PARTIAL: profile and live child-process sampler regression checked; complete RC time series and application-loop/lease/pool-pressure observations UNVERIFIED. |
| Active-work kill/restart recovery | UNVERIFIED: no new RC kill/restart; historical exit/rejoin does not prove Attempt fencing or physical-effect recovery. |
| Long-running exact RC / re-soak after changes | BLOCKED: assignment supplies no immutable promotion RC/configuration; current runner explicitly fails artifact equivalence even at four hours. |
| Findings filed/reclassified | PARTIAL: existing local classifications preserved; external filing UNVERIFIED and prohibited in this lane. No new load findings claimed. |
| Machine/human hash-tied evidence | PARTIAL: historical evidence inspected and preserved; qualifying exact-RC evidence UNVERIFIED. |

**BLOCKED**, not integration approval. Only this handoff changes; no code,
runtime config, tests, raw evidence, ledger or grants are changed. Test inventory
delta is zero. A speculative ledger amendment cannot resolve the absent soak.
Next action remains release-owner designation of immutable RC/configuration,
resolution of the aggregate rate-limit acceptance mismatch, representative
production workloads and physical-effect/metric oracles, then a new >=4-hour
exact-artifact run. No GitHub mutations performed.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC and qualifying sustained evidence}`.

## Revalidation at `d5d9c1b757ff` — job `5da9a1abcc55423e80290d72d56adc48`

Scope frozen to #860, the supplied failure log, existing soak driver/tests,
production rate-limit wiring, relevant accepted ADRs, and the requested vulture
gate. Only this existing handoff is edited. Starting HEAD matches the assignment;
the worktree was clean. Base `3c761d14db944a727fa0744444bc67cfe36d49f7`
resolves. No sync conflict exists; no GitHub mutation or integration attempted.
No `check-*.log` files were present in this job directory at initial inspection.

The supplied prior `98a11313167b41a98a420abfda80c292/check-3.log` is a
**schema-fence test failure**, not a vulture failure: 24 DDL statements versus
21 expected. Current `test_pg_learnings.py:174` already includes the three
validation audit columns, independently of production constants. Fresh execution
passes that regression; re-editing it would not repair an existing failure.

Fresh validation (1800-second timeouts; logs in the assigned job directory):

- Required exact-CI vulture command: PASS, **1323 findings / 1323 reviewed
  identities**, zero unclassified / never-allowlist findings (`worker-vulture.log`).
  No unbanked identity exists to justify a ledger amendment.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q -rs`:
  **129 passed, 6 skipped** in 3.05s (`worker-pytest.log`). All skips require a
  migrated `MAISTRO_TEST_PG_DSN`. Fake-connection tests do not prove live PG races.

Production reachability and reconciliation:

- `maistro_server/main.py:648` installs the actual `RateLimitMiddleware`;
  `api/rate_limit.py:94` constructs a process-local limiter. Executed
  `test_soak_promotion_gates.py:439` confirms an independent `[200, 200, 429]`
  allowance on each instance for the same authenticated or pre-auth identity.
  This proves local enforcement, not cluster-wide non-bypass.
- `run_soak.py:730` unconditionally rejects host-process preflight as exact-RC
  evidence. The executed four-hour CLI regressions keep this gate fail-closed.
- `run_soak.py:1044` cancels the schedule-probe Run without physical execution.
  Accepted ADR-081426-1f7c identifies physical execution by Attempt;
  ADR-082426-82c7 only proves occurrence admission uniqueness. ADR-081626-f383
  does not itself authorize lease-expiry takeover. No replacement scheduler,
  execution authority, store, or authorization path is introduced to bridge gaps.
  ADR-085's per-principal policy does not make process-local counters shared.

Acceptance review (no fresh deployment/soak is claimed):

| Criterion | Current evidence / disposition |
| --- | --- |
| Representative RC load | UNVERIFIED: inspected profile explicitly omits multi-user/Workspace, fan-out, successful model/tools, Design/Canvas and Goal/background workloads. |
| Two production RC replicas | UNVERIFIED: middleware instances in regression tests are not deployed RC replicas. |
| Sustained saturation, reclaim, retries, leaks | UNVERIFIED: focused tests are not sustained production traffic. |
| Physical-work uniqueness and Goal reconciliation | UNVERIFIED: schedule probe stops at admission and cancels the Run. |
| Rate/security/degraded non-bypass | Independent per-replica allowances reproduced; aggregate non-bypass is not proven. Complete RC security/degraded behavior UNVERIFIED. |
| Complete metrics and thresholds | UNVERIFIED: sampler regressions pass, but no complete RC time series; driver loop lag is not application loop lag. |
| Active-work restart/drain/fencing/recovery | UNVERIFIED: no physical-effect-correlated RC restart executed. |
| Long unchanged exact-RC soak | BLOCKED: immutable promotion image/configuration not designated in assignment; host preflight explicitly cannot qualify. |
| Findings filed/reclassified | Local findings preserved; external disposition UNVERIFIED, GitHub mutations prohibited. |
| Hash-bound machine/human RC evidence | UNVERIFIED: historical preflight artifacts cannot certify the designated promotion artifact. |

**BLOCKED** on acceptance prerequisites, not a reproduced CI failure. Do not
rerun another host shakedown as a substitute for the missing RC designation and
production workload/oracles. Next: release owner supplies immutable RC/config,
resolves aggregate rate-policy expectations, and enables qualifying physical-work
and resource observation for a new >=4-hour soak. No code/config/tests or quality
ledger changes are justified by this round; inventory delta is zero.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: RC designation and production soak}`.
Final checks: `uv run ruff check .` PASS; `uv run ruff format --check .`
PASS (3270 files); `git diff --check` PASS. Ruff logs are
`worker-ruff-check.log` and `worker-ruff-format.log` in the job directory.
Only this handoff changed; no new tests require an inventory note.
