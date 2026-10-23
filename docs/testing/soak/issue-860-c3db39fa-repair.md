# Issue #860 — c3db39fa repair checkpoint

## Frozen scope

- Issue: #860 only; writer CI-repair round, branch `auto-860`.
- Starting HEAD: `e5b21225a5dd9a0c4fd9bf6b99a28c8ce27297a3`.
- Dispatch base: `b672b799aba6d3db9edc3e1be18b1a3335dd3bc0`.
- Worktree was clean at entry; no uncommitted work required salvage.
- Scope: `quality/vulture-baseline.json` for actually observed retained identities,
  their source/adjacent tests if a real dead-code repair is indicated, and this
  validation/handoff note. Existing #860 soak sources, tests, profile, evidence,
  ADRs, and captured dispatch are read-only acceptance evidence unless a concrete
  in-scope defect requires repair. No other issues/PRs will be processed.
- No driver `check-*.log` files were present in the supplied job directory.
- Assumption: the explicit CI-repair exception authorizes reviewed vulture ledger
  amendments, but not authorization edits or relaxing promotion gates. A passing
  static gate cannot establish a production RC soak.

## Progress

The requested exact vulture command passed: 1,338 reviewed identities matched
1,338 findings; zero unclassified and zero never-allowlist findings. It reported
default comparison base `cd5618223cbd`, not the dispatch base. There is no observed
unbanked identity to repair or amend; ledger changes would be speculative.
The supplied prior result exists and reports BLOCKED. Current profile inspection
confirms that the runner is explicitly a host-process preflight, not a production
RC runner. Fresh focused tests passed: 109 passed, 6 skipped (2.77 s); full repository
ruff lint and format checks passed (2,943 files formatted). The tests exercise
real production limiter instances: the same identity receives `[200,200,429]`
independently on both replicas. This is evidence against a shared allowance,
not proof of an exact production deployment. `git diff --check` against the
dispatch base passed; the prior reported EOF failures no longer reproduce.
An attempted ADR-081 descriptive filename was not found; skipped. The actual
ADR filenames were subsequently resolved from the repository.

## Architecture and reconciliation

Read accepted ADR-081426-1f7c (physical execution identity is the Attempt),
ADR-081626-f383 (Run store owns fencing; expiry takeover is not defined by that
contract), ADR-082426-82c7 (occurrence uniqueness is canonical Run admission),
and ADR-085 (principal-keyed request limits). ADR-081 deployment topology is
Proposed, not an accepted exception. None authorizes treating admission counts
as physical-work proof, introducing a second scheduler/store, or waiving #860's
replica-selection requirement. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`; no runtime or authority changes made.

Production `maistro_server/main.py:593` installs the inspected middleware.
`api/rate_limit.py:25-30,72-77` explicitly uses independent in-memory state.
`deploy/docker-compose.prod.yml:26-29,75-76` defines two services built locally,
not a designated immutable release image. The profile identifies missing
production workloads and telemetry at `m3a-load-profile.md:152-165,197-201`.

## Executed validation

Validation used long tool timeouts (1,000–1,800 seconds).

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,338 reviewed identities / findings; zero unclassified, zero never-allowlist. Matches `.github/workflows/vulture-ratchet.yml:82-85` arguments. |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 2,943 files |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | PASS: 109 passed, 6 skipped, 2.77 s |
| `uv run pytest packages/maistro-server/tests -x -q` | PASS: 494 passed, 9 skipped, 22 deprecation warnings, 27.34 s |
| `uv run python scripts/check-deployment-claims.py` | PASS: named components/backends exist; not a deployed behavioral test |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS: 4,755 unique collected tests match inventory |
| `git diff --check b672b799aba6d3db9edc3e1be18b1a3335dd3bc0...HEAD` | PASS: prior whitespace findings do not reproduce |
| `uv run python -` importing the real soak runner and evaluating retained round-6 JSON | PASS: asserted exactly `sustain_duration` and `exact_rc_artifact` failures and `preflight_artifact_check().ok is False` |

One exploratory invocation, `uv run python scripts/check-vulture-baseline.py
--help`, exited 1: this wrapper did not display help; it measured zero findings
and correctly rejected the empty scan. This is not a failure of the exact CI
scan above and gives no grounds for a ledger amendment. No speculative scanner
fix was made. Skipped tests are not credited as acceptance evidence. No live
Compose deployment or fresh soak ran.

## Acceptance audit

| # | Criterion | Evidence and disposition |
| --- | --- | --- |
| 1 | Representative RC workload | UNVERIFIED. Existing profile describes a one-key, provider-less preflight, explicitly missing user/Workspace population, Graph fan-out, successful tools/models, Canvas/Design and Goal/background traffic. |
| 2 | At least two production application replicas | UNVERIFIED. Compose defines two services; executed ASGI instances are not two deployed RC replicas. |
| 3 | Sustained saturation, reclaim, retry, leak observations | UNVERIFIED. Real evaluator rejects retained 90.43 seconds against 14,400 required. No current long-window observation. |
| 4 | Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED. Admission-oracle tests pass, but neither admission identities nor the historical schedule probe's cancelled queued Run proves physical Attempt work. |
| 5 | Rate-limit/security/degraded non-bypass | NOT MET for a shared principal allowance: both production-middleware counterexamples passed, demonstrating independent `[200,200,429]` responses per replica for authenticated and unauthenticated identities (`tests/test_soak_promotion_gates.py:439-488`). Local backpressure/security regressions pass; complete RC behavior UNVERIFIED. |
| 6 | Complete metrics and thresholds | UNVERIFIED. Sampler regressions pass, but no current production application-loop latency, worker/container counts, or sustained pool/lock/queue series. Driver-loop latency is not application-loop latency. |
| 7 | Active-work kill/restart drain/fencing/recovery | UNVERIFIED. No RC restart or physical-effect reconciliation executed. Sampler/process tests do not establish this property. |
| 8 | Long-running exact-RC artifact/config soak | NOT MET. `run_soak.py:635-646,1465` rejects its host-process preflight even at sufficient duration. No designated immutable promotion artifact/configuration was supplied. |
| 9 | Findings filed/reclassified before promotion | PARTIAL: existing human evidence locally classifies F11/F12 as M3-A evidence-validity defects. Complete external filing/reclassification UNVERIFIED; GitHub mutations prohibited. |
| 10 | Machine/human evidence tied to exact hashes | UNVERIFIED for current RC. Retained JSON names `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this head, and fails the current evaluator. Existing raw artifacts remain untouched. |

## Handoff

**BLOCKED**, not integration approval. Only this validation note changes. No
production/test/config/ledger changes and no test additions; inventory delta is
zero, so no new inventory note is needed. The explicit CI-ledger repair has no
reproducible defect to fix. The previous blocker cannot be resolved by another
static validation or by relabeling host preflight evidence.

Next: provide the exact immutable promotion RC/configuration; resolve rate-limit
scope with the owning security/deployment lane; complete production workload,
physical-effect and telemetry oracles; then execute and publish a new >=4-hour
exact-artifact soak. Preserve the existing canonical execution and auth paths.
No push, PR, merge, comment, issue closure, background command, or destructive
git operation was performed.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and soak}`.
The scoped validation is finished; #860 acceptance remains blocked. Commit this
note locally as the writer checkpoint.
