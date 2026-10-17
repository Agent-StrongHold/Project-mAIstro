# Issue #860 — bounded repair 7d8df861

## Frozen scope

- Issue #860 only; branch `auto-860`, starting head
  `bb2a1829b4806e663b15321c90b4792b4e912ebb`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Read-only evidence: supplied dispatch-context.json, prior result and cited
  check-3.log; repository instructions, relevant ADRs, soak runner/profile,
  adjacent soak tests, vulture gate and retained identities it actually reports.
- Candidate edits: this report; `quality/vulture-baseline.json` only if the
  explicit CI-repair scan identifies reviewed retained debt. No speculative
  scheduler/rate-limiter redesign, release designation, or GitHub mutation.
- Initial worktree clean; starting head verified. No salvage required.
- No check-*.log files present in current job directory at initial inspection.

## Ambiguity and assumption

Prior result reports no designated exact RC artifact/configuration. Treat this
as an unverified blocker pending local inspection, not permission to invent a
release candidate. The explicit vulture repair can be evaluated independently.

## Progress

Read supplied prior result; it reports BLOCKED, not acceptance completion.
The cited old check-3.log is a schema-fence assertion failure (24 statements
versus 21), not a vulture failure. Fresh targeted tests pass: 102 passed,
6 skipped (2.04 s). The exact requested vulture scan passes: 1,323 findings,
1,323 reviewed identities, zero unclassified/never-allowlist. No ledger edit is
justified. `docs/testing/soak/README.md` was not found; skipped in favor of the
existing `m3a-load-profile.md`.

Read accepted ADR-073126-c4e1 (immutable release artifacts), ADR-082526-b36a
(executor lease renewal/reclamation), and ADR-085 (principal rate limits).
The current profile explicitly calls this a host-process preflight, not the
promoted Compose artifact. No alternate execution or authorization authority
will be introduced to hide those acceptance gaps. Production inspection confirms the gaps below. The canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model remains unchanged.

## Executed validation

Logs are in `/home/dev/maistro/jobs/7d8df861722943f9ac2d6c25cf101692/`.

| Command | Actual outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1,323 reviewed identities match 1,323 findings (`vulture.log`). No new retained identities to bank. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q` | Exit 0; 102 passed, 6 skipped (`targeted-pytest.log`). Skips are not acceptance evidence. |
| `uv run ruff check .` | Exit 0; all checks passed (`ruff-check.log`). |
| `uv run ruff format --check .` | Exit 0; 3,270 files already formatted (`ruff-format.log`). |
| `uv run python scripts/check-suite-inventory.py` | Exit 0; all 17 suites match, 31,128 unique test identities (`inventory.log`). Collection is not test execution. |
| `git diff --check` | Exit 0. |

The old failure's missing three validation-audit columns are already explicitly
asserted at `packages/maistro-core/tests/persistence/test_pg_learnings.py:173–178`.
Production `PgLearningStore.ensure_schema` executes the upgrade under one
transaction and advisory lock (`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`).
No test changes were necessary; no inventory delta is introduced.

One exploratory lookup used a nonexistent `maistro_server/middleware/rate_limit.py`;
recorded not found and resolved once from the test's actual import to
`maistro_server/api/rate_limit.py`. No command acted on that missing path.

## Acceptance review (all ten criteria)

| Criterion | Fresh evidence and remaining gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** Read `docs/testing/soak/m3a-load-profile.md`: one-key degraded HTTP preflight, with missing concurrent Workspaces, Graph fan-out, successful tools/models and Design/Canvas/background work explicitly listed at line 152. No selected RC applicability decision supplied. |
| At least two deployed application replicas | **UNVERIFIED.** Tests exercise two production middleware instances via ASGI, not two deployed RC replicas. No live deployment was started in this round. |
| Sustained saturation, queues, reclaim, retries and leak observations | **UNVERIFIED.** No sustained load executed. Unit tests of sampler/accounting cannot establish long-window behavior. |
| Physical-work uniqueness across replicas | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the admission probe Run without executing it. Admission identity tests passed but are not physical Attempt fencing evidence. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; stronger shared-budget claim falsified locally.** Executed `test_replica_selection_has_an_independent_production_allowance` for both authenticated and unauthenticated identities (`tests/test_soak_promotion_gates.py:439`): each middleware instance admits two requests then returns 429 for the same identity. Production allocates its own `InMemoryRateLimiter` at `packages/maistro-server/src/maistro_server/api/rate_limit.py:95`. Local enforcement is documented; do not mislabel it a cluster-wide budget or change authorization authority. |
| Complete telemetry and explicit thresholds | **UNVERIFIED.** Profile has thresholds; passing sampler tests cover child RSS/descriptors. Driver loop lag is not application loop lag, and no complete RC observation series was captured. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** No active-work deployment/restart in this round. Process rejoin and terminal record counts alone would not prove physical-work fencing. |
| Long soak of unchanged exact RC | **BLOCKED / UNVERIFIED.** `scripts/soak/run_soak.py:730` always rejects host preflight as exact-RC evidence. Executed four-hour-evidence CLI refusal tests use synthetic evidence, not four hours of traffic. Assignment, frozen issue body and linked PR bodies designate no exact image/configuration for promotion. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** This committed report records the gaps locally. GitHub mutation is prohibited; no filing, reclassification, closure or promotion performed. |
| Machine/human evidence bound to exact artifact/configuration hashes | **UNVERIFIED for RC.** Local test logs and this source-linked report are not a hash-bound exact-RC soak pack. |

Frozen dispatch inspection classified all 683 primary comments as carrying an
automated progress marker and read the four linked PR bodies; extracted evidence
is `dispatch-bodies.txt` in the job directory. No new GitHub enumeration or
mutation was performed. This does not claim an exhaustive release-registry audit.

## Disposition and handoff

**BLOCKED**, not merge-ready. No actual current vulture or schema-test failure
justifies a code, ledger or gate change. Only this report is changed. No new
ADRs, schedulers, Goal stores or authorization paths were introduced.

Next: release owner must designate immutable RC artifacts and normalized runtime
configuration; the exact deployed topology needs a representative workload and
physical-work/lease-recovery observations, full telemetry, and a >=4-hour unchanged
soak. The rate-limit acceptance mismatch needs an explicit disposition, not a
waiver inferred from local 429 responses. Do not repeat preflight runs expecting
them to satisfy the exact-artifact gate. Local validation success is not
integration approval.

Checkpoint: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
errors 0 current validation commands; next is the release-evidence prerequisite.
Commit this report locally and leave the worktree clean.
