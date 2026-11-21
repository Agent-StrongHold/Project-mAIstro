# Issue #860 — repair validation fed13f53

## Scope and checkpoint

Only issue #860, worktree `/home/dev/Git/wt/auto-860`, starting commit
`b35f3b930a7bec00407a27c69ad7262eb88f108f`, supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Both resolve; initial tree clean.
Frozen repair surface: this report and the vulture ledger only if the prescribed
scan demonstrates actual unbanked retained identities. No remote mutations.
Writer assignment takes precedence over generic verifier wording.

The job directory supplied no driver `check-*.log`. Read the explicitly named
prior `98a11313167b41a98a420abfda80c292/check-3.log`: it fails the schema-fence
assertion (24 DDL calls versus 21), not the vulture gate. Do not guess debt from
that historical failure.

Fresh validation logs are in
`/home/dev/maistro/jobs/fed13f532f5d4b1b859f24bc1ba3f75c/`:

- `worker-vulture.log`: prescribed `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` passes;
  1,323 findings / 1,323 reviewed identities, zero unclassified/never-allowlist.
  No ledger amendment justified.
- `worker-pytest.log`: `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py -x -q -rs` passes: **102 passed, 6 skipped**.
  All six skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL claim.
  This re-executes the named failing schema test and the actual production
  middleware replica-selection counterexample, not just a summary assertion.

Read repository instructions, documentation authority hierarchy and accepted
ADR-062, ADR-082126-f69c, ADR-082426-82c7, ADR-082526-b36a. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Admission uniqueness is not
physical-work fencing, and a restarted process is not lease-recovery evidence.
No alternative execution or authorization mechanism will be introduced.

## Acceptance review

Reviewed the current load profile, actual harness artifact gate, adjacent tests,
and `maistro_server.api.rate_limit.RateLimitMiddleware`. The middleware creates
an `InMemoryRateLimiter` per instance (`rate_limit.py:94`); its documentation
explicitly promises only process-local enforcement (`rate_limit.py:32`). The
executed test at `tests/test_soak_promotion_gates.py:439` exhausts the same
identity on replica one then obtains another `[200, 200, 429]` on replica two,
for authenticated and anonymous identities. These are actual middleware ASGI
instances, not deployed RC replicas. Local enforcement does not establish the
issue's stronger no-replica-selection-bypass requirement. Do not silently waive
that requirement or add a competing authorization path.

| Acceptance criterion | Executed evidence / disposition |
| --- | --- |
| Representative release workload | UNVERIFIED: profile explicitly lacks multi-user/Workspace populations, Graph fan-out, successful model/tools, Canvas/Design and Goal reconciliation. |
| Two application replicas of supported production profile | UNVERIFIED: middleware test uses two ASGI instances, not deployed RC images. No production soak executed this round. |
| Sustained saturation, queue growth, reclaim, backoff and leaks | UNVERIFIED: process-group sampler tests pass, but no sustained RC workload or reclamation observation. |
| No duplicate physical work across replicas | UNVERIFIED: admission probes validate canonical IDs, not physical Attempt execution or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | UNVERIFIED acceptance with reproduced counterevidence: both identity classes receive independent allowances on each production middleware instance. |
| Required telemetry and explicit thresholds | UNVERIFIED: sampler tests cover child RSS/descriptors; driver loop lag is not application-loop lag, and no complete production threshold series was captured. |
| Active-work kill/restart proves drain/fencing/recovery | UNVERIFIED: evaluator and boot-cleanup tests pass; no live active-Attempt recovery experiment executed. |
| Long soak of exact promoted RC/configuration | UNVERIFIED: `scripts/soak/run_soak.py:730` always rejects host-preflight artifact equivalence. All three four-hour-preflight rejection cases pass. No immutable promoted RC/configuration was designated in the assignment. |
| Load findings filed/reclassified before promotion | UNVERIFIED: local historical dispositions are not newly verified external closure evidence; GitHub mutations prohibited. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED for the exact RC: this report identifies source and fresh local checks, not a production soak. |

## Final validation and outcome

- `uv run ruff check .`: passed (`worker-ruff-check.log`).
- `uv run ruff format --check .`: passed, 3,270 files already formatted
  (`worker-ruff-format.log`).
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites,
  31,128 unique identities, no copied evidence (`worker-inventory.log`).
- `git diff --check`: passed.
- No tests added or modified; no inventory delta required. No source, ledger,
  grant, gate, runtime configuration or historical evidence edits.

**BLOCKED** for issue acceptance, not a currently failing vulture gate. This
round changes only this report and commits it locally. The historical DDL test
failure is already repaired in the starting tree: the current independent DDL
list includes the three Gauntlet columns. No evidence warrants another repair.
The previous blocker cannot be resolved by relabeling host preflight evidence or
running it longer; a production RC target and representative runner are needed.

Next: designate immutable images and normalized production configuration plus an
authorized environment; reconcile the replica-budget requirement; exercise the
canonical production workload and active-work recovery with full telemetry; run
the >=4-hour exact-RC soak and publish hash-bound evidence. Runtime/configuration
changes require a fresh soak. Existing branch-wide changes and earlier reports
were preserved, not recertified by this bounded round.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 executed validation failures; 6 database integration tests skipped.
Residual risks are the ten unproven acceptance criteria above. No integration
approval, push, issue closure or other GitHub mutation.
