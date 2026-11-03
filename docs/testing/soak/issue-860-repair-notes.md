# Issue #860 repair checkpoint

## Frozen scope

- Assigned item: issue #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD verified: `8cdfd5e7187057549590d14216473ed997a12d7a`; initially clean.
- Inspect existing soak profile/evidence, promotion gates and adjacent tests, repository instructions and relevant ADRs.
- Repair evidence-backed findings and the explicitly assigned exact-debt-ledger CI gate; no changes to execution or authorization authority.
- Candidate edits: this report, existing soak documentation, `quality/vulture-baseline.json` (only reviewed identities reported by the required command). Tests/code only if inspection demonstrates an actual defect in the assigned soak gates.
- No GitHub mutations; no promotion claim without an exact-artifact >=4h run.

## Initial observations

- Job directory snapshot contains `events.jsonl`, `manifest.json`, `prompt.txt`, `state.json`; no `check-*.log` files are present. Driver checks cannot be assumed successful.
- Ambiguity: the prompt includes verifier and writer instructions. Proceed as writer because this lane explicitly assigns repair and requires a local commit.
- Prior result at `/home/dev/maistro/jobs/af4e4e2506c04a9f84d10cee409658e0/result.json` ends at this starting HEAD and explicitly reports BLOCKED. Existing profile/evidence already correct the historical H3 shared-store claim and document the host-process limitation; no repeat cosmetic repair is justified.

## Required CI-repair gate

Executed `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` at the starting HEAD: exit 0, 1402 reviewed identities / 1402 findings, zero unclassified and zero never-allowlist findings. No unbanked identity exists to review or amend. `quality/vulture-baseline.json` is deliberately unchanged; adding debt without a reported identity would violate the evidence-based repair requirement.

## Architecture and reconciliation

Read `AGENTS.md`, `CLAUDE.md`, production Compose, the existing load/evidence documents, the soak driver and adjacent promotion tests, and the production rate-limit middleware. The assigned historical H3 contradiction is already corrected in this HEAD. The middleware constructs its own `InMemoryRateLimiter` per instance; a six-path overload probe cannot establish a shared budget.

Read ADR-081 (deployment; **Proposed**, not an accepted guarantee), accepted ADR-085 (principal-keyed rate limits), accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle), and accepted ADR-081626-f383 (durable execution lease/fencing). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`: queue/schedule admission is not physical execution evidence. The fencing ADR explicitly leaves lease-expiry takeover outside its current contract. Reconcile #860 by recording that surface as unverified, not by adding reclaim authority or treating admission counts as proof. ADR-085 does not specify a shared request-budget implementation; the observed per-process policy still leaves #860's replica-selection criterion unmet.

Production Compose defines two application replicas but is a reference artifact with unpinned image tags. No immutable selected RC image/config identity was supplied in this lane. A longer run of the current host-uvicorn harness would still fail its exact-artifact gate, so starting another short emulator run would not repair the blocker.

## Fresh focused validation

All commands below ran in the assigned worktree with 1800-second timeouts:

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs`: **102 passed, 5 skipped** (7.94 s). All five skips require `MAISTRO_TEST_PG_DSN`; they are not live PostgreSQL evidence. Existing tests exercise actual rate-limit middleware instances, the admission-backpressure route, mocked HTTP probes and the live Linux subprocess sampler. In particular, both identity classes receive `[200, 200, 429]` on replica 2 after exhausting replica 1: an executed counterexample to shared-budget/non-bypass claims, not a production soak.
- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 2624 files already formatted.
- `uv run python scripts/check-deployment-claims.py`: pass (names resolve only; does not prove deployment behavior).
- `uv run python scripts/check-merge-markers.py`: pass.

No tests were added or changed; inventory delta is zero and no inventory-note amendment is needed. No code, runtime configuration, historical evidence or quality ledger was changed.

An additional `uv run python` inline replay imported the current `failed_promotion_checks` and evaluated the three named historical packs, asserting that every one fails both `sustain_duration` and `exact_rc_artifact` (exit 0):

| Historical pack | Recorded head | Recorded sustained seconds | Current failed checks |
| --- | --- | --- | --- |
| `m3a-soak-evidence.json` | `b268f05359e748387daf01a1077a98c30a336d3d` | absent | rate limiting, failover, nonterminal Runs, admission availability, duration, artifact, drain |
| `m3a-round5-final.json` | `6e8c866e5db152983426ebba355691f83b9201dc` | 90.17 | rate limiting, duration, artifact |
| `m3a-round6-shakedown.json` | `b31c5fdaa63b40506335bbb288889e87bdb9ba0c` | 90.43 | duration, artifact |

This replays gates against recorded data; it does not reproduce historical runtime behavior or establish a new soak.

## Acceptance audit

| #860 criterion | Reachable evidence and disposition |
| --- | --- |
| Representative RC profile | **PARTIAL / UNVERIFIED**. `m3a-load-profile.md` defines thresholds and a request mix, but explicitly lists missing users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and Goal workloads. Driver `main_async` uses one credential and a health-heavy mix (`run_soak.py:1270-1290`). No selected RC configuration justifies those exclusions. |
| Two supported application replicas | **UNVERIFIED for RC**. `deploy/docker-compose.prod.yml` defines two; `boot_stack` launches two host processes instead (`run_soak.py:1121-1131`). Middleware tests emulate independent apps, not Compose replicas. |
| Sustained saturation/reclaim/retry/leaks | **UNVERIFIED**. Round 6 records 90.43 s versus 14400 s (`evidence/m3a-round6-shakedown.json:221-224`). Live child-sampler regression passes, but is not a long-window leak/pool/reclaim test. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED**. Claim probe races admission then cancels the queued Run (`run_soak.py:1050-1055`); final SQL counts canonical Runs, not external physical side effects (`run_soak.py:1414-1419`). One admitted Run cannot prove one physical Attempt across recovery. |
| Rate/security/degraded non-bypass | **NOT MET as written**. Production limiter is process-local (`rate_limit.py:25-30,74`); executed authenticated and unauthenticated replica-selection counterexamples pass. Route tests prove local enforcement/backpressure only. No sustained exact-RC security/degraded proof. |
| Complete telemetry with thresholds | **PARTIAL / UNVERIFIED**. `sample_once` observes PostgreSQL sessions, lock waits, query round-trip, process-group resources and Run status counts (`run_soak.py:455-490`). Driver-loop lag (`run_soak.py:1306-1318`) is not application-loop latency; no current full-duration worker/pool/lease telemetry demonstrates the required bounds. |
| Active-work kill/restart with fencing/recovery | **UNVERIFIED**. Historical round 6 has SIGTERM exit/rejoin counters, not correlated in-flight Attempt/side-effect proof. Rejoin and zero nonterminal Runs alone do not exclude loss or duplicate physical work. |
| >=4h exact-RC artifact/config soak | **UNVERIFIED / BLOCKED**. Current harness unconditionally returns `exact_rc_artifact.ok=false` (`run_soak.py:635-646`). Replayed packs fail both artifact and duration. No exact selected RC digest/config was provided; no new soak was attempted. |
| Findings filed/reclassified to earliest invariant | **PARTIAL / external filing UNVERIFIED**. Existing evidence locally classifies F11/F12 as M3-A evidence-validity findings. This round preserves those records; no GitHub mutation is permitted or performed. |
| Machine/human evidence tied to exact hashes | **PARTIAL / qualifying evidence UNVERIFIED**. Historical JSON and narrative exist and were inspected/replayed. `collect_hashes` records host/preflight identity (`run_soak.py:1088-1120`), not promoted application image digests and the complete production runtime configuration. |

## Handoff

**BLOCKED; no promotion approval.** The assigned CI gate is already green and prior documentation corrections are present. Manufacturing a ledger delta or another cosmetic correction would not address the unresolved acceptance evidence. Only this checkpoint/report is changed in this round.

Next: obtain the immutable RC image and normalized full runtime configuration; resolve the replica-selection requirement against the documented per-process limiter; complete a representative production-path workload and physical-work/Attempt recovery oracles; then run >=14400 seconds on that exact artifact and publish both evidence forms. Any runtime/code/config repair requires a new qualifying soak. Do not promote the historical preflight packs.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC artifact/config selection and qualifying soak; issue #860 remains blocked"}`. Focused validations passed; issue acceptance remains unfinished. Commit this report locally and leave the worktree clean.
