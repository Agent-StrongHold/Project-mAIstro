# Issue #89 current repair validation

## Current round: supplied head `a68a3a1b2369`, base `80242f28521b`

Job `2f3dd344705a44c18915548dfb7ced54`, branch/worktree `auto-89`.
The initial worktree was clean. Preserved all prior implementation, tests,
and reports. Frozen scope: issue #89, supplied dispatch/PR evidence, named
Vulture/front-matter gates, existing coverage repair and adjacent release
checks. No `check-*.log` files were supplied in this job directory; the logs
below were generated here. No remote enumeration or GitHub mutations occurred.

**Diagnosis:** earlier rounds fixed the coverage failure, but reported BLOCKED
because actual RC/soak/promotion evidence was absent. A queued front-matter
check is not a reproduced failure. This round independently tested that
assessment; no evidence justified a source, gate, or ledger repair.

### Fresh execution

All commands use `uv run` (dependency setup: `uv sync --locked --extra dev`).
Logs reside in `/home/dev/maistro/jobs/2f3dd344705a44c18915548dfb7ced54`.

- Named exact-debt gate: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS, 1219 reviewed identities / 1219 findings, unclassified 0,
  never_allowlist 0 (`check-vulture.log`). No ledger amendment warranted.
- All seven validation steps of `.github/workflows/registry.yml` — PASS
  (`check-registry.log`):
  - `uv run pytest tests/tools/registry/ tests/tools/test_lint_lifecycle.py packages/maistro-registry/tests --confcutdir=tests/tools -p no:cacheprovider -q`
    — 194 passed.
  - `uv run python tools/lint_lifecycle.py` — baseline 0, clean.
  - `uv run python -m maistro_registry.cli lint . --strict` — 447 files,
    0 errors/warnings, 199 existing test-evidence debts.
  - `RATCHET_BASE_REV=80242f28521bba184f4d5d62cda972c1c8928f36 uv run python scripts/check-citation-status-provenance.py`
    — 0 exceptions.
  - `uv run python scripts/check-adr-index.py` — consistent.
  - `uv run python scripts/generate-spec-ac-defined-index.py` and
    `git diff --exit-code docs/specs/README.md` — 57 specs, no diff.
  - `uv run python scripts/check-adr-status-language.py` — 0 contradictions.
- `COVERAGE_FILE=<job>/release.coverage uv run coverage run --branch --source=scripts -m pytest tests/test_promote_release.py tests/test_release_guard.py tests/test_check_release_consistency.py tests/test_release_publish_metadata.py tests/test_soak_compose_pressure.py tests/release/ tests/test_verify_wheel_imports.py tests/test_check_license_inventory.py tests/test_check_compliance.py -x -q`
  — **703 passed**. With the same coverage file,
  `uv run coverage xml -o <job>/release-coverage.xml`, then
  `uv run python scripts/check-diff-coverage.py <job>/release-coverage.xml --base 80242f28521bba184f4d5d62cda972c1c8928f36`
  — PASS, both changed measured production files meet 90% lines / 80% arcs
  (`check-release-coverage.log`). The full combined hosted publish-set coverage
  floor is **UNVERIFIED**; this focused producer proves the diff portion only.
- `uv run ruff check .`, `uv run ruff format --check .` — PASS, 3682 files.
  `uv run python scripts/check-suite-inventory.py` — PASS, 21 suites,
  37257 unique identities / 0 duplicates. No tests added; inventory delta zero.
  Existing +20 coverage-repair inventory note remains accurate.
  `uv run python scripts/check-release-consistency.py`,
  `uv run python scripts/check-workflow-inventory.py`, and
  `uv run python scripts/check-workflow-write-safety.py` — PASS, 33 workflows
  (`check-static.log`).
- `uv run pytest tests/test_check_required_checks.py tests/test_mutation_targets.py tests/test_check_diff_coverage.py -x -q`
  — 141 passed; `git diff --check` — PASS (`check-adjacent.log`).
- `uv run python scripts/check-doc-links.py` — PASS, 3607 Markdown files,
  0 broken relative links; report diff reviewed and `git diff --check` clean
  (`check-report.log`).
- Byte-check mutation: the first process-local probe incorrectly patched a
  module replaced by fixture setup, so its wrapper failed (pytest passed).
  Retained `check-byte-verification-mutation.log`; this was a probe error, not
  a product failure. Corrected probe patches the live `promote_mod` fixture in
  `pytest_runtest_call`, disabling only `verify_dist`. The existing tampered-byte
  regression then fails at `tests/test_promote_release.py:509` (`assert 0 == 1`);
  wrapper requires pytest exit 1 and passes
  (`check-byte-verification-mutation-corrected.log`). No tracked mutation.

### Acceptance and blocking handoff

Read accepted ADR-073126-c4e1, ADR-095, and ADR-097. Reconciliation: the issue
requires an actual release, while the accepted ADR reserves publication to
protected, tag-triggered `release.yml` with human approval. No local publisher,
new authorization path, or execution-model change is an acceptable substitute.

| Criterion | Executed local evidence | Remaining acceptance |
| --- | --- | --- |
| RC artifacts built only from candidate commit | Candidate record CLI test records real git identity and file hashes; workflow RC-only wheel/image branches checked; 703 tests pass | Hosted candidate build UNVERIFIED |
| Clean install, real-model execution, security hot path, backup/restore | Pinned required-check tests and missing/failing-check rejection tests pass against production validator | Actual functional soak UNVERIFIED |
| Exact-RC sustained multi-replica workload with crash/restart, fencing, pressure, duplicate detection (#860) | `multi_replica_soak` is mandatory in `REQUIRED_SOAK_CHECKS`; missing-soak CLI test passes | Actual workload and measured observations UNVERIFIED |
| Invariant-invalidating findings filed/reclassified before promotion | Production validator and CLI reject unrouted findings; tests pass | Real routing and issue contents UNVERIFIED |
| Code/runtime-config change requires new RC and applicable soak | Real temporary-git tests reject tracked content/config/mode changes and older matching RC selection | Deployed/external config equivalence and replacement soak UNVERIFIED |
| Final tree/bytes equivalent to soaked RC | Tree-identity and real-file hash tests pass; disabled byte-check mutant killed; workflow final builds excluded | Actual final/RC artifact pair and registry digest equality UNVERIFIED |
| External package/image/signature/install verification succeeds | Adjacent release tests pass; clean-install/sign/verify workflow steps inspected | Actual independent external consumer verification UNVERIFIED |
| Machine-readable soak tied to exact artifact/config | Stale wheel/image binding and missing-config tests pass; workflow evidence staging inspected | Compatible real evidence production/transport and deployed config binding UNVERIFIED |

**BLOCKED, not integration approval.** The concrete unresolved integration
contract remains `scripts/promote_release.py:44-57`: promotion requires schema-1
`soak-evidence` on the selected successful RC run, not #860's native boolean
record. `cmd_adopt_digests` downloads that artifact (`:578-583`); the inspected
release workflow uploads its own soak artifact on finals only (`:952-960`).
No compatible post-RC producer/transport or real soak is proven by injected
GitHub unit-test seams. Do not weaken the contract or fabricate a pass record.

Next owner: release/soak maintainers must supply compatible evidence for the
exact RC, run the functional and sustained workloads, route findings, promote
through the protected pipeline, and independently verify external artifacts.
Trusted publishing, environment approval and registry permissions remain
UNVERIFIED. Repeating these local checks cannot supply those observations.
Only this existing report changed; source, tests, ledgers and grants untouched.
Progress: checked 1 issue, done 1 validation/handoff, skipped 0, errors 1
(corrected local probe), next: release/soak owner action. No push or closure.

## Previous round: supplied head `87ce1ab3dee2`, base `80242f28521b`

Job `7be5ec4cd6624a7d9fd21ef99b368df0`; assigned worktree and branch
`auto-89`. Initial status and diff were clean. The prior coverage repair at
`87ce1ab3dee2` and all preceding work were preserved. Frozen scope: issue #89,
supplied PR #2536 evidence, named registry/vulture gates, focused release
coverage and adjacent tests. No remote refresh, publishing, or GitHub mutation.
The supplied job directory initially contained no `check-*.log` files; logs
named below were produced by this worker, not supplied by the driver.

The dispatch's front-matter check is **queued**, not a failed validation.
Captured PR #2536 evidence instead records failed coverage check
`140175737147` at older head `5f6bff7d458f`. The prior attempt repaired that
failure with 20 tests; the previous BLOCKED verdict concerned missing actual
release/soak evidence. This round independently reran validation before deciding
whether any production or ledger repair was warranted.

### Executed commands and outcomes

Logs are under the job directory above. All ordinary validation commands below
exited 0; the process-local mutation deliberately made pytest exit 1.

- `uv sync --locked --extra dev` — PASS (`check-sync.log`).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS, 1219 reviewed identities = 1219 findings, unclassified 0,
  never_allowlist 0 (`check-vulture.log`). No evidence supports a ledger edit.
- All validation steps from `.github/workflows/registry.yml` — PASS
  (`check-registry.log`):
  - `uv run pytest tests/tools/registry/ tests/tools/test_lint_lifecycle.py packages/maistro-registry/tests --confcutdir=tests/tools -p no:cacheprovider -q`
    — 194 passed.
  - `uv run python tools/lint_lifecycle.py` — baseline 0, no violations.
  - `uv run python -m maistro_registry.cli lint . --strict` — 447 files,
    0 errors/warnings, 199 existing test-evidence debts.
  - `RATCHET_BASE_REV=80242f28521bba184f4d5d62cda972c1c8928f36 uv run python scripts/check-citation-status-provenance.py`
    — 0 citation exceptions.
  - `uv run python scripts/check-adr-index.py` — index agrees.
  - `uv run python scripts/generate-spec-ac-defined-index.py` followed by
    `git diff --exit-code docs/specs/README.md` — 57 specs, no diff.
  - `uv run python scripts/check-adr-status-language.py` — 0 contradictions.
- With `COVERAGE_FILE=<job>/release.coverage`,
  `uv run coverage run --branch --source=scripts -m pytest tests/test_promote_release.py tests/test_release_guard.py tests/test_check_release_consistency.py tests/test_release_publish_metadata.py tests/test_soak_compose_pressure.py tests/release/ tests/test_verify_wheel_imports.py tests/test_check_license_inventory.py tests/test_check_compliance.py -x -q`
  — **703 passed**; `uv run coverage xml -o <job>/release-coverage.xml`, then
  `uv run python scripts/check-diff-coverage.py <job>/release-coverage.xml --base 80242f28521bba184f4d5d62cda972c1c8928f36`
  — PASS: both measured changed production files meet 90% lines / 80% branch
  arcs (`check-release-coverage.log`). This reproduces the relevant diff-gate
  mechanics from `quality.yml`; it does **not** rerun all service-backed
  producers or prove the combined publish-set floor/entire hosted check.
- `uv run ruff check .` and `uv run ruff format --check .` — PASS,
  3682 files formatted (`check-ruff.log`).
- `uv run python scripts/check-suite-inventory.py` — PASS, all 21 suites,
  37257 unique identities, 0 duplicates. No tests were added this round;
  inventory delta is zero and the existing +20 note remains accurate.
- `uv run python scripts/check-release-consistency.py`,
  `uv run python scripts/check-workflow-inventory.py`, and
  `uv run python scripts/check-workflow-write-safety.py` — PASS (33 workflows).
- `uv run pytest tests/test_check_required_checks.py tests/test_mutation_targets.py tests/test_check_diff_coverage.py -x -q`
  — 141 passed; `git diff --check` — PASS. These and the preceding inventory
  commands are recorded in `check-adjacent-gates.log`.
- `uv run python scripts/check-doc-links.py` and final `git diff --check` —
  PASS, 3606 Markdown files / 0 broken relative links (`check-final-docs.log`).
- Mutation proof: an inline `uv run python` pytest plugin replaced only the
  loaded module's `verify_dist` with `lambda *args: []` before calling
  `test_adopt_wheels_fails_closed_on_tampered_bytes`. The test failed at
  `tests/test_promote_release.py:509` (`assert 0 == 1`), proving it reaches
  byte verification, not just the earlier tree guard. The wrapper required
  pytest exit 1 and exited 0 (`check-byte-verification-mutation.log`). No
  tracked code was changed for the probe.

### Acceptance rechecked against the production path

Read accepted ADR-073126-c4e1, ADR-095, and ADR-097. Reconciliation: the issue
asks for a release, but ADR authority reserves publishing to tag-triggered
`release.yml` with protected promotion and human approval. This lane cannot
substitute local publication or create tags. No scheduler, Goal store, event
source, or authorization path changed.

| Criterion | Fresh local evidence | Operational acceptance |
| --- | --- | --- |
| RC built only from candidate commit | `release.yml:284` builds wheels only for RCs; both image builds are RC-only; `cmd_record_evidence` records checked-out commit/tree and real file hashes; record and workflow tests pass in the 703-test battery | Actual hosted candidate build UNVERIFIED |
| Clean install, real-model, security hot path, backup/restore during soak | `promote_release.py:286` requires passing status and citations for every required check; pinned-check and rejection tests pass | Actual four-part functional soak UNVERIFIED |
| #860 sustained exact-RC multi-replica crash/restart, fencing, pressure, duplicate-work workload | `multi_replica_soak` is pinned as required; binding and missing-soak tests pass | Actual workload and measured runtime observations UNVERIFIED |
| Invariant-invalidating findings routed before promotion | `promote_release.py:306` requires a syntactically valid routed issue; CLI rejection tests pass | Real issue filing/reclassification and contents UNVERIFIED |
| Changes require new RC and applicable soak | `release_guard.py:190` compares the latest numeric RC tree, including tracked configuration and modes; real temporary-git rejection tests pass | Tracked-tree enforcement proven locally; deployed/external configuration equivalence and actual replacement soak UNVERIFIED |
| Final byte-equivalent to soaked RC | `promote_release.py:351` verifies file hashes; workflow finals adopt wheels/digests without rebuilding runtime artifacts; byte-check mutant killed | Actual RC/final artifact pair and registry manifest identity UNVERIFIED |
| External package/image/signature/install verification succeeds | Workflow has clean-venv imports, scans, signing and verification; adjacent tests pass | Actual independent external consumer verification UNVERIFIED |
| Machine-readable evidence tied to exact artifact/config | `promote_release.py:259` binds wheel/image maps and requires a config digest; `release.yml:1021` stages evidence under SHA256SUMS; PyPI waits for images/soak; binding tests pass | Compatible real evidence production/transport and deployed-config binding UNVERIFIED |

### Disposition and next owner

**BLOCKED on operational acceptance, not on a reproduced local gate defect.**
This round updates only this existing report. No source, tests, quality ledger,
grant, or gate changed; fabricating a ledger repair when the scan is green would
not address evidence. The full combined hosted Coverage gate remains UNVERIFIED;
the formerly red diff-coverage portion is proven green at the supplied base.

The unresolved production seam is explicit at `scripts/promote_release.py:44-57`:
`adopt-digests` requires a compatible `soak-evidence` Actions artifact on the
selected successful RC run; #860's native boolean record is not that schema.
The release workflow's own soak upload is finals-only (`release.yml:952`), not
a demonstrated post-RC producer/transport. Fake GitHub seams in CLI tests cannot
prove this integration or a real soak. Do not weaken the evidence contract.
Release/soak owners must provide compatible evidence for a real RC, execute all
functional and sustained workloads, route findings, promote via the protected
pipeline, and independently verify externally published artifacts. Environment
reviewer, trusted publishing, and registry permissions also remain unverified.

Progress: checked 1 issue, completed 1 focused validation/handoff, skipped 0
assigned issues, unexpected validation errors 0; next: release/soak owner action.
No push, integration approval, or issue closure.

## Previous round (retained history)

### Frozen scope

- Assigned issue: #89, branch `auto-89`, starting HEAD `b9ec333c16848c504030d2e0c0c64b696cca60f3`.
- Supplied comparison base: `8d8f10616fb7ae984a02bf84553489470d03c726`.
- Scope: existing release promotion implementation (`.github/workflows/release.yml`, `scripts/promote_release.py`, `scripts/release_guard.py`), adjacent release/license tests and inventory notes; named registry and vulture gates.
- Job: `/home/dev/maistro/jobs/d64f92ac827f469cb2e80d1344cb66a1`.
- Initial inspection: clean worktree, prior implementation and validation commits retained. No `check-*.log` files supplied in this job directory. Prior result reports BLOCKED on operational release evidence, not a reproduced code failure; this report will independently validate that distinction.
- Strategy following exhausted prior attempts: do not restart implementation or infer scanner failures from queued status. Execute named gates, inspect reachable production behavior and meaningful tests, then commit the smallest evidence-backed change/report.

## Results

- Named vulture gate executed: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS, 1219 reviewed identities / 1219 findings, unclassified 0, never_allowlist 0. No evidence warrants a ledger edit.
- Registry workflow inspected: queued is a scheduling state, not evidence of a front-matter failure. All seven validation steps freshly PASS: registry/lifecycle tests 194 passed; lifecycle lint clean; strict registry lint 447 files, 0 errors/warnings (199 existing test-evidence debts); citation provenance with `RATCHET_BASE_REV=8d8f10616fb7ae984a02bf84553489470d03c726` reports 0 exceptions; ADR index consistent; spec index generation yields no diff (57 specs); body-status gate 0 contradictions. Commands follow `.github/workflows/registry.yml`, using `uv run` and `-q` for pytest output.
- Dispatch acceptance snapshot read: actual candidate build, four functional soak checks, #860 sustained multi-replica soak, invariant routing, fresh RC after runtime-affecting changes, byte-equivalent final, external verification, exact artifact/config evidence. Prior attempt history includes an invalid result-JSON failure and operational BLOCKED reports; no reason to restart the implementation.

- Focused release battery PASS: `uv run pytest tests/test_promote_release.py tests/test_release_guard.py tests/test_check_release_consistency.py tests/test_release_publish_metadata.py tests/test_soak_compose_pressure.py tests/release/ tests/test_verify_wheel_imports.py tests/test_check_license_inventory.py tests/test_check_compliance.py -x -q` — 683 passed in 46.02s.
- `uv run ruff check .` PASS; `uv run ruff format --check .` PASS (3682 files).
- Inspected production CLI and workflow plus `tests/test_promote_release.py`: finals adopt RC wheel bytes and image digests, tree guard rejects changed tracked config, soak validation precedes final image promotion, PyPI waits for images, and missing soak artifacts fail closed. Unit/CLI tests fake GitHub seams; they do not execute a hosted soak or prove that a compatible post-RC artifact is actually uploaded.
- Read accepted release ADR-073126-c4e1: tag-triggered `release.yml` is the only publisher; human `release` approval remains required; finals must ship the last RC artifacts. No local manual publication is an acceptable workaround.

- Mutation check PASS (mutant killed): a process-local pytest plugin replaced production `verify_dist` with `lambda *args: []`; `test_adopt_wheels_fails_closed_on_tampered_bytes` then failed at `tests/test_promote_release.py:508` (`assert 0 == 1`). The wrapper required pytest exit 1 and exited 0. No tracked source/test edits were used for this probe.
- Additional gates PASS: `uv run python scripts/check-release-consistency.py` (released none, shipping 0.9.0, working toward 1.0.0); `check-workflow-inventory.py` (33 workflows); `check-workflow-write-safety.py` (33 workflows); `check-suite-inventory.py` (21 suites, 37237 unique identities, no duplicates); `check-doc-links.py` (3604 markdown files, 0 broken relative links). Each script was invoked with `uv run python scripts/<name>`.
- ADR-095 confirms `develop -> main` promotion with protected human-reviewed main; no alternative publishing or execution authority introduced. No production changes warranted by the named gates. No tests added, so inventory delta is zero and no baseline/ledger edits are needed.

- Gate-policy regression tests PASS: `uv run pytest tests/test_check_required_checks.py tests/test_mutation_targets.py -x -q` — 123 passed in 3.07s. `git diff --check` PASS.
- Captured dispatch review evidence inspected (no network refresh): #2536's RC distribution retention finding is already repaired in the preserved workflow (`dist` retention is 90 days, equal to evidence). #1672 findings concern the separate #860 harness; no edits to that other lane. Captured #860 remains open and explicitly requires a long-running exact-RC workload with measured thresholds and failure/recovery observations.

## Acceptance against reachable production behavior

| Issue criterion | Executed local evidence | Actual release acceptance |
| --- | --- | --- |
| RC artifacts built only from candidate commit | `release.yml:284`, `:577`, `:642` build only on RC; record CLI (`promote_release.py:483`) records real git commit/tree and hashes; record and workflow tests pass in the 683-test battery | Actual hosted candidate build UNVERIFIED |
| Soak includes clean install, real-model, security hot path, backup/restore | `promote_release.py:286` requires each named check with passing status and evidence; pinned-check and per-check mutation tests pass | Actual functional soak window UNVERIFIED; fake evidence is not a soak |
| #860 exact-RC sustained multi-replica workload, crash/restart, fencing, pool pressure, duplicate detection | `multi_replica_soak` is pinned by `test_required_soak_checks_are_pinned_not_adaptive`; digest-binding and missing-artifact rejection tests pass | Sustained runtime observations UNVERIFIED; supplied #860 snapshot is open |
| Invariant-invalidating findings routed before promotion | `promote_release.py:306` rejects unrouted invariant findings; validator and adopt-digests CLI tests pass | Actual filing/reclassification UNVERIFIED; format validation does not verify issue contents |
| Code/runtime-config change requires new RC and applicable soak | Real temporary-git tree tests reject content/mode/config changes after latest RC; `release.yml:105` invokes guard. Config reference/digest fields are required (`promote_release.py:259`) | Tracked-tree enforcement proven locally; deployed/external config equivalence and fresh soak after changes UNVERIFIED |
| Final tag/tree byte-equivalent to soaked RC | Guard tests cover same tree/different merge commit and reject newer mismatching RC; adopt-wheels verifies real file hashes (`promote_release.py:351`); production byte-check mutant killed | Actual RC/final artifact pair and registry manifest equality UNVERIFIED |
| External package/image/signature/install verification succeeds | Workflow includes twine, clean venv/minimum floors (`release.yml:377`, `:391`), scans, digest signing/verification (`:817`, `:831`); adjacent tests pass | Actual consumer installs and PyPI/GHcr/signature verification UNVERIFIED |
| Machine-readable evidence tied to exact promoted artifact/config | CLI binding tests reject stale wheel/image hashes and malformed config identity; final staging includes record/soak under SHA256SUMS (`release.yml:1021`); PyPI waits for successful images/soak (`:433`) | Compatible evidence production/transport and actual config binding UNVERIFIED |

## Handoff / residual blockers

Verdict: **BLOCKED**, not integration approval. The named CI gates have no reproduced failure to repair. This change is only this evidence report; all prior implementation/tests are preserved. Test inventory delta: zero. No quality ledgers, grants, release tags, or product source changed.

`scripts/promote_release.py:45-57` explicitly delegates soak production to another lane and requires an Actions artifact named `soak-evidence` on the selected RC run. Its documented #860 native record does not satisfy the promotion schema. This round did not prove a supported upload path, produce a real soak record, or execute a tagged release. The passing tests inject GitHub access and cannot establish that cross-lane integration. Do not weaken the gate to admit incompatible evidence or substitute local green checks for sustained observations.

Next owner action: release/soak maintainers must provide a compatible evidence producer/transport bound to an actual successful RC run, complete the exact-RC sustained and functional soak, route real findings, and use the ADR-governed protected promotion workflow with independent external verification. Any changed code/runtime configuration requires a new RC and applicable soak. Maintainer-side environment approval, trusted publishing and registry permissions are not verified by this report.

Progress: checked 1 assigned issue, completed 1 local validation report, skipped 0 assigned issues, unexpected command failures 0 (one intentional mutation-test failure). All eight operational acceptance criteria remain UNVERIFIED. No GitHub mutation, issue closure, push, or release operation performed.
