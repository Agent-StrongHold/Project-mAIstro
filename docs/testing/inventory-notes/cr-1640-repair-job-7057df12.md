# CR1640 repair checkpoint — job 7057df12

## Frozen scope and salvage

- One item: assigned issue/PR #1640, delivery planner #1629; writer lane.
- Assigned worktree `/home/dev/Git/wt/cr-1640`, starting HEAD `56df7f7b3967199a108a2dba75b8011dff269e92`, supplied base `d0e8e235a896d2644b33852f64cbdca1766ec59e` both resolve.
- Frozen evidence: this job's dispatch-context.json and check-0/1/2.log, supplied prior result, existing branch diff, and the existing untracked checkpoint `cr-1640-repair-job-632b9b7f.md`. No refreshed remote enumeration.
- Initial log/status inspected. Tracked diff was empty. Existing untracked checkpoint backed up in the job directory, together with incoming-1640.patch; retained in place.
- Process only the reported container/SBOM/cosign failure, requested exact Vulture gate, delivery planner acceptance, and adjacent tests/configuration. Candidate files are the frozen branch diff plus directly referenced container workflow/dependencies, ADRs and tests. No unrelated changes or gate weakening.
- Ambiguity: prompt includes verifier-only no-edit text but explicitly assigns a writer repair with mandatory commit; proceeding as writer. Supplied failed-gate label is not itself a scanner finding; inspect evidence before changing production code.

## Initial results

- Supplied check-0.log: dependency sync passes; check-1.log: Ruff passes; check-2.log: 3,574 files formatted. Read the actual logs.
- Previous attempts left a verification checkpoint, not an uncommitted source repair. Prior result reports local container/Vulture success but final-head review/CI unverified. These claims require fresh validation.
- Environment: root has only 128 MiB free; /tmp 3.2 GiB. Do not rebuild large images blindly or delete unrelated artifacts. Record environment blockers rather than fabricate repairs.

## Fresh executed checks

- Required exact Vulture command: PASS, 1,236 reviewed identities = 1,236 findings, zero unclassified. No ledger change justified (log: job directory `vulture.log`).
- `uv run pytest tests/test_plan_delivery.py tests/test_check_required_checks.py tests/test_distribution_contract.py tests/test_mutation_targets.py -x -q`: PASS, 161 tests in 30.21s (`focused-tests.log`).
- Frozen dispatch's actual container job 133896873948 is SUCCESS at 1cbb30b829, not failed. The assigned starting head differs from that commit only in the round-3 evidence Markdown note. Its CI does not prove final-head CI/review; no speculative scanner repair justified.
- Read production planner, adjacent tests, current security workflow, accepted ADR-081226-a66b (canonical execution hierarchy) and ADR-082526-cb51 (explicit unmeasured coverage). Planner remains advisory/read-only and cannot change runtime authority. The issue's old scripts/ path is now tools/; historical no-workflow/ratchet-change claims are obsolete, not a reason to undo existing repairs.
- An initially guessed security-containers.yml path did not exist; skipped and inspected the tracked `.github/workflows/security.yml` identified in preserved evidence. It explicitly removes signing; the check name does not imply a cosign signing contract.

- Fresh bounded container checks: Trivy 0.73.0 (`--severity HIGH,CRITICAL --ignore-unfixed --ignorefile .trivyignore.yaml --exit-code 1`) and Grype 0.116.0 (`--fail-on high --only-fixed`) both PASS on the existing `hive-conductor:pr-cr1640-56df7f7b39` image. Logs in this job directory. Grype reports only Medium/Low findings; not a zero-vulnerability claim. Used a job-specific `/tmp` cache, without disabling DB updates.
- All five starting-head-named image tags exist, but Docker metadata has no Labels key: no immutable source provenance was established from tag names. These scan results prove that local image's scan status, not exact-head rebuild success. Rebuilds remain unsafe with the nearly full Docker/root filesystem; no artifacts deleted.
- Read the dated concrete residual plan and operator skill in full: explicit closeout/M1/M2/M3/release sequence, reuse exclusions, refreshed complete-census contract and unchanged external cadence are present. These are not claims that the dated seed is live or the external orchestrator was changed.

- Planner-only branch coverage: `uv run coverage run --branch --data-file <job>/planner.coverage -m pytest tests/test_plan_delivery.py -q` and `uv run coverage report ... --include='*/tools/plan_delivery.py' -m`: PASS, 56 cases, 99%, 236 statements / 62 branches, only line 395 (`__main__`) missed. This is local planner coverage, not the aggregate/diff CI gate.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS, 6,110 collected root-suite identities match inventory; zero copied-test duplicates. No count adjustment needed.
- Fresh `uv run ruff check .` and `uv run ruff format --check .`: PASS (3,574 files formatted).
- Additional executed production/CLI probes (`acceptance-probes.log`): all four slice kinds selected correctly; earlier milestone outranks a 1,000-point later milestone; effort/forecast limitations present; the unchanged dated seed exits 2 with moved-base/staleness/incomplete-census reasons and no selection. Both existing reservation regression tests pass against production and fail against an in-memory rollback that strips the named-task scope union. No worktree source was mutated for the regression experiment.

- Relevant workflow commands freshly executed: image inventory (all Dockerfiles dispositioned), image pins (9 pinned bases/tools), workflow inventory (32 workflows), execution lifecycles (19 classified/discovered) and doc links (3,235 Markdown files, zero broken links) all PASS. `git diff --check` passes.
- After bounded checks, root has 106 MiB free and /tmp 1.6 GiB free. A five-image rebuild plus full SBOM generation is not safe here. Full current-head container reproduction remains UNVERIFIED; neither a source failure nor a pass is inferred from this resource limit.

## Acceptance evidence (starting production bytes unchanged)

| Criterion | Evidence in this round |
| --- | --- |
| Separate slice kinds, canonical issue/source references | Read task validation/recommendation; all four kind probes pass; source references remain input bookkeeping. |
| Complete reviewed passed exact-base evidence only | Focused tests pass for partial, failed/skipped/error/pending, stale, self-reviewed and missing-trace evidence, plus dependency-closed completion. |
| Reject cycles, omitted dependencies, invalid scopes, ambiguous evidence | Existing adversarial tests and real CLI duplicate-key/invalid-JSON tests pass. |
| Preserve owners; serialize paths/resources; retain inactive reservations | Existing tests pass, including narrow/multiple named-task reservations; both narrow-scope regressions rejected in memory. |
| WIP bounded by active reservations; reuse owner | Existing WIP/cap, active-budget, owner-reuse and one-task-per-owner tests pass. |
| Suppress on moved base, stale input, incomplete census | Existing tests pass; actual unchanged seed CLI exits 2 with no selection. |
| Milestone/dependency ranking and explicit relative effort | Existing critical-chain/determinism tests and milestone-first probe pass; effort/selected-scope limitations inspected/asserted. |
| Concrete closeout/M1/M2/M3/release residual plan and reuse exclusions | Read `docs/planning/DELIVERY-PLAN-2026-09-27.md` in full. It is explicitly dated, not current fleet census. |
| Existing orchestrator input/refresh contract; no claimed cadence change | Read operator skill and actual CLI; command is local/read-only and never executes evidence commands or dispatches. No competing Goal/Graph/Run/NodeRun/Attempt authority introduced (accepted ADR-081226-a66b). |
| Adversarial tests and exact-head repository CI/review before merge | Local 161 focused tests, 56 planner cases/99% coverage and listed gates PASS. **Exact final-head aggregate/diff coverage, acceptance-state mandate, full container/SBOM reproduction and independent final review UNVERIFIED.** Frozen remote successes are for 1cbb30b829 only. |

## Handoff and disposition

No production source, dependency, workflow, grant, ledger or test change is justified by the actual findings in this round. In particular, the exact Vulture gate does not ask for retained-identity banking. No new tests were added, so no inventory delta is needed. Preserve the previous untracked checkpoint as a historical record alongside this current evidence note; its old base/resource statements are not current verification claims.

The frozen PR body remains stale (old published head, scripts/ path, 54 rather than 56 planner cases, and obsolete no-workflow/ratchet-change claim). Remote metadata edits are prohibited here. An authorized owner must reconcile it and obtain final-head CI/review. Do not equate prior-head successes or the local image tag with final-head approval. Do not rebuild until adequate filesystem capacity is available; do not delete unrelated artifacts to get it.

This round commits only the two checkpoint notes locally. Verdict: NEEDS-DEEP-REVIEW, not integration approval. One assigned item checked; implementation repairs not demonstrated necessary; validation handoff completed; merge acceptance remains unresolved. No push, comment, PR, merge, issue closure or waiver.
