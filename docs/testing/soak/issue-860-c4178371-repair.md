# Issue #860 — c4178371 repair checkpoint

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `ef524159aeaacae20dcd1590cbb4f0c9dc1c29fc`.
- Supplied base: `7334621bf797178dd992622d55aaead33bf9d094`.
- Initial worktree: clean; no incoming edits to salvage.
- Candidate edits: this report and, only if the required scan identifies
  reviewed retained debt, `quality/vulture-baseline.json`. Any actual source
  repair requires an evidence-backed scope checkpoint first.
- Validation scope: exact vulture scan, repository ruff checks, existing soak
  promotion tests and adjacent server admission/rate-limit tests; acceptance
  inspection of the retained soak driver/profile/evidence and relevant ADRs.
- No new issue/PR enumeration or remote mutations. Supplied dispatch snapshot
  is the sole issue/PR evidence source.

## Assumptions and initial evidence

This is a writer CI-repair round. The supplied prior result reports a passing
vulture scan and unresolved exact-RC soak prerequisites; those claims are not
accepted as fresh validation. No `check-*.log` files were present in the supplied
job directory at initial inspection. The explicit writer permission applies;
no verifier-only tree restriction is assumed.

## CI-repair checkpoint

Executed the dispatched exact scan:

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

Exit 0: 1,336 findings / 1,336 reviewed identities; zero unclassified and zero
never-allowlist entries. The gate reports its comparison base as
`56332162cf63` (not the supplied issue base). No missing identity or genuine dead
source was reported. A ledger amendment without such evidence is unwarranted;
`quality/vulture-baseline.json` remains unchanged.

## ADR reconciliation

Accepted ADR-081226-a66b retains Run → NodeRun → Attempt lifecycle ownership;
accepted ADR-081626-f383 makes the canonical Run store the execution-fence
owner and explicitly does not define lease-expiry takeover. A schedule-admission
race is not proof of physical Attempt fencing or reclaim. Accepted ADR-085
requires per-principal rate limiting; it does not waive the issue's explicit
replica-selection acceptance. ADR-081 is Proposed, not an accepted exception
allowing the host-process emulator to substitute for the promoted artifact.
No scheduler, authority, authorization path, or runtime configuration is changed.

## Executed validation

All commands ran in the assigned worktree with long tool timeouts (1,000 or
1,800 seconds). Existing environment resolved the required dependencies.

| Command | Outcome |
| --- | --- |
| Exact vulture scan above | PASS; 1,336 reviewed identities match |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3,003 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS; 75 tests, 2.75 seconds |
| `uv run python scripts/check-ratchet-provenance.py` | PASS; 49 quality JSON consumers have explicit provenance |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check 7334621bf797178dd992622d55aaead33bf9d094...HEAD` | PASS; prior whitespace finding is not reproduced against the assigned base |
| `uv run python` loading the current driver and asserting `failed_promotion_checks` for retained round-6 JSON | PASS; exact failures are `sustain_duration`, `exact_rc_artifact` |

The vulture invocation matches `.github/workflows/vulture-ratchet.yml:82-85`.
Local command output is retained in `/tmp/issue-860-c4178371-*.log` (ephemeral,
not a promoted evidence pack). No source or test change was justified by these
results. No tests were added, removed, or renamed; inventory delta is zero and
no inventory note or baseline edit is required.

## Acceptance audit

| #860 criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** Profile exists but `m3a-load-profile.md:152-164` explicitly excludes actual multi-user/Workspace, Graph fan-out, successful tools/models, Canvas and reconciliation coverage. Reading the profile is not executing those workloads. |
| At least two supported application replicas | **UNVERIFIED for the RC.** `deploy/docker-compose.prod.yml:26-78` defines two application services; `run_soak.py:635-646` identifies its different host-uvicorn topology. ASGI middleware instances in tests are not deployed replicas. |
| Sustained saturation, reclaim, retry, leaks and restart | **UNVERIFIED.** Retained evidence records 90.43 seconds versus 14,400 required (`evidence/m3a-round6-shakedown.json:163-165,221-225`). No new long soak was run. |
| Physical-work uniqueness / Goal reconciliation | **UNVERIFIED.** Retained claim probe cancels its Run (`evidence/m3a-round6-shakedown.json:12-16`); profile lines 197-200 acknowledge it does not execute physical work or sustain schedule traffic. Passing admission tests do not establish this criterion. |
| Security/degraded behavior cannot be bypassed by replica selection | **Counterexample reproduced.** `tests/test_soak_promotion_gates.py:439-488` passes for authenticated and unauthenticated identities: replica 1 yields 200,200,429, then replica 2 independently yields 200,200,429. This uses the production middleware registered by `packages/maistro-server/src/maistro_server/main.py:628`; its `api/rate_limit.py:72-76` constructs process-local state. The adjacent rate-limit and canonical admission-backpressure tests pass but do not establish cluster-wide enforcement. |
| Complete thresholded PostgreSQL/application-loop/worker/RSS/FD/queue/error telemetry | **UNVERIFIED.** Existing sampler tests prove child-process observations, not a sustained application telemetry series. Profile lines 158-164 explicitly distinguish driver loop lag from application lag and leave worker counts and saturation unverified. |
| Active-work kill/restart drain/fence/recovery | **UNVERIFIED.** Historical exit/rejoin evidence is not current-artifact physical-work fencing proof. No live recovery scenario executed in this round. |
| Long exact-RC artifact/config soak | **Not met.** Current evaluator rejects the retained evidence for both duration and exact artifact. `run_soak.py:635-646` always rejects the emulator as an exact artifact; four-hour preflight rejection tests pass. Running this same emulator longer cannot repair the artifact mismatch. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED for completeness.** Existing profile references earlier findings, but the fresh replica-selection counterexample remains unresolved. No GitHub mutations were performed or implied. |
| Current image/package/commit/config-bound machine and human evidence | **UNVERIFIED.** Retained JSON is tied to `b31c5fdaa63b40506335bbb288889e87bdb9ba0c` (`evidence/m3a-round6-shakedown.json:70`), not the assigned HEAD; it is not transferable to this branch. This report is validation/handoff documentation, not a substitute soak pack. |

## Outcome and handoff

**BLOCKED on issue acceptance; dispatched vulture gate already passes.** Only
this report is changed. No ledger, grant, gate, production source, deployment,
or test changes. No exact-RC workload was launched or claimed.

Next work requires selecting and freezing the actual promotable artifact and
configuration, providing the missing production-path representative workloads
and telemetry, resolving replica-selection enforcement through the existing
canonical security path, then running at least the profile's four-hour soak
with live physical-work fencing/recovery checks. Preserve the canonical
Goal → Graph → Run → NodeRun → Attempt execution model. Any runtime/config
repair requires a new soak; do not reuse the historical hashes or accept
passing unit tests as release evidence.

Progress: checked 1 assigned issue; done 1 bounded CI-gate/acceptance audit;
skipped 0 issues; command errors 0. The issue itself remains incomplete.
