# Issue #860 repair checkpoint — aff1c0da

## Frozen scope

Only issue #860, starting head `32e40a7c7e2f51864ce35db2ce2d46314579b348`,
base `2f56be40ad241262b0384ab0b97834ebd37fe4d7`, assigned worktree `auto-860`.
No GitHub operations. Initial tree clean. Supplied dispatch snapshot inspected;
no live re-enumeration. Allowed edit surfaces: this checkpoint and
`quality/vulture-baseline.json` only if the requested scan demonstrates retained
unbanked identities. No production changes without new concrete evidence.

Assumption: this is a writer CI-repair round, not a verifier-only round.
The prior result is evidence to recheck, not acceptance proof. Current job has
no supplied check-*.log files. The requested vulture scan exited 0 (log: job directory `repair-vulture.log`);
no ledger amendment is justified. Supplied historical `check-3.log` shows
`test_ensure_schema_fences_ddl_behind_advisory_lock` expected 21 statements but
observed 24. Rechecking the current test before considering any repair.
Current schema test file passes (exit 0); it already includes the three missing
validation-audit columns. `uv run ruff check .` and `uv run ruff format --check .`
both exit 0. No source, ledger, or test repair justified by these results.
Attempted README paths `scripts/soak/README.md` and
`docs/testing/soak/README.md` were not found; skipped in favor of the resolved
`docs/testing/soak/m3a-load-profile.md`.

Existing soak-promotion tests and server rate-limit tests both exit 0. The former
executes the two identity variants of the replica-selection counterexample:
after exhausting replica 1, the same identity receives two successes at replica
2. This tests production middleware, registered at `maistro_server/main.py:648`,
not a complete production deployment. No tests added or changed, so no inventory
delta is needed.

Read accepted ADR-085, ADR-081226-69ee, ADR-081626-f383 and ADR-082526-b36a.
The later renewal/reclaim ADR extends the earlier fencing boundary; neither
allows treating admission deduplication as physical-execution proof. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt and the canonical authorization path.
The documented process-local rate-limit contract is not a waiver of #860's
replica-selection acceptance criterion. No competing enforcement path introduced.

## Executed validation

Logs are in `/home/dev/maistro/jobs/aff1c0daef924d5299a8b79e05995773/`.

| Command | Result / log |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1322 reviewed identities, 1322 findings, zero unclassified; `repair-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; `repair-schema-tests.log` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 72 passed; `repair-soak-tests.log` |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 26 passed; `repair-rate-tests.log` |
| `uv run ruff check .` | PASS; `repair-ruff.log` |
| `uv run ruff format --check .` | PASS; `repair-format.log` |
| `uv run python scripts/check-ratchet-provenance.py` | PASS; `repair-provenance.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; `repair-surfaces.log` |
| `git diff --check` | PASS |

Vulture used its default resolved baseline `ab8b3737fa64`, not the dispatch base;
this is not a claim of exact CI merge-base validation. No baseline/grant changes.
The six skipped persistence tests are not claimed verified.

## Acceptance audit

| # | Criterion | Executed evidence or remaining gap |
|---|---|---|
| 1 | Representative RC load profile | UNVERIFIED: profile inspected; it explicitly lacks user/Workspace populations, fan-out, successful tool/model calls and Design/Canvas traffic. No exact RC selected here. |
| 2 | Two production application replicas | UNVERIFIED: two ASGI middleware instances are not a production deployment. |
| 3 | Sustained saturation/reclaim/retry/leak observations | UNVERIFIED: no sustained production workload executed. |
| 4 | No duplicated physical work across replicas | UNVERIFIED: `scripts/soak/run_soak.py:1067` cancels the schedule admission probe without physical execution. |
| 5 | Replica-independent rate/security/degraded behavior | Counterexample reproduced by both identity cases at `tests/test_soak_promotion_gates.py:439`; `packages/maistro-server/src/maistro_server/api/rate_limit.py:94` creates independent limiters. Full production security/degraded behavior UNVERIFIED. |
| 6 | Production telemetry with thresholds | UNVERIFIED: profile has thresholds, but no current production samples. Driver loop lag is not application loop lag. |
| 7 | Active-work kill/restart drain/fencing/recovery | UNVERIFIED: no active-work interruption executed. |
| 8 | Long exact-RC soak | UNVERIFIED: `scripts/soak/run_soak.py:744` always rejects host preflight artifact equivalence; passing gate tests are not a four-hour RC soak. |
| 9 | Findings filed/reclassified before promotion | UNVERIFIED: local blockers documented; no GitHub mutation permitted or performed. |
| 10 | Published hash-bound machine/human soak evidence | UNVERIFIED: local validation logs/report are not an image/config-bound production soak pack. |

## Handoff

**BLOCKED**, not integration approval. Only this checkpoint changed. Historical
CI failure does not reproduce; exact-debt scan has no unbanked identities to
repair. Do not manufacture a ledger change or rerun host preflights as promotion
proof. Next work requires an immutable RC/configuration, representative
production workload coverage, replica-independent enforcement on the existing
security path, physical execution/recovery observations, and the long RC soak
with hash-bound evidence. These are substantive prerequisites, not scanner fixes.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0,
next: "production RC/workload and enforcement prerequisites; exact-RC soak"}`.

