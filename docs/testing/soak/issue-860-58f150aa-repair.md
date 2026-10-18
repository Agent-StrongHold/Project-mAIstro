# Issue #860 repair checkpoint — 58f150aa

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`3f176f5f66ebd8bab898106a632635bb96601b36`, supplied base
`2f56be40ad241262b0384ab0b97834ebd37fe4d7`. Initial tree clean.
No other issues/PRs will be processed or GitHub state changed.

Repair surfaces: this report; `packages/maistro-core/tests/persistence/test_pg_learnings.py`
if the reported failure reproduces; `quality/vulture-baseline.json` only for actual
reviewed scanner findings under the explicit ledger-repair exception; an inventory
note if tests change. Read-only validation includes adjacent persistence code,
existing soak runner/tests/profile and rate-limit regressions, governing ADRs and CI gates.

Evidence supplied: prior `check-3.log` reports 24 schema statements versus 21
expected; prior result reports missing production soak acceptance. Neither is
assumed current. No `check-*.log` files were present in this job directory at start.
Assumption: this is a bounded CI-repair pass, not permission to invent an RC
artifact/configuration or replace the canonical execution/authorization model.

## Results

Required vulture scan executed successfully: 1322 findings matched 1322 reviewed
identities; zero unclassified/never-allowlist findings. No ledger amendment is
justified. Current schema-fence test already lists the three validation audit
columns missing from the historical failure (lines 174–176).
Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
37 passed, 6 skipped. The supplied historical failure does not reproduce.
`uv run pytest tests/test_soak_promotion_gates.py -x -q`: 72 passed.
`uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
26 passed. The existing two identity parametrizations independently reproduce
replica-local allowances, not cluster-wide protection. No new tests or inventory
delta are needed for a non-reproducing historical failure.
`scripts/soak/README.md` was not found; skipped (use the existing load profile).
## Additional validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.
- `uv run python scripts/check-ratchet-provenance.py`: passed, 53 consumers.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git diff --check`: passed (also checked before commit).
- Gates used their default resolved baseline `ab8b3737fa64`, as printed by the
  tools; this is not the dispatch's supplied develop base. No baseline/grant
  was modified and no claim of exact CI merge-base validation is made.

Read accepted ADR-085, ADR-081226-69ee, ADR-081626-f383 and ADR-082526-b36a.
The later TTL/renewal/reclaim contract extends the earlier fencing boundary;
its production soak proof is still required. Preserve the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt model and existing authorization.
The first attempted b36a filename was not found; the repository-listed actual
file was then read. No unresolved ref or missing path was used for execution.

## Acceptance audit

| # | Criterion | Current evidence / disposition |
|---|---|---|
| 1 | Representative RC workload | UNVERIFIED: `m3a-load-profile.md` explicitly lacks concurrent user/Workspace populations, Graph fan-out, successful tools/models and Design/Canvas traffic. No selected exact RC configuration was validated. |
| 2 | Two production replicas | UNVERIFIED: ASGI instances exercised production middleware, not a production deployment. |
| 3 | Sustained load, saturation, reclaim, retries and leaks | UNVERIFIED: no sustained production run executed. Unit tests do not establish these observations. |
| 4 | No duplicate physical work | UNVERIFIED: `scripts/soak/run_soak.py:1067` cancels the admission-only schedule probe without execution; it cannot prove physical Attempt uniqueness or sustained Goal reconciliation. |
| 5 | Replica-independent rate/security/degraded enforcement | Counterexample executed: both identity cases of `tests/test_soak_promotion_gates.py:439` exhaust one instance then obtain two additional successes on the second. `api/rate_limit.py:94` constructs independent limiters, registered in production at `maistro_server/main.py:648`. Full production security/degraded behavior remains UNVERIFIED. |
| 6 | Production telemetry and explicit thresholds | UNVERIFIED: profile thresholds exist, but no current production metrics collected; driver loop lag is not application loop lag. |
| 7 | Kill/restart active work with drain/fencing/recovery | UNVERIFIED: no active-work interruption executed; process rejoin alone would not prove this. |
| 8 | Long exact-RC soak | UNVERIFIED: `scripts/soak/run_soak.py:744` always rejects host preflight artifact equivalence. Executed gate tests are not a four-hour production soak. |
| 9 | Findings filed/reclassified | UNVERIFIED: local blockers recorded; no GitHub mutation permitted or performed. |
| 10 | Published hash-bound machine/human evidence | UNVERIFIED: this report is local validation evidence, not a production image/config-bound soak pack. |

## Disposition

**BLOCKED.** The historical CI defect is already repaired; the required scanner
found no debt to amend. No speculative source/test/ledger change is justified.
Only this report changed; no tests were added, so no inventory delta is required.
Six live-database tests skipped and are not claimed verified.

Next: select an immutable RC/configuration, complete representative production
workloads, establish replica-independent enforcement through the existing security
path, observe physical execution and recovery, then run the long exact-RC soak
and publish hash-bound evidence. Do not repeat host preflight runs as a substitute
or weaken promotion gates. This is not integration or promotion approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0,
next: "production RC/workload and enforcement prerequisites; exact-RC soak"}`.
