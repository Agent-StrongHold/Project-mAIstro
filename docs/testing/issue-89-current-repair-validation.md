# Issue #89 current repair validation

## Current round: assigned head `61e3ba7721`, base `618954f052`

Job `3216c683221c4263b8c68fa02acb5e66`; frozen scope: issue #89, the named
front-matter/coverage/vulture gates, and the standing operational soak
contract. Worktree entered clean at the exact starting head; no driver
`check-*.log` files were supplied in this job's directory (second round in a
row), so every log cited here is a fresh worker execution under
`/home/dev/maistro/jobs/3216c683221c4263b8c68fa02acb5e66/`.

### New diagnostic fact this round: the remote Coverage-gate RED is fully explained and already repaired locally

Captured check-run evidence for PR #2536's pushed head `5f6bff7d458f` shows
`Coverage gate (publish-set floor + diff coverage)` = **failure** (front-matter
= success, all other checks success). Diagnosis, from git evidence at this
head:

- The gate's diff half at that head compared base `3be6b665` (the PR's
captured develop base) to `5f6bff7d45`. That delta touches exactly two
measured production files — `scripts/promote_release.py` and
`scripts/release_guard.py` — plus three test files that
`scripts/check-diff-coverage.py` exempts by declaration.
- At `5f6bff7d45`, `scripts/promote_release.py` measured 86.5% of 327 changed
lines — under the 90% per-file floor; every uncovered line was a fail-closed
seam body (`87ce1ab3de`'s commit message reproduces the measurement).
- The repair, commit `87ce1ab3de` (20 seam-covering tests in
`tests/test_promote_release.py`), is a **descendant** of `5f6bff7d45`:
`git merge-base --is-ancestor 5f6bff7d45 61e3ba7721` holds, i.e. the pushed
branch tip `origin/auto-89` == `5f6bff7d45` is stale and predates its own
fix. Nothing further is broken in the tree; advancing the branch to this
head is what turns the remote check green. This worker is prohibited from
pushing, so that advance is the driver's/integrator's action.
- The dispatched `queued` state for "Validate ADR/spec front-matter" does not
correspond to any captured failure: the captured check-run for that name at
`5f6bff7d458f` is `success`, and all 7 steps re-pass fresh below.

### Fresh execution at `61e3ba7721` (all exit 0 unless stated)

- Exact vulture gate (CI args
`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`):
**1217 reviewed identities / 1217 findings**, unclassified 0,
never_allowlist 0 (`check-vulture-local.log`). Ledger byte-identical to
`origin/develop` — `git diff --numstat origin/develop -- quality/
docs/testing/inventory/` prints nothing (`check-adjacent-local.log`). No
amendment made; none warranted.
- Front-matter gate, all 7 `registry.yml` steps
(`check-registry-local.log`): registry/lifecycle tests **194 passed**;
lifecycle lint baseline 0; strict registry lint **447 files, 0 errors / 0
warnings** (199 pre-existing test-evidence debts); citation provenance with
`RATCHET_BASE_REV=origin/develop` 0 exceptions; ADR-INDEX consistent;
AC-Defined index regenerated, `git diff --exit-code docs/specs/README.md`
clean; body-status language 0 contradictions.
- Coverage gate, diff half: release battery
**703 passed**; `coverage xml` →
`check-diff-coverage.py --base 618954f0528090144683c308a18e19c6068d63f1`
— **ok**, 2 changed measured production files at/above 90% lines / 80%
branch arcs, 3 test files exempt by declaration
(`check-release-coverage-local.log`). As every prior round recorded, the
focused producer proves the diff half only; the combined hosted publish-set
floor (87%) needs CI's six producers and stays UNVERIFIED locally.
- Byte-verification mutation probe re-run with this round's own scripts
(`probe_byte_verification.py` + `byte_probe_mutant.py` in the job dir):
control exit 0; with `verify_dist` stubbed on the fixture-loaded module only,
pytest exit 1 with `MUTANT ACTIVE` and the regression's own `assert 0 == 1`
signature — mutant killed (`check-byte-mutation-local.log`).
`git status` clean after the probe; no tracked mutation.
- Policy/adjacent: `tests/test_check_required_checks.py
  tests/test_mutation_targets.py tests/test_check_diff_coverage.py` —
**141 passed**; `check-doc-links.py` 0 broken; `check-suite-inventory.py`
21/21 suites, 37818 unique identities, 0 duplicates; release consistency,
workflow inventory (33), write-safety, `ruff check .` and
`ruff format --check .` (3717 files) all pass
(`check-adjacent-local.log`, `check-inventory-local.log`,
`check-static-local.log`). No tests added or removed this round — inventory
delta 0, no note required.

### Acceptance and disposition (unchanged in substance)

Re-read the production seams at this head rather than trusting earlier notes:
`scripts/promote_release.py:44-57` (cross-lane contract: the soak harness
must upload an Actions artifact named exactly `soak-evidence` on the RC run;
the #860 native boolean record does not satisfy it; adapting would weaken
the gate), `:144` `SOAK_ARTIFACT`, `:150` `REQUIRED_SOAK_CHECKS`, `:259`
`_validate_binding`, `:316-322` `invalidates_invariant` → `routed_issue`,
`:333` `validate_soak`, `:351` `verify_dist`; and
`.github/workflows/release.yml:946-953` — the workflow's own soak-evidence
upload is finals-only because RC runs have none yet ("the soak happens during
the candidate window"). Local green tests inject the download seam; they do
not create the producer/transport, run a real soak, or publish anything.

All eight operational acceptance criteria therefore stay exactly as the
standing table below records: hosted RC build, functional soak, #860
sustained multi-replica workload, real finding routing, replacement-soak on
deployed change, actual RC/final byte pair, external verification, and real
evidence binding remain UNVERIFIED and reserved to the release/soak owners
(#860 lane / PR #1672) and the protected, tag-triggered pipeline with human
approval (ADR-073126-c4e1, ADR-095). No source, test, workflow, gate, grant,
or ledger defect was demonstrated this round; the only tree change is this
note.

Verdict unchanged: **BLOCKED on operational acceptance**, not on any
reproduced local gate defect. The one reproduced remote gate failure
(Coverage gate at `5f6bff7d458f`) is already repaired in this branch's local
history by `87ce1ab3de` and re-proven green at this head; the remote advance
itself is outside this worker's authority.

Progress: checked 1 issue, done 1 focused validation/handoff round, skipped 0,
unexpected errors 0. No push, tag, merge, or GitHub mutation. Writer handoff
only; not integration approval or issue completion.

## Previous round: assigned head `4e6a254315`, base `618954f052`

Job `576c481701ce4b9e8910745cce4b6b5a`; frozen scope: issue #89,
existing release implementation/tests, named registry/vulture/coverage gates.
Initial `git log --oneline -20`, `git diff --stat`, and status showed a clean
worktree with the earlier implementation and repairs preserved. No driver
`check-*.log` files were supplied. Logs below are fresh worker executions under
`/home/dev/maistro/jobs/576c481701ce4b9e8910745cce4b6b5a/`.

### Executed evidence (not earlier verification claims)

- Exact requested command `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exit 0:
  **1217 reviewed identities / 1217 findings**, unclassified 0, never_allowlist
  0 (`check-vulture-local.log`). No ledger amendment is justified.
- Every validation step in `.github/workflows/registry.yml` — exit 0
  (`check-registry-local.log`): registry/lifecycle tests **194 passed**;
  lifecycle lint baseline 0; strict registry lint; citation provenance with
  `RATCHET_BASE_REV=618954f0528090144683c308a18e19c6068d63f1`; ADR index;
  spec-index generation plus `git diff --exit-code docs/specs/README.md`;
  body-status language. The dispatched **queued** status is not a reproduced
  front-matter failure.
- `uv run coverage run --branch --source=scripts -m pytest
  tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_release_consistency.py tests/test_release_publish_metadata.py
  tests/test_soak_compose_pressure.py tests/release/
  tests/test_verify_wheel_imports.py tests/test_check_license_inventory.py
  tests/test_check_compliance.py -x -q` — **703 passed**. With `COVERAGE_FILE`
  set to the job's `release.coverage`, `uv run coverage xml -o
  <job>/release-coverage.xml`, then `uv run python scripts/check-diff-coverage.py
  <job>/release-coverage.xml --base 618954f0528090144683c308a18e19c6068d63f1`
  — exit 0, both changed production files meet 90% lines / 80% branch arcs
  (`check-release-coverage-local.log`). This proves the historically red diff
  half, **not** the entire combined hosted publish-set floor; that remains
  UNVERIFIED.
- Byte-verification bypass mutant killed at `tests/test_promote_release.py:509`
  (`assert 0 == 1`; `check-byte-mutation-fixture-local.log`). A process-local
  pytest plugin replaced the actual `promote_mod` fixture's `verify_dist`
  immediately before the test call. Its wrapper required pytest exit 1 and
  exited 0. An initial probe patched the separate module-level helper instead
  and left the test passing; that invalid injection is retained in
  `check-byte-mutation-local.log`, not counted as mutation evidence. No tracked
  source was mutated.
- `uv run ruff check .`, `uv run ruff format --check .`, and `uv run python
  scripts/check-suite-inventory.py` — exit 0 (3717 formatted files; 21 suites,
  37818 unique test identities). `check-release-consistency.py`,
  `check-workflow-inventory.py`, `check-workflow-write-safety.py`, each invoked
  with `uv run python scripts/<name>`, and `git diff --check` — exit 0
  (`check-static-local.log`). No tests added/removed; inventory delta **zero**;
  the preserved +20 repair note remains applicable.
- `uv run python scripts/check-doc-links.py` — exit 0, 3638 Markdown files,
  no broken relative links; final `git diff --check` passes. Ledger/inventory
  baseline diff against the assigned base is empty (`check-final-local.log`).
- Inspection error, not a gate failure: guessed workflow path
  `.github/workflows/m3a-soak.yml` was not found; skipped without further
  investigation. No runtime evidence is inferred from that lookup.

### Acceptance disposition after reading production and adjacent tests

Read accepted ADR-073126-c4e1 and ADR-095. Publishing remains exclusively the
protected, tag-triggered `release.yml`; local publication is not a workaround.
No execution, event, Goal-store, or authorization authority changed.

| Criterion | Reachable mechanism / executed tests | Actual operational acceptance |
| --- | --- | --- |
| RC artifacts only from candidate commit | RC-only wheel/image builds in `release.yml:284,577,642`; record CLI captures real git identity/hashes; 703-test battery | Hosted candidate build UNVERIFIED |
| Clean install, real-model, security hot path, backup/restore soak | `promote_release.py:150-156,286-303` requires each named passing check and citations; pinned-check and rejection tests pass | Actual functional soak UNVERIFIED |
| #860 sustained exact-RC multi-replica crash/restart, fencing, pressure, duplicate detection | Required `multi_replica_soak` and artifact-binding tests pass | Sustained workload/runtime observations UNVERIFIED |
| Invariant-invalidating findings routed before promotion | `promote_release.py:306-328` rejects absent/malformed routed issue; CLI tests pass | Actual filing/reclassification and issue contents UNVERIFIED |
| Changed code/runtime config requires new RC and applicable soak | `release_guard.py:190-247` compares latest numeric RC tree; real temporary-git tests reject tracked changes | Tracked-tree enforcement proven; deployed/external configuration equivalence and replacement soak UNVERIFIED |
| Final tree/artifacts byte-equivalent to soaked RC | `verify_dist` hashes exact downloaded bytes; finals adopt rather than rebuild; byte-check mutant killed | Actual RC/final artifact pair and registry manifest identity UNVERIFIED |
| External package/image/signature/install verification succeeds | Workflow includes clean-venv installs, scans, digest signing/verification; adjacent tests pass | External consumer verification UNVERIFIED |
| Machine-readable soak tied to exact promoted artifact/config | `promote_release.py:259-283` compares wheel/image maps and requires config identity; binding tests pass | Compatible real producer/transport and deployed-config binding UNVERIFIED |

**BLOCKED, not merge-ready.** Named local gate failures do not reproduce, so this
round changes only this existing report, not source, tests, gates, grants, or
ledgers. `cmd_adopt_digests` (`promote_release.py:560-583`) requires a compatible
`soak-evidence` artifact on the selected RC run. The workflow's own upload
(`release.yml:949-955`) is finals-only, and CLI tests inject the download seam
(`tests/test_promote_release.py:431-460`); neither proves a real post-RC evidence
producer/transport. The documented cross-lane contract (`promote_release.py:49-57`)
remains unproven, not satisfied by local green tests. Do not weaken it.

Next: release/soak owners must supply compatible exact-RC evidence, execute all
functional/sustained soak checks, route real findings, use protected promotion,
and independently verify external artifacts. Environment reviewer, trusted
publishing, and registry permissions remain UNVERIFIED. No push, tag, GitHub
mutation, or issue closure performed. Checked 1 issue, done 1 validation/handoff,
skipped 0 assigned issues; one invalid mutation probe corrected, one missing
inspection path skipped. Local commit is handoff only, never integration approval.

## Previous round: assigned head `59275d0e9c`, base `618954f052` — develop sync merged, all named gates re-proven at merged head `c65f146b02`

Job `77215e722d4d48ef8f0c0ffd03546f84`, branch/worktree `auto-89`, exact
starting head `59275d0e9c06d387f70a89a1f0db8b35db4e9183`. Frozen scope:
issue #89 only. The immediately preceding job (`ccf6c87c…`) crashed at
startup (`agent_exit 1`, 0 checks, no artifact), and its predecessor ended
BLOCKED on the operational soak/promotion contract with the
"Validate ADR/spec front-matter" check still `queued` — a scheduling state,
not a reproduced failure. The supplied job directory contained **no**
`check-*.log` files, so every log cited below was generated by this worker.
`git status` was clean on entry; no salvage existed to preserve.

### Develop sync

`origin/develop` had moved to the assigned base `618954f052` — 3 commits
(`05df0ac31b` M2-A4 Sentinel decision integrity, `41c8b670a1` M2 enterprise
keyboard reachability, `618954f052` M2-A1 Warden/Sentinel coverage) past the
branch merge base `73610a225d`. Pre-merge overlap check between the develop
delta and this branch's diff: **0 shared files**, so the merge
(`c65f146b02`) resolved with zero conflicts. Ledger audit per
docs/quality-gates.md: `git diff --numstat origin/develop -- quality/
docs/testing/inventory/` prints nothing — quality ledgers and the
suite-inventory baseline are byte-identical to develop (develop itself
amended `quality/vulture-baseline.json` by one row; the merge inherited
exactly that, no candidate ledger edits).

### Fresh execution at merged head `c65f146b02`

All logs are under `/home/dev/maistro/jobs/77215e722d4d48ef8f0c0ffd03546f84`;
every command exited 0 except the deliberately killed mutant and one
retracted diff-coverage attempt whose failure was an operator error (XML
generated outside the repo root, so the two measured production files were
absent from the report); re-run correctly and green below.

- Front-matter gate ("Validate ADR/spec front-matter",
  `.github/workflows/registry.yml`), all 7 steps at this head — PASS:
  194 registry unit tests (`check-registry-tests.log`);
  `tools/lint_lifecycle.py` baseline 0 (`check-lifecycle.log`);
  `maistro-registry.cli lint . --strict` 447 files / 0 errors / 0 warnings
  (`check-registry-lint.log`); citation ratchet with
  `RATCHET_BASE_REV=origin/develop` 0 exceptions, no expansion
  (`check-citation.log`); ADR-INDEX consistent (`check-adr-index.log`);
  AC-Defined index regenerated with zero diff (`check-spec-index.log`,
  `check-spec-index-diff.log`); body-status language 0 contradictions
  (`check-adr-language.log`). The `queued` state does not reproduce as a
  validation failure.
- Coverage gate, diff half at this head: release battery
  `coverage run --branch --source=scripts` over the promote/guard/
  soak/publish suites — **703 passed** (`check-release-tests.log`);
  `coverage xml`, then `check-diff-coverage.py --base origin/develop`
  — PASS, 2 changed measured production files (`scripts/promote_release.py`,
  `scripts/release_guard.py`) at/above 90% lines / 80% branch arcs, 3 test
  files exempt by declaration (`check-diff-coverage.log`). The full combined
  hosted publish-set floor (87%) remains UNVERIFIED locally — it requires the
  six producers CI assembles (`quality.yml` coverage-gate job); this branch
  touches no file outside `scripts/`, root `tests/` and docs.
- Byte-verification mutation probe re-run at this head — control passes,
  mutant killed:
  `tests/test_promote_release.py::test_adopt_wheels_fails_closed_on_tampered_bytes`
  exits 0 unmutated (`check-byte-control.log`) and exits 1 with
  `MUTANT ACTIVE` / `assert 0 == 1` under a process-local plugin stubbing
  `verify_dist` (`check-byte-mutant.log`, `probe_byte_verification.py`).
  No tracked source was mutated; `git status` clean after the probe.
- Exact vulture gate (CI args
  `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) —
  1217 reviewed identities -> 1217 findings, 0 unclassified
  (`check-vulture.log`; count tracks develop's one-row ledger amendment).
  Candidate baseline edits cannot authorize anything and none were made.
- `ruff check .` / `ruff format --check .` — PASS, 3717 files formatted
  (`check-ruff.log`, `check-ruff-format.log`).
- `check-suite-inventory.py` — 21 suites match the recorded inventory,
  no tests added (`check-inventory.log`);
  `check-release-consistency.py`, `check-workflow-inventory.py`,
  `check-workflow-write-safety.py`, `check-doc-links.py` — PASS
  (`check-release-consistency.log`, `check-workflow-inventory.log`,
  `check-workflow-write-safety.log`, `check-doc-links.log`).
- `uv run pytest tests/test_check_required_checks.py tests/test_mutation_targets.py tests/test_check_diff_coverage.py -q`
  — **141 passed** (`check-policy-tests.log`).
- Acceptance seams re-read in production source at this head (not trusted
  from prior notes): `scripts/promote_release.py:150-156` `REQUIRED_SOAK_CHECKS`
  = clean_install / real_model / security_hot_path / backup_restore /
  multi_replica_soak; `:340-377` `validate_soak` gates `adopt-digests`
  fail-closed on schema-1 soak evidence (`:560-583`); `_validate_binding`
  ties the record to exact wheel sha256 map + image digests + config digest;
  `:316-326` findings with `invalidates_invariant` must carry `routed_issue`;
  `:415-457` `select_rc_run` takes only the LATEST successful candidate run
  (an older success is never evidence for a newer tree — new-RC-on-change);
  `:351-372` `verify_dist` rejects missing, hash-mismatched and extra files
  (byte-equivalence, not "rebuilt from same tree"); `.github/workflows/release.yml`
  candidate tags build, finals adopt the candidate's bytes via
  `buildx imagetools create` (no final image rebuild).

### Disposition

No source, test, workflow, or ledger defect was demonstrated at this head;
the tree change is this note plus the develop-sync merge. The carried BLOCKED
remains the documented cross-lane operational contract, unchanged by any
local round: `scripts/promote_release.py` requires a real schema-1
`soak-evidence` artifact produced by a sustained multi-replica soak on the
exact RC (producer lives with the #860 lane / PR #1672), publication is
reserved to the tag-triggered `release.yml` pipeline with protected approval,
and the final tag + external verification are protected operations no repair
worker may perform. All locally reachable acceptance is proven above at this
exact head.

Progress: checked 1 issue, done 1 develop sync + focused validation round,
skipped 0, unexpected errors 0; next: release/soak owner evidence and
protected operation. Writer handoff only; not integration approval or issue
completion.

## Previous round: assigned head `2bc81c02bd`, base `73610a225d98` (already merged)

Job `17ec229326d64a26a76479d8e50b2fda`, branch/worktree `auto-89`, exact
starting head `2bc81c02bdc3c88507357da7658af6ab8cdcab52`. Frozen scope:
issue #89 only. The merge-queue items named for this round were the
`queued` "Validate ADR/spec front-matter" check and the carried
operational BLOCKED; a `queued` state is scheduling, not a reproduced
failure, so this round re-proves the named gates at the current head
before touching anything. `git status` was clean on entry; no salvage
existed to preserve. No tests added/removed (inventory delta zero), no
ledger/grant edits (vulture gate clean; ordinary round), no push, tag,
or other GitHub mutation.

### Fresh execution at `2bc81c02bd`

All logs are under `/home/dev/maistro/jobs/17ec229326d64a26a76479d8e50b2fda`;
every command exited 0 except the deliberately killed mutant.

- Branch position: `origin/develop` (`73610a225d98`) is an ancestor of
  this head — the develop sync landed in `bb9b2d2200`; 0 commits behind
  develop, so no conflict resolution was needed. `uv sync --locked
  --extra dev` — environment already locked and current.
- Front-matter gate ("Validate ADR/spec front-matter",
  `.github/workflows/registry.yml`), all 7 steps at this head — PASS:
  194 registry unit tests (`check-registry-tests.log`);
  `tools/lint_lifecycle.py` baseline 0 (`check-lifecycle.log`);
  `maistro-registry.cli lint . --strict` 447 files / 0 errors / 0
  warnings (`check-registry-lint.log`); citation ratchet with
  `RATCHET_BASE_REV=origin/develop` 0 exceptions, no expansion
  (`check-citation.log`); ADR-INDEX consistent (`check-adr-index.log`);
  AC-Defined index regenerated with zero diff (`check-spec-index.log`,
  `check-spec-index-diff.log`); body-status language 0 contradictions
  (`check-adr-language.log`). The queued state does not reproduce as a
  validation failure.
- Coverage gate, diff half at this head: release battery
  `coverage run --branch --source=scripts` over the promote/guard/
  soak/publish suites — **703 passed** (`check-release-tests.log`);
  `coverage xml`, then `check-diff-coverage.py --base origin/develop`
  — PASS, 2 changed measured production files at/above 90% lines /
  80% branch arcs, 3 test files exempt by declaration
  (`check-diff-coverage.log`). The full combined hosted publish-set
  floor (87%) remains UNVERIFIED locally — it requires the six
  producers CI assembles (`quality.yml` coverage-gate job).
- Byte-verification mutation probe re-run at this head — control
  passes, mutant killed:
  `tests/test_promote_release.py::test_adopt_wheels_fails_closed_on_tampered_bytes`
  exits 0 unmutated (`check-byte-control.log`) and exits 1 with
  `MUTANT ACTIVE` under a process-local plugin stubbing `verify_dist`
  (`check-byte-mutant.log`, `probe_byte_verification.py`). No tracked
  source was mutated.
- Exact vulture gate (CI args) — 1218 reviewed identities -> 1218
  findings, 0 unclassified (`check-vulture.log`); candidate baseline
  edits cannot authorize anything and none were made.
- `ruff check .` / `ruff format --check .` — PASS, 3710 files formatted.
- `check-suite-inventory.py` — 21 suites match the recorded inventory,
  no tests added (`check-inventory.log`);
  `check-release-consistency.py`, `check-workflow-inventory.py`,
  `check-workflow-write-safety.py`, `check-doc-links.py` — PASS.
- Ledger safety: `git diff --numstat origin/develop -- quality/
  docs/testing/inventory/` prints nothing — quality ledgers and the
  suite-inventory baseline are byte-identical to develop (multiset rule
  honored).

### Disposition

No source, test, workflow, or ledger defect was demonstrated at this
head; the only tree change is this note. The carried BLOCKED is not a
gate failure: it is the documented cross-lane operational contract —
`scripts/promote_release.py:49-57` requires schema-1 `soak-evidence`
produced by a real RC soak, and accepted ADRs reserve publication to
the tag-triggered `release.yml` pipeline with protected approval. That
evidence must come from the release/soak owners (#860 lane, PR #1672)
and the protected release environment; it cannot be manufactured
locally by any number of further repair rounds. All locally reachable
acceptance (candidate-only RC enforcement, soak-before-promotion
rejection, new-RC-on-change, byte-equivalence fail-closed with a killed
bypass mutant, artifact/config binding, and every named gate) is proven
above at this exact head.

Progress: checked 1 issue, done 1 focused validation/handoff round, skipped 0,
unexpected errors 0; next: release/soak owner evidence and protected
operation. Writer handoff only; not integration approval or issue completion.

## Previous round: assigned head `c6cfc6de9626`, base `73610a225d98`

Job `c88e90acbe5f44d7b1cecf2fa6f93a82`, branch/worktree `auto-89`.
Frozen scope: issue #89, preserved release implementation and adjacent tests,
queued registry gate, exact vulture gate, and the prior diff-coverage repair.
Initial `git log --oneline -20`, `git diff --stat`, and `git status --short`
confirmed the implementation and previous fixes were committed and the tree
was clean. No salvage was discarded. No supplied `check-*.log` files existed
in this job directory; the logs cited below were generated by this worker.

The previous result was BLOCKED on actual release/soak evidence, not a
reproduced local gate defect. Repeating implementation from scratch would not
supply that evidence. This round independently reran the named gates before
considering any repair. No source defect was demonstrated, so only this
existing report changes; no tests added/removed (inventory delta zero), no
quality ledger/grant changes, and no merge, push, tag, or GitHub mutation.

### Fresh validation

Logs are under `/home/dev/maistro/jobs/c88e90acbe5f44d7b1cecf2fa6f93a82`.
All validation commands below exited 0 except the deliberately killed mutant.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — 1218 reviewed identities / 1218 findings, zero unclassified or
  never-allowlist findings (`check-vulture.log`). No ledger repair warranted.
- All validation steps in `.github/workflows/registry.yml` — PASS:
  `uv run pytest tests/tools/registry/ tests/tools/test_lint_lifecycle.py packages/maistro-registry/tests --confcutdir=tests/tools -p no:cacheprovider -q`
  — **194 passed**; `uv run python tools/lint_lifecycle.py` — baseline 0;
  `uv run python -m maistro_registry.cli lint . --strict` — 447 files,
  zero errors/warnings (199 pre-existing test-evidence debts);
  `RATCHET_BASE_REV=73610a225d98c602fc014dfbcfe3e399bbe79d9b uv run python scripts/check-citation-status-provenance.py`
  — zero exceptions; `uv run python scripts/check-adr-index.py` — consistent;
  `uv run python scripts/generate-spec-ac-defined-index.py` followed by
  `git diff --exit-code -- docs/specs/README.md` — zero diff;
  `uv run python scripts/check-adr-status-language.py` — zero contradictions.
  Logs: `check-registry-tests.log`, `check-lifecycle.log`,
  `check-registry-lint.log`, `check-citation.log`, `check-adr-index.log`,
  `check-spec-index.log`, `check-spec-index-diff.log`, `check-adr-language.log`.
  The supplied `queued` state does not reproduce as a validation failure.
- With `COVERAGE_FILE=<job>/.coverage-release`,
  `uv run coverage run --branch --source=scripts -m pytest tests/test_promote_release.py tests/test_release_guard.py tests/test_check_release_consistency.py tests/test_check_compliance.py tests/test_check_license_inventory.py tests/test_release_publish_metadata.py tests/test_soak_compose_pressure.py tests/release/ tests/test_verify_wheel_imports.py --timeout=60 -x -q`
  — **703 passed** (`check-release-tests.log`).
  `uv run coverage xml -o <job>/coverage-release.xml`, then
  `uv run python scripts/check-diff-coverage.py <job>/coverage-release.xml --base 73610a225d98c602fc014dfbcfe3e399bbe79d9b`
  — PASS, two changed measured production files meet 90% lines / 80% branch
  arcs (`check-diff-coverage.log`). This uses a focused subset of the root
  coverage producer; **the full combined publish-set floor remains UNVERIFIED**.
- Process-local pytest plugin disabled only the live fixture module's
  `verify_dist`; the existing tampered-byte regression failed with
  `assert 0 == 1` while the plugin reported `MUTANT ACTIVE` (pytest exit 1,
  `check-byte-mutant.log`). The same test without the plugin passed (exit 0,
  `check-byte-control.log`). No tracked source was mutated.
- `uv run ruff check .` and `uv run ruff format --check .` — PASS, 3710 files;
  `uv run python scripts/check-suite-inventory.py` — all 21 suites match,
  37719 unique test identities, zero duplicates. No inventory update needed.
- `uv run python scripts/check-release-consistency.py`,
  `uv run python scripts/check-workflow-inventory.py`,
  `uv run python scripts/check-workflow-write-safety.py`, and
  `uv run python scripts/check-doc-links.py` — PASS (33 workflows, zero broken
  links). Logs have the corresponding `check-*.log` names.
- `uv run pytest tests/test_check_required_checks.py tests/test_mutation_targets.py tests/test_check_diff_coverage.py -x -q`
  — **141 passed** (`check-policy-tests.log`).

### Acceptance and remaining owner action

Read accepted ADR-073126-c4e1 and ADR-095 and inspected the reachable CLI,
shipping workflow and adjacent tests. Reconciliation: the issue requests a
real release; accepted authority reserves publication to tag-triggered
`release.yml`, protected develop-to-main promotion and human release approval.
A local publisher, fabricated soak record, or weaker evidence schema is not a
valid substitute. The canonical execution/authorization model is unchanged.

| Criterion | Fresh executed local evidence | Operational acceptance |
| --- | --- | --- |
| RC built only from candidate commit | Record CLI captures real git identity/hashes; workflow tests pin RC-only builds; 703-test battery passes | Hosted candidate build UNVERIFIED |
| Clean install, real-model, security hot path, backup/restore soak | Pinned required-check and per-check rejection tests pass | Actual functional soak UNVERIFIED |
| Exact-RC sustained multi-replica workload with crash/restart, admission/fencing, resource pressure and duplicate detection (#860) | Mandatory `multi_replica_soak`, artifact-binding and missing-soak rejection tests pass | Actual workload/observations UNVERIFIED |
| Invalidating findings filed/reclassified before promotion | Validator and CLI reject absent/malformed routed issue references | Actual routing/issue contents UNVERIFIED |
| Code/runtime-config changes require new RC and applicable soak | Real temporary-git tests reject runtime/config/mode changes and older matching RCs | External/deployed config equivalence and replacement soak UNVERIFIED |
| Final tree/artifacts byte-equivalent to soaked RC | Tree/hash/CLI tests pass; byte-verification bypass mutant killed | Actual RC/final pair and registry digest equality UNVERIFIED |
| External package/image/signature/install verification succeeds | Adjacent release tests pass; clean-install and digest sign/verify workflow inspected | Actual external verification UNVERIFIED |
| Machine-readable soak tied to exact artifact/config | Stale wheel/image binding and malformed config-identity rejection tests pass | Real producer/transport and deployed configuration binding UNVERIFIED |

**BLOCKED on operational acceptance.** `scripts/promote_release.py:49-57`
requires schema-1 `soak-evidence` on the selected RC run; `:578-583` downloads
it. `.github/workflows/release.yml:946-953` preserves it on finals only.
Injected GitHub tests prove rejection and consumption, not a supported
post-RC producer/transport or a sustained soak. This is an explicit cross-lane
contract, not evidence that the producer exists. Captured PR #1672 is open;
no remote status was refreshed. The release/soak owners must supply compatible
real evidence, execute the functional and sustained workloads, route findings,
promote with protected approval, then independently verify external artifacts.
Trusted publishing, release approval configuration and registry permissions
remain UNVERIFIED. The unchanged operational blocker cannot be repaired by
editing a green ledger or re-running local tests.

Progress: checked 1 assigned issue, done 1 focused validation/handoff, skipped 0,
unexpected errors 0; next: release/soak owner evidence and protected operation.
Writer handoff only; not integration approval or issue completion.

## Previous round: develop sync to base `c707949a0a98`, merged head `e30ab607675d`

Job `795e11baa48a440a916c315d6a99fd85`, branch/worktree `auto-89`, started
clean at `64c2eee8b04ed1e5fe9d70ca6932418936526960`. The lane brief named
base `c707949a0a98` and reported the front-matter check `queued` (scheduling,
not a failure); the carried block was the operational soak/promotion BLOCKED.
Fresh fetch showed `origin/develop` at the assigned base `c707949a0a98` — 4
commits (`c707949a0a` M3-A3, `80242f2852` M5-B, `8d8f10616f` M3-E5,
`4f8f40352d` M8-A) past the branch's merge base `69b41dd3af32`, on file sets
disjoint from this branch's diff.

### Actions and fresh execution (all green)

- `git merge origin/develop` — resolved with zero conflicts. Ledger audit per
  docs/quality-gates.md: `git diff --numstat origin/develop -- quality/
  docs/testing/inventory/` prints nothing — ledgers and inventory baseline
  byte-identical to develop, no rows lost (multiset safety check).
  `uv sync --locked --extra dev` after the `uv.lock` change. Post-merge
  merge-base = `c707949a0a98` (exactly the assigned base).
- Front-matter gate, all 7 steps at `e30ab607675d` — registry unit tests
  194 passed; `tools/lint_lifecycle.py` clean; `maistro-registry lint
  . --strict` 447 files / 0 errors; citation ratchet
  `RATCHET_BASE_REV=origin/develop` 0 exceptions, no candidate expansion
  (base resolves to `c707949a0a98`); ADR-INDEX consistent; AC-Defined index
  regenerated with zero diff; body-status language 0 contradictions.
- Vulture exact-debt gate (CI args) — 1218 reviewed identities -> 1218
  findings, unclassified 0. Count moved 1219 -> 1218 with develop's own
  ledger commit; local ledger verified identical to `origin/develop`. No
  amendment made or warranted.
- Coverage gate, diff half — 183 release tests pass under
  `coverage run --branch --source=scripts`; `check-diff-coverage.py --base
  origin/develop` exit 0 (2 measured files at/above 90% lines / 80% arcs,
  3 test files exempt by declaration).
- `ruff check .` / `ruff format --check .` — pass (3699 files formatted).
  Note: one upstream ruff warning about an invalid `# noqa` directive in
  develop's `discovery_source_fetch.py:61` — warning only, not this branch's
  file, exit 0.
- `check-suite-inventory.py` — 21 suites match the recorded inventory.
- `check-doc-links.py` 0 broken; workflow inventory clean (33);
  workflow write-safety ok; backlog consistency OK (167 items).

No source, test, or ledger change was warranted. The only tree changes are
the sync merge commit, this doc, and inventory note
`docs/testing/inventory-notes/verify-89-m3a7-develop-sync-c707949a.md`
(delta +0 tests). Operational acceptance (hosted RC build, #860 multi-replica
soak, actual final promotion) remains UNVERIFIED by construction — see
Acceptance and Handoff sections below.

## Previous round: supplied head `a68a3a1b2369`, base `80242f28521b`

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
