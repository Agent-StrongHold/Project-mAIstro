# Issue #860 — bounded CI repair 9c8273ba

## Frozen scope

- Issue: #860 only; branch `auto-860`.
- Starting HEAD: `d09ab1e382b01873da570b41541026a57b5ba5cc`.
- Supplied develop base: `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Worktree clean on entry; no incoming edits to salvage.
- Read-only evidence: supplied dispatch snapshot, prior result/check log,
  repository instructions, relevant ADRs, soak implementation/adjacent tests,
  vulture checker and affected identities if the scan reports any.
- Candidate edits: this report and `quality/vulture-baseline.json` only if the
  mandated scan establishes retained unbanked identities. No speculative repairs,
  new execution authority, gate weakening, or GitHub mutations.
- Assumption: this is the writer CI-repair lane, not the read-only verifier lane.
  No check logs exist in the current job directory at entry; inspect the supplied
  previous failed check instead. Production acceptance is not inferred from tests.

## Progress

Initial snapshot recorded. Prior result reports BLOCKED with all ten production
acceptance criteria unverified; those claims will be checked against current code
and executed focused validation, not adopted as successful verification.

- Mandated vulture command passed: 1322 reviewed identities, 1322 findings,
  zero unclassified or forbidden identities. No ledger change is justified.
- Supplied prior `check-3.log` failed because the schema-fence test expected 21
  DDL statements and observed 24. Current test already explicitly includes the
  three Gauntlet audit columns; rerun the test rather than duplicate the repair.
- Accepted ADR-082426-82c7 puts occurrence uniqueness on the canonical Run;
  ADR-082826-b601 requires physical execution through canonical NodeRun/Attempt.
  Admission-only probes cannot establish physical-work uniqueness.
- `scripts/soak/README.md`: not found; skipped. No further search for that path.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py -x -q`: 109 passed, 6 skipped. The supplied
  historical failure no longer reproduces. Skips are not acceptance evidence.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  3301 files already formatted.
- Current `preflight_artifact_check` explicitly rejects host-process artifact
  equivalence; the executed CLI regression rejects even synthetic four-hour
  evidence without exact-RC proof. `_terminalize_probe_run` explicitly describes
  an admission-only schedule race, not physical execution.
- Executed `test_replica_selection_has_an_independent_production_allowance`
  (both authentication cases) proves that the same identity gets [200, 200, 429]
  from each independent production middleware instance. This matches
  `maistro_server/api/rate_limit.py`'s documented process-local contract, not
  a cluster-wide non-bypass guarantee. No alternate authorization path is added.
- An attempted lookup of Hive `app.py` / `middleware/rate_limit.py` found neither
  path; skipped. The relevant production middleware is the server path imported
  by the executed regression tests.

## Acceptance review (production, not synthetic fixture success)

| # | Criterion | Current evidence / remaining obligation |
|---|---|---|
| 1 | Representative profile | UNVERIFIED: `m3a-load-profile.md` defines a degraded single-key preflight; its remaining-gaps section excludes multi-user/Workspace population, fan-out, successful tool/model calls, Design/Canvas and Goal workers without selected-RC justification. |
| 2 | Two production application replicas | UNVERIFIED: driver starts host uvicorn replicas, not the promoted production Compose topology. |
| 3 | Sustained saturation/reclaim/retry/leak observations | UNVERIFIED: no new long-running production soak executed; profile minimum is 14400 seconds. |
| 4 | Physical-work uniqueness | UNVERIFIED: `run_soak.py:1070` cancels an admission-only schedule probe without execution; ADRs require the canonical NodeRun/Attempt spine. |
| 5 | Replica-independent rate/security/degraded enforcement | UNVERIFIED, contrary allowance evidence reproduced: `tests/test_soak_promotion_gates.py:439` proves fresh per-replica budgets with production middleware. Local enforcement is intentionally not a shared budget. |
| 6 | Complete production telemetry with thresholds | UNVERIFIED: profile identifies driver-loop lag, dedicated DB probe and process-group measurements, not application-loop lag, complete worker/cgroup coverage or full production query/pool observations. |
| 7 | Active physical work kill/restart/recovery | UNVERIFIED: process exit/rejoin and terminal Run totals do not establish in-flight Attempt fencing or absence of physical duplication/loss. |
| 8 | Exact RC long soak | UNVERIFIED: `run_soak.py:744` always rejects artifact equivalence; executed CLI tests reject missing/null/preflight artifact records even with synthetic four-hour evidence. |
| 9 | Findings disposition before promotion | UNVERIFIED: historical evidence pack records findings, but complete current production findings disposition is not established. No GitHub mutations permitted. |
| 10 | Exact promoted image/package/commit/config evidence | UNVERIFIED: preflight hash records cannot substitute for immutable promoted image/config identities and a new production run. |

No production code or tests changed, so no inventory delta is required. The
supplied CI failure is already repaired at entry and the exact-debt scan has no
unbanked findings. This round records executed validation, not a cosmetic code
repair or acceptance waiver.

## Final validation and handoff

- `uv run python scripts/check-ratchet-provenance.py`: passed (53 quality JSON
  consumers have explicit provenance; delegated gates passed). Two existing
  invalid-escape SyntaxWarnings were non-fatal.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git diff --check`: passed.
- Executed a Python import of the current soak evaluator against the frozen
  historical `evidence/m3a-round30-shakedown.json`: observed 420.08 seconds,
  required 14400; failed checks exactly `sustain_duration`, `exact_rc_artifact`.
  Assertions confirmed both failures. This is historical evidence evaluation,
  not a new soak or an attestation of that old run's contents.

Verdict: **BLOCKED** on production acceptance, not the now-passing reported CI
failure. Only this report changed. No test count change, ledger edit, runtime
change, merge, push, or GitHub mutation. No new production load was launched:
spending four hours on a driver that explicitly cannot execute the exact RC
would not satisfy the acceptance criterion.

Progress: checked 1 assigned issue, done 0 acceptance-complete issues, skipped 0
issues, errors 0 final validation commands. Next: select the immutable RC
image/configuration and production topology, complete the representative workload
and physical Attempt observations, resolve the replica-budget contract gap, then
run and publish a fresh >=4-hour exact-RC soak. Preserve all existing artifacts.
