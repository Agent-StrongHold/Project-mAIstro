# Issue #860 — repair validation fe13b354

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `714d43ace38acdfad726e9912603590b330c7ac1`; supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial worktree is clean; no incoming uncommitted work to salvage.
- Review targets: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, relevant accepted ADRs,
  supplied dispatch/prior-result evidence, and the exact vulture gate.
- Edit targets: this report; `quality/vulture-baseline.json` only if the
  executed scanner demonstrates reviewed retained unbanked identities.
  No speculative runtime changes or new execution authority.
- The job directory contains no `check-*.log` files at initial inspection.
  Read the specifically supplied historical failure separately; do not treat
  previous successful validation claims as current evidence.
- Ambiguity: no immutable promotion RC/configuration is designated in the
  assignment. Do not substitute the working branch or a host smoke run for it.

## Progress

- Exact vulture command executed successfully: 1323 findings, 1323 reviewed
  identities, zero unclassified/never-allowlist findings. No ledger amendment
  is justified; no scanner debt reproduced.
- The supplied historical `check-3.log` is a schema-fence test failure
  (24 statements versus 21 expected), not vulture debt. Current
  `test_pg_learnings.py:174-176` already includes the three omitted validation
  columns. Re-run that suite before declaring the historical defect resolved.
- Accepted ADR-081626-f383 requires canonical Attempt lease fencing;
  ADR-082126-f69c disallows a second schedule runtime; ADR-083026-a91e forbids
  interpreting unmeasured values as zero. ADR-081 remains Proposed, not an
  accepted exception to these contracts. No architectural reconciliation or
  alternative runtime is introduced.
- Current `preflight_artifact_check` explicitly fails exact-RC identity;
  `_terminalize_probe_run` cancels the schedule race without executing work.
  Existing rate tests exercise real production middleware but not a deployed
  RC: each replica grants an independent allowance.
- Additional validation targets are the exact historical failing suite
  `packages/maistro-core/tests/persistence/test_pg_learnings.py` and existing
  task-backpressure tests; these are evidence-driven checks, not edit targets.

## Executed validation

All commands ran in the assigned worktree with 1200-second command timeouts.

| Command | Observed result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0; 1323 reviewed identities = 1323 findings, zero unclassified |
| `uv run ruff check .` | all checks passed |
| `uv run ruff format --check .` | 3270 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 65 passed |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; historical schema-fence failure does not reproduce |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 1 passed |

The six skipped database integration cases are not production soak proof.
No tests were added or changed, so there is no suite inventory delta.
The supplied dispatch includes a draft #1672 and prior blocker reports; neither
is integration approval. No GitHub actions were taken.

## Acceptance disposition

| #860 criterion | Current evidence and disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `m3a-load-profile.md` defines a preflight profile and explicitly identifies missing concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and background reconciliation. No selected RC applicability decision supplied. |
| At least two deployed application replicas | UNVERIFIED for the selected RC. The passing middleware tests use ASGI instances, not deployed images. No new deployment run claimed. |
| Sustained saturation, growth, reclaim, retry and leak observations | UNVERIFIED. No sustained run performed this round; focused tests cannot replace these observations. |
| No duplicate physical work across replicas | UNVERIFIED. `scripts/soak/run_soak.py:1044` cancels the admission probe's Run without executing it. Passing admission tests do not establish physical-work uniqueness. |
| Rate/security/degraded non-bypass under concurrency | UNVERIFIED overall; independent allowances reproduced by both parameterizations of `tests/test_soak_promotion_gates.py:439`. Each real middleware instance returns 200, 200, 429 for the same identity. Six-path rejection probes prove local enforcement only. |
| Complete telemetry with explicit thresholds | UNVERIFIED. Profile distinguishes driver loop lag from application loop lag and process-group RSS from container/worker measurements; no complete exact-RC series executed. |
| Active-work kill/restart, graceful drain, fencing and recovery | UNVERIFIED. Boot cleanup regression tests pass, but do not establish the required active-work recovery contract. |
| Long unchanged exact-RC soak | UNVERIFIED/BLOCKED. No immutable RC/configuration designated. Three CLI regression cases pass by rejecting missing/null/preflight artifact evidence even at four hours. `scripts/soak/run_soak.py:730` explicitly returns a failed artifact check. |
| Findings filed/reclassified before promotion | Local findings recorded here. External disposition UNVERIFIED; GitHub mutations prohibited. |
| Machine/human evidence tied to exact hashes | UNVERIFIED for the promotion RC. This report records the tested source head, not an image/configuration-bound deployment run. |

## Handoff / stop condition

**BLOCKED**, not merge-ready. The requested scanner repair has no reproducible
scanner violation, and the historical test defect is already repaired at the
starting head. No speculative scanner edits, ledger churn, cosmetic code changes
or promotion-gate exceptions were made. Only this report is changed this round.

Next work requires an explicitly selected immutable RC plus deployment/runtime
configuration and representative surface applicability, followed by production
workload instrumentation that observes canonical physical Attempts and recovery,
then the documented >=4-hour unchanged-artifact soak. Local rate enforcement
must not be relabeled cluster-wide non-bypass. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; do not add a parallel scheduler or
execution authority to manufacture evidence.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0;
validation command errors 0; acceptance blocked 1. Next: RC selection and actual
production acceptance work, not another speculative vulture repair.
