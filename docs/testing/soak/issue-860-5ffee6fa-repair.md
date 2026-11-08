# Issue #860 — bounded repair round 5ffee6fa

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `3da96d3276685e40381df95e2182c8cab2295904` (clean).
- Supplied develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Evidence snapshot: supplied `dispatch-context.json`, previous result
  `ed41cfaf3ef446d49f4b8479de1aea36/result.json`, and reported failure
  `98a11313167b41a98a420abfda80c292/check-3.log`. No current check logs supplied.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  adjacent `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, and
  `quality/vulture-baseline.json` only if the required scan demonstrates drift.
- Acceptance review inputs: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  production rate-limiter wiring, deployment configuration, and relevant ADRs.
- Writable reporting files: this report and a matching inventory note only if
  test coverage changes. No other issues/PRs will be processed or re-enumerated.

## Initial evidence and assumption

The supplied historical check-3 log failed because the schema-fence test expected
21 statements while production emitted 24. This must be reproduced against the
assigned head before repair. The previous result reports missing exact-RC soak
proof; it is not accepted as fresh validation. No immutable RC deployment is
specified in the assignment; local/unit validation will not be called RC proof.

## Fresh results

- Required exact-argument vulture scan: PASS, 1,323 reviewed identities and
  findings, zero unclassified/never-allowlist. No ledger amendment warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  PASS, 37 passed / 6 skipped in 1.75s. The reported schema-fence failure is not
  reproducible: the current test already independently lists all 24 DDL statements,
  including the three Gauntlet columns at lines 175–177.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q -rs`: PASS,
  65 passed in 1.44s. Includes real production limiter instances demonstrating
  independent replica allowances and a CLI fail-closed test for four-hour
  host-preflight evidence; these are not a deployed RC soak.
- Production wiring confirmed: `maistro_server/main.py:648` installs the tested
  `RateLimitMiddleware`; `api/rate_limit.py:93` creates an in-memory limiter.

No execution authority, authorization path, or ledger grants will be introduced.
Existing committed evidence is preserved. No source repair is justified by these
checks.

- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites / 31,128
  unique identities, no copied evidence.
- `git diff --check`: PASS.
- All validation commands used 1,200-second timeouts. No live database or
  sustained production deployment was exercised. The six skipped core tests
  are not acceptance evidence.

## Architecture reconciliation

Read repository instructions, documentation authority hierarchy, and accepted
ADR-062, ADR-082126-f69c, ADR-082426-82c7 and ADR-082526-b36a. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`: schedule occurrence uniqueness is
an admission property, not proof of unique physical work; a process restarting is
not proof that an execution lease was reclaimed. No competing scheduler, store,
event authority, or authorization path was added.

Production Compose is a reference topology with two application services, not an
immutable release designation (`deploy/docker-compose.prod.yml:11`). The issue's
replica-selection requirement is stronger than the documented process-local
rate-budget policy (`packages/maistro-server/src/maistro_server/api/rate_limit.py:32`).
This discrepancy remains unresolved; it is not waived or silently replaced with
a new rate-limiting architecture in this evidence-only CI repair.

## Acceptance matrix

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Read `m3a-load-profile.md`; its remaining-gaps section excludes concurrent users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and sustained Goal/background-worker reconciliation. No selected RC justifies those exclusions. |
| At least two production replicas | UNVERIFIED. Compose defines two services, but executed tests use ASGI instances, not a deployed exact RC. |
| Sustained saturation, queue growth, reclaim, backoff and leaks | UNVERIFIED. No sustained RC run performed; sampler tests cannot substitute for these observations. |
| No duplicated physical work | UNVERIFIED. Canonical identity/admission tests do not establish active Attempt fencing across replicas or Goal reconciliation under load. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | UNVERIFIED with counterevidence. Executed `test_replica_selection_has_an_independent_production_allowance` for authenticated and anonymous identities: each instance independently accepts `[200, 200, 429]`. Production installs this middleware at `main.py:648`. |
| Complete telemetry and explicit thresholds | UNVERIFIED. Profile and process sampler exist, but no complete RC time series; driver-loop lag is not application-loop latency. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED. Gate/cleanup tests pass; no active-work deployed recovery experiment executed. |
| Long soak of exact RC/configuration | UNVERIFIED. `scripts/soak/run_soak.py:730` always rejects host-preflight artifact equivalence; executed four-hour-evidence CLI tests confirm rejection. Immutable promoted image/configuration not designated. |
| Findings filed/reclassified before promotion | UNVERIFIED. This report records blockers; no external disposition established and GitHub mutations are prohibited. |
| Machine/human evidence bound to exact hashes | UNVERIFIED for the RC. This report identifies the source head, not deployed image/configuration identity or load evidence. |

## Handoff

**BLOCKED.** Changed only this report. No tests were added or modified, so no
inventory delta is required. Vulture has no unbanked identities: no ledger edit
is justified despite permission to repair it. No sync conflict or uncommitted
incoming work existed. No GitHub mutations performed.

Next: designate the immutable RC and authorized deployment configuration;
resolve the replica-budget requirement mismatch; complete the representative
production-path workload and application telemetry; execute active-work recovery
and the profile's >=4-hour exact-RC soak. Any runtime/code/config change requires
a fresh soak. Another host smoke run cannot supply the missing proof.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 validation failures (6 database tests skipped). This focused validation
does not recertify the hundreds of historical branch artifacts. Commit this
report locally; do not integrate or close #860.
