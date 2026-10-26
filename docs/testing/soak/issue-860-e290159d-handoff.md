# Issue #860 — e290159d repair checkpoint

## Frozen scope

- Assigned item: #860 only, branch `auto-860`.
- Starting HEAD: `374520acba0eb93472016464af0358dbf0abd148`.
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree initially clean; no incoming edits to salvage.
- Inputs: supplied dispatch-context.json, prior result 698aef57, prior check-3.log 98a11313.
- No driver check-*.log files present in current job directory at initial snapshot.
- Review scope: scripts/soak/run_soak.py, tests/test_soak_promotion_gates.py,
  related production rate-limit path, relevant ADRs and CI vulture command.
- Potential edit scope: this report and quality/vulture-baseline.json only if
  the requested scan produces reviewed identities requiring amendment.
- Assumption: writer CI-repair assignment does not designate this arbitrary
  worktree HEAD as the release candidate. Missing RC evidence must stay unverified.

## Progress

Requested Vulture scan executed with a 1200-second timeout: PASS, 1323
reviewed identities / findings, zero unclassified and never-allowlist findings.
Checker reports ratchet base `4aa68edc0b6b`; no ledger amendment is justified.
The prior check-3.log reports 24 schema statements versus 21 expected; the
current test independently lists all 24, including validation audit columns.
Fresh schema regression passed. No source repair is justified by that historical
failure. The latest five captured issue comments and PR #1672/#2100 bodies add
no RC designation: they describe blocked attempts, a draft claim, and a narrow
historical-secret-scan repair respectively. No remote list was refreshed.

## Executed validation

All validation commands used 1200-second timeouts in the assigned worktree.
Logs below are in `/home/dev/maistro/jobs/e290159de13744f8af69d7982d23aa43/`.

| Command | Outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS as above; arguments checked against `.github/workflows/quality.yml:1078`. Output in worker tool transcript. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 103 passed, 6 skipped in 2.49 s (`worker-pytest.log`). All skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL evidence claimed. |
| `uv run ruff check .` | PASS (`worker-ruff-check.log`). |
| `uv run ruff format --check .` | PASS, 3270 files already formatted (`worker-ruff-format.log`). |

## Architecture and reachable behavior

Read repository instructions and accepted ADR-081426-1f7c, ADR-081626-f383,
ADR-082526-b36a, ADR-082826-08f0 and ADR-085. Preserve the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model. Physical execution identity
is Attempt; terminal Run counts cannot establish physical-work uniqueness.
The later reclaim/recovery ADRs complete the original lease ADR's deferred
recovery boundary: a live lease prohibits redispatch. No alternate execution,
authorization, persistence or event authority was introduced.

ADR-085 requires per-principal rate identities. The production middleware
uses the canonical resolver but documents process-local allowances
(`packages/maistro-server/src/maistro_server/api/rate_limit.py:31–37,90–98`),
and is installed in `main.py:648`. Fresh execution of
`tests/test_soak_promotion_gates.py:439` reproduced `[200,200,429]` on EACH
middleware instance for the same identity (authenticated and pre-auth cases).
This is real middleware through ASGI, not a deployed multi-replica soak. It
cannot certify the stronger issue non-bypass claim; changing policy or adding a
competing limiter in this CI-repair lane would not be a justified reconciliation.

## Acceptance audit

No RC deployment or long soak was executed in this round. Local tests are not
substitutes for the production observations required below.

| Issue criterion | Evidence and disposition |
|---|---|
| Representative release workload | **UNVERIFIED.** `run_soak.py:1373–1395` uses one credential and a health/task/receipt/metrics mix without LiteLLM. `m3a-load-profile.md` explicitly lists missing users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and Goal/background-worker coverage. RC applicability remains undesignated. |
| Two deployed application replicas | **UNVERIFIED for RC.** `run_soak.py:730–741` identifies host-uvicorn preflight, not the promoted Compose artifact. ASGI middleware instances do not prove deployment. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED.** Sampler and admission tests pass, but no sustained RC observation window was collected. |
| Physical-work uniqueness across schedules/tasks/Run/Attempt/Goal | **UNVERIFIED.** Admission tests passed; `run_soak.py:1507–1527` checks Run counts/status rather than physical Attempt execution across all paths. |
| Rate/security/degraded non-bypass | **UNVERIFIED for deployment.** Fresh middleware test reproduces independent replica allowances; this does not prove a shared principal budget or concurrent security/degraded correctness. |
| Complete telemetry with thresholds | **UNVERIFIED.** `run_soak.py:1410–1426` measures driver-loop lag, not application-loop lag. No complete production telemetry window collected. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED.** Drain evaluator tests pass; no active RC Attempt was killed/restarted and observed through canonical recovery. |
| Long soak of exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** No immutable RC designation supplied. Executed `test_four_hour_preflight_cannot_pass_cli` rejects otherwise-passing synthetic four-hour evidence without RC identity; production driver installs that failing check at `run_soak.py:1552`. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** Findings recorded here; GitHub mutation is prohibited and was not attempted. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED for RC.** This report binds local checks to the source head, not a promoted image/config or release evidence pack. |

## Handoff

**BLOCKED**, not integration approval. Only this report changed; no source,
tests, ledgers, grants or gates changed. No test inventory delta is needed.
Existing work was preserved. The supplied historical test failure and requested
Vulture failure do not reproduce; do not invent a repair or weaken a gate.

Next: designate the immutable RC image/configuration and representative workload
applicability; resolve rate non-bypass semantics through existing policy ownership;
execute the long production soak with physical Attempt/recovery observations and
complete telemetry. Any code/runtime-config change requires a new soak.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC prerequisites and production soak"}`.
