# Issue #89 current repair validation

## Frozen scope

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
