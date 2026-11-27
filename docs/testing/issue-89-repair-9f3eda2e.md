# Issue 89: bounded repair round 9f3eda2e

## Frozen scope and initial state

- Assigned issue: #89 only; branch `auto-89` in `/home/dev/Git/wt/auto-89`.
- Starting head: `f8d4d1021df103f48ffe7d5073acdd2ad16bc302`.
- Assigned base: `c707949a0a98c9feff01b64c6ce405143b76b5d1`.
- Initial `git log --oneline -20`, `git diff --stat`, and `git status --short`: existing implementation and validation commits present; no uncommitted work to salvage.
- Snapshot: supplied `dispatch-context.json` and prior result `795e11baa48a440a916c315d6a99fd85/result.json`; no remote enumeration or mutations.
- Repair targets: queued ADR/spec front-matter gate, exact-debt-ledger vulture gate, prior release diff-coverage failure, and the eight acceptance criteria in the captured issue body.
- Existing implementation files to inspect (not presumed broken): `.github/workflows/release.yml`, `scripts/promote_release.py`, `scripts/release_guard.py`, `tests/test_promote_release.py`, `tests/test_release_guard.py`, and their existing inventory notes. Only evidence-backed repairs will be made.
- No `check-*.log` files were supplied in this job directory at initial inspection; execute local gates rather than treating prior claims as proof.
- Prior-attempt diagnosis: implementation artifacts now exist, but repeated validation rounds reported operational soak/promotion prerequisites missing. A queued check is not evidence of a source defect. This round will not manufacture soak evidence or repeat the no-artifact strategy.
- Ambiguity: prompt contains both verifier and writer directions. Proceed as assigned repair writer, preserving all existing work and committing the validation/handoff record. No GitHub actions, publishing, policy weakening, or execution-authority changes.

## Results

- `uv sync --locked --extra dev` — exit 0 (`check-sync.log`).
- Exact CI vulture command: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exit 0, 1218 reviewed identities / 1218 findings, unclassified 0, never_allowlist 0 (`check-vulture.log`). No evidence supports a ledger amendment.
- Captured PR #2536 review concerns RC `dist` retention; prior implementation retains it for 90 days. Captured #860 remains open with an explicit sustained exact-RC workload requirement. Prior artifacts distinguish repaired diff coverage from unverified operational acceptance.

- All seven `.github/workflows/registry.yml` validations — exit 0 (`check-registry.log`): registry/lifecycle pytest 194 passed; lifecycle lint; strict registry lint; citation provenance with the assigned immutable base; ADR index; generated spec index with zero diff; body-status language. Queued check did not reproduce as a failure.
- Release regression battery (703 passed) under `coverage run --branch --source=scripts`, followed by coverage XML and `scripts/check-diff-coverage.py --base c707949a0a98c9feff01b64c6ce405143b76b5d1` — exit 0 (`check-release-coverage.log`). This proves the diff portion, not the combined publish-set/service-backed hosted floor.
- Read accepted ADR-073126-c4e1, ADR-095, ADR-097 and inspected release guard/soak validators and adjacent tests. Reconciliation: actual publication is exclusively tag-triggered `release.yml` with protected human approval; local publishing or a new authorization path cannot substitute for the operational criteria. No execution-model change is in scope.

- Static battery — exit 0 (`check-static.log`): ruff check/format, suite inventory, release consistency, workflow inventory/write safety, 141 gate-policy/coverage tests, `git diff --check`.
- Mutation probe initially exited 1 (`check-byte-mutation.log`): `trylast=True` ran the hook after pytest's test call, so byte verification was not disabled when the test ran (1 passed). This is a probe-ordering error, not product failure; preserve the log and retry once with a pre-call hook wrapper.
- Production transport blocker independently inspected: `cmd_adopt_digests` downloads `SOAK_ARTIFACT` from `evidence["run_id"]` (`scripts/promote_release.py:578-583`), while `.github/workflows/release.yml:952-960` uploads that artifact on finals only. A compatible post-RC producer/transport is not demonstrated by this workflow. Injected GitHub seams in tests cannot prove that integration.

- Corrected process-local mutation — wrapper exit 0 (`check-byte-mutation-corrected.log`). A pre-call hook wrapper disabled only live `verify_dist`; the existing tampered-wheel regression failed at `tests/test_promote_release.py:509` (`assert 0 == 1`). The wrapper requires pytest exit 1 and restores the function. No tracked mutation or new test was introduced.
- Strict registry lint checked 447 files with 0 errors/warnings (199 existing test-evidence debts); citation exceptions 0. Ruff format checked 3699 files. Suite inventory: all 21 suites match, 37513 unique test identities, 0 duplicates. No tests added this round; inventory delta zero, existing +20 coverage-repair note remains applicable. No baseline, grant, or quality-ledger change warranted.

## Acceptance: local mechanism versus completed release

The full release battery command executed was:

```bash
COVERAGE_FILE=<job>/release.coverage uv run coverage run --branch --source=scripts -m pytest tests/test_promote_release.py tests/test_release_guard.py tests/test_check_release_consistency.py tests/test_release_publish_metadata.py tests/test_soak_compose_pressure.py tests/release/ tests/test_verify_wheel_imports.py tests/test_check_license_inventory.py tests/test_check_compliance.py -x -q
```

Here `<job>` is `/home/dev/maistro/jobs/9f3eda2ed62747458c059c6fb14b5479`.
All logs referenced above are in that directory. Registry pytest used
`tests/tools/registry/ tests/tools/test_lint_lifecycle.py packages/maistro-registry/tests --confcutdir=tests/tools -p no:cacheprovider -q`.
Static scripts were invoked as `uv run python scripts/<name>.py`; policy pytest
used `tests/test_check_required_checks.py tests/test_mutation_targets.py tests/test_check_diff_coverage.py -x -q`.

| Captured acceptance criterion | Reachable mechanism and executed evidence | Remaining operational acceptance |
| --- | --- | --- |
| RC artifacts built only from candidate commit | RC-only wheel/image build conditions in `release.yml:284,577,642`; record CLI captures real git identity and hashes; record/workflow tests pass in 703-test battery | Hosted candidate build UNVERIFIED |
| Clean install, real-model execution, security hot path, backup/restore during soak | `promote_release.py:286` requires each named passing check and citation; pinned-set and missing/failing-check rejection tests pass | Actual functional soak UNVERIFIED |
| Exact-RC sustained multi-replica workload including recovery, fencing, resource pressure, duplicate-work detection (#860) | `multi_replica_soak` required by pinned test; missing-soak CLI rejection test passes | Actual sustained workload, measurements and thresholds UNVERIFIED; fixture records are not observations |
| Invariant-invalidating findings filed/reclassified before promotion | `promote_release.py:306` rejects absent/malformed `routed_issue`; validator and CLI tests pass | Real routing and referenced issue contents UNVERIFIED |
| Code/runtime-config changes require new RC/applicable soak | `release_guard.py:190` selects latest numeric RC and compares git trees; real temporary-git tests reject content/config/mode changes | Deployed/external configuration equivalence and replacement soak UNVERIFIED |
| Final tag/tree byte-equivalent to soaked RC except non-runtime metadata | Exact tree guard and wheel hash checks pass; byte-verification mutant killed; finals adopt instead of build | Actual RC/final artifact pair and registry digest equivalence UNVERIFIED; no metadata exceptions exercised |
| External package/image/signature/install verification succeeds | Clean-venv install and cosign verify steps inspected; adjacent release tests pass | Actual independent external consumption/signature verification UNVERIFIED |
| Machine-readable soak evidence tied to exact promoted artifact/config | `promote_release.py:259` compares wheel/image maps and requires config identity; stale-binding/config rejection tests pass; final evidence staged under SHA256SUMS | Compatible real producer/transport, real evidence and deployed-config binding UNVERIFIED |

## Disposition and owner handoff

**BLOCKED.** No named local gate failure reproduced, so no speculative source,
ledger or gate repair is justified. This round changes only this validation
record; all prior implementation and test work remains intact. The formerly
red diff-coverage portion is green, but the full combined service-backed
publish-set coverage floor and hosted check status remain UNVERIFIED.

The unresolved seam is not just a missing test run: `scripts/promote_release.py:44-57`
requires schema-1 evidence on the selected successful RC run, while the inspected
workflow uploads it only on finals. A unit-test fake cannot prove the producer
or transport exists. Do not adapt the gate to accept #860's native boolean
schema or manufacture passing evidence. Release/soak maintainers must establish
compatible evidence production/transport, execute the exact-RC functional and
sustained workloads, route findings, promote through the protected workflow,
and verify external artifacts. Trusted publishers, environment approval and
registry permissions remain UNVERIFIED here. No new scheduler, store, event
authority, authorization path, tag, publication or GitHub mutation was created.

Progress: checked 1 issue; done 1 bounded validation/handoff; skipped 0;
errors 1 local mutation-probe ordering error (corrected); next: release/soak
owner action, not another speculative scanner repair.

Final checks (`check-report.log`): `uv run python scripts/check-doc-links.py`
passes (3625 Markdown files, 0 broken links); backlog consistency passes
(167 items); `git diff --check` passes. `git diff --numstat` against the assigned
base for `quality/` and `docs/testing/inventory/` is empty: no ledger/baseline
rows changed or lost. Only this new report is staged for a local commit; no
push, integration approval, release operation or issue closure is authorized.
