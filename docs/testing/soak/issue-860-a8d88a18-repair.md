# Issue #860 — repair validation, job a8d88a18

**Writer round; not promotion evidence or integration approval.**

## Frozen scope

- Sole item: issue #860, branch `auto-860`, starting head
  `63625928ea76a8a70a04333639e99a77677f887c`, develop base
  `91996e19223db61bab49ce2e8a8d5b8f6eb2728e` (both resolved locally).
- Worktree clean at entry; no salvage needed. Prior result
  (`86cb034e`, verdict BLOCKED) read; its findings re-verified below, not assumed.
- Job directory contains no `check-*.log` files; driver checks unavailable, so all
  validation below was executed directly in this round.
- Previous block was an acceptance block (no designated exact-RC artifact, no
  ≥14400 s production-topology soak), not a develop sync conflict. The observed
  branch divergence (138 ahead / 3 behind `origin/develop`) was resolved anyway:
  `origin/develop` merged cleanly (no conflicts; 7 files, +772/−1) at merge commit
  `9885ad8f51cbcdf7663e0610d8f5bc09a4ed72da`, so the assigned develop base
  `91996e192` is now an ancestor. That merge brings P1a Attempt
  `cancellation_cause` model work (#1928) — execution-model-neutral, verified by
  the new tests passing; canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`
  preserved, no competing scheduler/store/authorization introduced.

## Change made this round (evidence-based, in-lane)

Filed the one load-derived runtime finding that had executed in-tree evidence but
no work filing: **`[engine-116]` Cluster-wide rate-limit budget for multi-replica
deployments — Accepted; `gap-spec` — v1.0** in `BACKLOG.md`.

- Evidence: limiter state is deliberately process-local
  (`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30`), and
  `tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance`
  (executed this round, both identity classes) reproduces `[200, 200, 429]` on each
  replica for the same identity — replica selection mints fresh allowance.
- Disposition: #860's acceptance bullet "cannot be bypassed by replica selection"
  is unmet by the current implementation and required before final promotion; the
  cluster-wide decision is captured by no spec/ADR (`gap-spec`), so the item is
  filed at the earliest broken milestone invariant with the decision (candidate:
  coordinated shared store behind the existing limiter interface) required before
  implementation. This resolves the recurring "external filing UNVERIFIED"
  partial for the limiter finding: the filing now exists in the repo's
  work-source of record. No GitHub mutation performed or needed for this.
- `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).

## Fresh validation (all executed this round, 900 s timeouts)

| Command | Result |
| --- | --- |
| `git merge --no-ff origin/develop` | clean, no conflicts; merge `9885ad8f` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS (2,889 files) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_attempt_cancellation_cause_model.py packages/maistro-core/tests/graph/test_template_runtime_exclusion.py -q -rs` | **171 passed, 5 skipped** (skips require migrated `MAISTRO_TEST_PG_DSN`; no live-Postgres concurrency claim) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,342 reviewed identities / 1,342 findings; base `91996e192` → candidate `9885ad8f`. No unbanked identity; no ledger amendment warranted |
| `uv run python scripts/check-suite-inventory.py --suite tests/ --suite packages/maistro-core/tests --suite packages/maistro-server/tests` | PASS: 3 suites match recorded inventory (17,755 unique identities) |
| `uv run python scripts/check-backlog-consistency.py` | PASS (168 items, incl. new `engine-116`) |

Evaluator replay (inline `uv run python -`, no historical evidence modified): at
merged head `9885ad8f`, `failed_promotion_checks` rejects all four historical
packs on both `sustain_duration` and `exact_rc_artifact`
(`m3a-soak-evidence.json` 7 failed, `m3a-repair-validation.json` 7,
`m3a-round5-final.json` 3 [90.17 s], `m3a-round6-shakedown.json` 2 [90.43 s]);
`preflight_artifact_check()` returns `ok=false`, topology
`host-uvicorn-preflight`. The gate is functioning as designed: sub-minimum,
non-RC-identity evidence cannot sign promotion.

## Acceptance audit (unchanged where no new evidence exists)

| #860 criterion | Disposition |
| --- | --- |
| Representative RC load profile | PARTIAL — `m3a-load-profile.md` records workload gaps; unchanged this round |
| ≥2 production replicas exercised | UNVERIFIED — `deploy/docker-compose.prod.yml` defines two servers; static contract + middleware regressions only |
| Sustained saturation / reclaim / retries / leaks | UNVERIFIED — no fresh sustained load; evaluator rejects all historical packs on duration |
| Physical-work uniqueness, Goal reconciliation | UNVERIFIED — admission-only proofs; schedule probe cancels its Run without executing |
| Rate limiting not bypassable by replica selection | **NOT MET → FILED as `engine-116`** (Accepted, `gap-spec`, v1.0) with executed regression evidence; implementation work pending |
| Telemetry with explicit thresholds | UNVERIFIED — wrapper-only historical measurements; profile documents gaps |
| Kill/restart drain/fencing/recovery | UNVERIFIED — no new active-work restart |
| ≥14400 s soak of exact RC artifact/config | NOT MET — no immutable RC image/configuration designated; gate correctly rejects all four packs. Any code change (incl. this merge) requires a new soak against the eventual RC |
| Findings filed/reclassified to earliest invariant | **ADVANCED** — limiter bypass finding now filed in-repo as `engine-116`; historical F11/F12 classifications retained |
| Machine/human evidence bound to exact hashes | UNVERIFIED for promotion — historical narrative exists; cannot sign the RC |

## Handoff

Still blocked on the same substantive external inputs identified by prior rounds:
a designated immutable RC artifact/configuration for #89, the `engine-116`
cluster-wide limiter decision/implementation, and the ≥4 h production-topology
soak with active Attempt interruption/recovery correlation. No in-tree defect was
found this round; the vulture CI-repair premise remains not reproduced
(ledger matches the scan exactly). No tests added or changed by this round beyond
the develop merge (which carries its own inventory note), so no new inventory
delta note is required for this round's edits (BACKLOG.md + this note).

Progress: checked 1, done 1 (develop merge + engine-116 filing + validation),
skipped 0, errors 0; next: release owner designates the RC artifact/configuration;
`engine-116` decision and implementation; then the ≥14400 s soak on that exact
topology.
