# Issue #860 — repair checkpoint (817760c1)

## Frozen scope

- Assigned item: #860 only, branch `auto-860`, starting HEAD
  `aee29c695fb7b55171e16db2dc6653f98e302443`; worktree initially clean.
- Inspect repository instructions, applicable deployment/convergence ADRs,
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-{load-profile,soak-evidence}.md`, existing round-six
  evidence, production rate middleware and adjacent tests, and CI gate wiring.
- Execute the requested vulture scan. Amend `quality/vulture-baseline.json`
  only if actual scan findings justify a reviewed retained identity.
- Run focused tests and lint/format gates. Record outcomes here and commit.
- No runtime/authorization redesign, new scheduler, remote mutations, or
  unsupported promotion certification.

## Initial evidence / ambiguity

The provided job directory contains `events.jsonl`, `manifest.json`,
`prompt.txt`, and `state.json`, but no `check-*.log` files. Driver checks are
therefore unavailable, not assumed successful. The prior result exists and
reports BLOCKED; its claims will be rechecked locally. The assignment is a
writer repair, not the read-only verifier role. No RC artifact/configuration
identifier was supplied; historical host-process runs cannot establish the
required exact-RC acceptance.

## Results

The requested vulture command passed: 1360 reviewed identities / 1360
findings, zero unclassified and zero never-allowlist findings. Its default
provenance selected base `045cfdfbe3ea`, candidate `aee29c695fb7`; it did not
use the assignment base. No scanner-backed ledger edit is warranted.

The current H3 evidence text already disclaims shared rate-limit state and
replica-selection non-bypass; the prior contradictory prose is not present.
The profile explicitly identifies missing multi-Workspace, fan-out,
Design/Canvas, successful provider, Goal and physical-work coverage. These
are acceptance gaps, not waivers.

Executed with 1200-second timeouts:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2809 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`:
  **80 passed, 5 skipped** in 2.85 s. The five skips require
  `MAISTRO_TEST_PG_DSN` and a migrated PostgreSQL database; no fresh database
  concurrency proof is claimed.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 46 consumers
  have explicit provenance. Non-fatal existing invalid-escape and local
  HTTP CORS warnings appeared.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.

Existing regressions exercise real rate middleware (including independent
allowances for the same identity on two instances), real canonical task
admission backpressure, and a live sampler subprocess. Mocked HTTP soak
probes and synthetic CLI evidence fixtures do not constitute deployed load.

Read ADR-085 (Accepted, principal-keyed limits), ADR-081626-f383 (Accepted,
Attempt fencing), ADR-082426-82c7 (Accepted, occurrence admission identity),
and ADR-081 (Proposed, not accepted deployment authority). The actual
`deploy/docker-compose.prod.yml:26-76` specifies two application replicas.
Admission uniqueness cannot establish physical-work fencing. ADR-085 does
not establish a shared limiter backend. Preserve the canonical execution
and identity paths; the replica-selection mismatch needs an explicit
resolution, not an acceptance waiver or guessed runtime redesign.

Executed `uv run python -` to import the current runner and evaluate the
three historical evidence packs named by the profile/evidence document.
Assertions that each fails both `sustain_duration` and `exact_rc_artifact`
passed:

| Pack | Recorded seconds | Current failed gates |
|---|---:|---|
| `m3a-soak-evidence.json` | top-level value absent | rate limit, LB failover, nonterminal Runs, admission availability, duration, artifact, drain |
| `m3a-round5-final.json` | 90.17 | rate limit, duration, artifact |
| `m3a-round6-shakedown.json` | 90.43 | duration, artifact |

This re-evaluates records; it does not replay traffic or validate their
historical claims. In particular, old H3 booleans do not establish today's
six-path coverage. No Docker deployment or long-running soak was performed.

## Acceptance disposition

| Criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC load profile | PARTIAL: profile and production request mix inspected (`run_soak.py:728-759`); concurrent users/Workspaces, fan-out, Design/Canvas, successful model/tool work and background workers UNVERIFIED. |
| Two application replicas | Production Compose declares two; host preflight historical evidence does not prove two exact-RC replicas. UNVERIFIED. |
| Sustained saturation, growth, leases, retries and leaks | Historical packs fail duration in the current evaluator; live sampler unit regression passed, not a sustained application test. UNVERIFIED. |
| No duplicate physical work / canonical admission / Goal reconciliation | Admission-oracle regressions passed; schedule probe races admission then terminalizes the probe Run (`run_soak.py:982-1068`). Physical effects and Goal reconciliation UNVERIFIED. |
| Rate/security/degraded non-bypass | NOT MET for shared allowance: executed production-middleware tests demonstrate another allowance on replica 2 after replica 1 rejects the same identity. `rate_limit.py:25-30,73-78` explicitly creates local state. Broader security/degraded behavior under sustained load UNVERIFIED. |
| Complete telemetry and thresholds | `run_soak.py:465-485` queries DB sessions/locks/Run status; `1304-1312` samples driver, not application loop lag. Full application/worker telemetry and enforced thresholds UNVERIFIED. |
| Active-work kill/restart/drain/fencing/recovery | Historical run-six drain/rejoin counts do not correlate physical Attempt effects. No fresh active-work recovery executed; UNVERIFIED. |
| Long-running exact RC, rerun on changes | NOT MET: round six is 90.43 s vs 14400 (`m3a-round6-shakedown.json:221-224`), and `run_soak.py:635-646` rejects host-preflight artifact equivalence even at four hours. No selected immutable RC image/configuration supplied. |
| Findings filed/reclassified before promotion | Local findings inspected in `m3a-soak-evidence.md`; earliest M3-A evidence-validity classification exists for F11/F12. External filing UNVERIFIED; GitHub mutations prohibited. |
| Human/machine evidence tied to exact hashes | Historical documents/JSON exist but cannot certify production image/config equivalence. Exact-RC hash-bound promotion evidence UNVERIFIED. |

## Handoff

**BLOCKED.** Required CI repair scan is green with no unbanked identities;
there is no evidence-backed ledger or dead-code repair to make. Only this
checkpoint document changed. No tests added/removed, so no inventory delta
is necessary. No runtime/configuration or raw evidence changed. No remote
mutations or background work.

Next: explicitly select the immutable RC image/configuration and provider
setup, resolve the replica-selection allowance contract, complete the
representative production-path workload and telemetry, then execute and
publish a minimum four-hour exact-RC soak with physical-work recovery
correlation. Do not rerun the host preflight merely to spend four hours: it
cannot satisfy the artifact gate. Do not send this lane through another
ledger repair without an actual failing gate log.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 command failures (5 integration-test skips). The scanner-validation
subtask is complete. Commit this report locally; no promotion or integration
approval is implied.
