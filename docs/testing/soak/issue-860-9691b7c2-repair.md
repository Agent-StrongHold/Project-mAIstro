# Issue #860 repair checkpoint — 9691b7c2

## Frozen scope

- Issue: #860 only; branch `auto-860`, starting HEAD
  `7a42bf55a00dfd9464bc9ab50061b0e47918e683`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Clean worktree at entry; no incoming edits to salvage.
- Inspect the supplied dispatch snapshot and prior result; do not refresh GitHub.
- File scope: this report, `quality/vulture-baseline.json` only if the exact
  scanner identifies retained debt, and existing soak runner/profile/tests plus
  their production call sites for validation (no speculative runtime changes).
- Current job directory contained no `check-*.log` at entry. The explicitly
  supplied prior `check-3.log` will be inspected instead.
- Assumption: this is a writer CI-repair round. Ledger changes are permitted only
  for actual scanner evidence. Passing local gates is not exact-RC soak proof.

## Progress

- `uv sync --locked --extra dev`: PASS (214 installed packages checked).
- Exact requested vulture scan: PASS, 1,323 reviewed identities / 1,323
  findings, zero unclassified and never-allowlist findings. No ledger amendment
  is justified. Scanner-selected baseline is `4aa68edc0b6b`, not the supplied
  develop base; that distinction is retained rather than silently overridden.
- Historical `98a113.../check-3.log` failed a 21-versus-24 DDL statement assertion
  in the learning-schema fence test. Fresh command
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q -rs`
  passes: **102 passed, 6 skipped**, 2.06 seconds. Skips explicitly require
  `MAISTRO_TEST_PG_DSN`; they are not live-database evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,270 files already formatted.

The reported deterministic failures are not reproduced. No source/test repair
or test-inventory delta is justified by those results. Unit tests do not certify
an RC deployment.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites, 31,128
  unique identities, zero duplicate evidence.
- `git diff --check`: PASS. Validation commands used 1,200-second timeouts.

## Architecture and reachable behavior

Read `AGENTS.md`, `docs/README.md`, accepted ADR-062 (including retirement of
its old execution entry point), ADR-082126-f69c, ADR-082426-82c7, and
ADR-082526-b36a. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
An occurrence claim demonstrates admission uniqueness, not physical-work
uniqueness; process restart is not proof of lease reclamation. No competing
scheduler, store, execution authority or authorization path is introduced.

The current schema test independently includes the three Gauntlet columns
(`packages/maistro-core/tests/persistence/test_pg_learnings.py:175`); production
lists them at `pg_learnings.py:116` and executes upgrades behind the transaction
lock at `pg_learnings.py:215`. Thus the historical missing-column expectation
is already repaired, without weakening the fence assertion.

`packages/maistro-server/src/maistro_server/main.py:648` installs
`RateLimitMiddleware`, whose constructor creates an in-memory limiter
(`api/rate_limit.py:93`). The executed authenticated/anonymous parametrizations
of `tests/test_soak_promotion_gates.py:439` each reproduce `[200, 200, 429]` on
both instances for the same identity. Local enforcement works, but selecting a
second replica increases the allowance. The documented N-times-limit policy
at `api/rate_limit.py:32` does not prove #860's stronger non-bypass requirement.
This policy mismatch is UNRESOLVED; no new shared authorization or limiting
architecture is invented in a CI-repair round.

`deploy/docker-compose.prod.yml:11` calls itself a reference requiring pinned
images, not a designated immutable RC. `scripts/soak/run_soak.py:730` always
fails host-preflight artifact equivalence. The executed CLI tests at
`tests/test_soak_promotion_gates.py:103` prove even synthetic four-hour evidence
cannot bypass that check. They do not run a four-hour experiment.

## Acceptance review

| Issue criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC workload | UNVERIFIED. `m3a-load-profile.md` explicitly omits concurrent users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and sustained Goal/background activity. No selected RC justifies exclusions. |
| At least two deployed application replicas | UNVERIFIED. Compose declares two services; ASGI middleware tests are not a deployed RC. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED. No sustained deployment experiment executed; passing unit tests cannot supply those observations. |
| No duplicate physical work across replicas | UNVERIFIED. Admission/occurrence counts are not physical Attempt fencing or sustained Goal reconciliation evidence. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | UNVERIFIED with counterevidence: real middleware instances independently accept the same identity after the first exhausts its local budget. |
| Complete telemetry with explicit thresholds | UNVERIFIED. Profile has thresholds but no fresh RC series; driver-loop latency is not application-loop latency. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED. No deployed active-work recovery experiment executed. |
| Long soak of exact RC/configuration | UNVERIFIED. No immutable RC designated; current runner deliberately rejects host-preflight certification regardless of duration. |
| Findings filed/reclassified before promotion | UNVERIFIED. Blockers recorded here; external disposition not established. GitHub mutations prohibited. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED for the RC. This report binds local validation to the starting source head, not to a deployed image or load experiment. |

## Handoff

**BLOCKED**, not integration approval. Only this report changed; no test additions,
source changes, inventory changes, ledger edits, grant edits or GitHub mutations.
No merge conflict exists. Existing artifacts remain preserved; historical soak
results were not recertified by these local checks. Six database tests remain
skipped, and all ten promotion criteria remain unproven.

Next required inputs/actions: designate immutable RC images and authorized runtime
configuration; reconcile replica-budget semantics; complete representative
production-path workload and application telemetry; execute active-work recovery
and the profile's >=4-hour exact-RC soak. Re-soak after runtime/code/config changes.
Do not repeat host preflight and call it promotion proof.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 fresh validation failures. Local report commit completes this bounded
repair investigation, not issue #860.
