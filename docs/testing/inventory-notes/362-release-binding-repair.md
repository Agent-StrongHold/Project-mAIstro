---
inventory-delta:
  tests/: +21
---

# Issue 362 release binding repair

Snapshot: issue #362 only; worktree `/home/dev/Git/wt/auto-362`, branch
`auto-362`, starting HEAD `99b56539fff056f9ab7712fd4f0b42e8d50a0dde`.
Clean starting tree; no salvage needed. No check-*.log files were present in
job 82ad3ec30c984972a681e7bfebb7252e at start. Prior result was read, not
accepted as new validation.

Frozen processing scope: compliance checker/producer, compliance registry and
COMPLIANCE.md, compliance-evidence and release workflows, adjacent compliance
and release tests, this inventory note. Architecture/instructions/CI inventory
and ADR files are read-only context. No other issues or GitHub mutations.

Ambiguity: prompt includes verifier and writer instructions; assigned repair
and mandatory commit are taken to designate this run as writer.

Initial finding: checked-in registry has no digest/evidence; a commit cannot
contain its own SHA. Existing workflow locators still require a precommitted
SHA, so they do not solve the release binding cycle. Preserve unverified
claims and fail-closed release behavior while adding post-commit binding.

Design checkpoint: add an explicit human-reviewed verification request (not a
green status), execute those requests on automatic branch runs, then resolve
immutable artifacts into a release-only registry after the commit exists.
Validate the unchanged committed source first; never replace source claims or
relax release_required. Add integration to evidence branches for ADR-073126-c4e1
RC releases. Keep the single release.yml publication authority and human release
environment approval. OUT-OF-SCOPE compliance/legal ownership remains Stronghold's;
this repair verifies engine technical evidence only, not legal sufficiency.
The earlier guessed inventory note path was not found; skipped, then read the
actual adjacent note returned by the one file snapshot.

Implementation checkpoint: post-commit resolution and explicit reviewed requests
implemented; no registry control was promoted, waived, or requested. Release
workflow preserves validated release JSON and attaches it through the existing
publisher. A real temporary Git repository/annotated tag and real pytest
subprocess now prove the source can remain unchanged while same-SHA evidence
passes. Only GitHub transport is substituted; live Actions is not claimed.

First validation: `uv run pytest tests/test_check_compliance.py -x -q` passed
97 tests in 8.64s (76 existing +21 new cases). Targeted Ruff formatting completed.
The new cases cover real tag binding, uncommitted input/wrong HEAD rejection,
no implicit promotion, invalid request statuses, stale/failed/empty manifests,
artifact checksum/expiry/missing artifact failures, disabled/manual/failed/
in-progress runs, and required release workflow wiring.

Validation checkpoint:
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2495 files).
- `uv run pytest tests/test_check_compliance.py tests/test_release_guard.py -x -q`:
  120 passed in 8.75s.
- `uv run pytest packages/maistro-core/tests/security/warden/test_detector.py -x -q`:
  34 passed in 1.84s (adjacent executable control sanity; not release attestation).
- `uv run python scripts/check-compliance.py`: passed.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: passed, 3603.
- `uv run python scripts/check-ratchet-provenance.py`: passed all delegated gates.
- `bash scripts/verify-monorepo-layout.sh`: passed.

Final validation and handoff:
- `git diff --check`: passed. Final Ruff check/format check passed again.
- Compliance + release tests rerun: 120 passed in 8.12s.
- Implementation committed as `e2d58a8da72c1f2b6375154391ca6dcfa9cd2caf`.
- At that committed HEAD, `uv run python scripts/check-compliance.py
  --require-release-evidence --release-digest <HEAD>` exited 1 with 79 expected
  missing/incomplete evidence problems.
- The same command with `--resolve-release-evidence --resolved-output <temp-file>`
  exited 1 with 52 expected missing/incomplete evidence problems, including
  Articles 15 and 17. Assertions verified both failures and absence of output.
  Resolution removes the impossible self-digest requirement, not the requirement
  for reviewed controls and real evidence.
- Ordinary compliance check and root inventory gate passed again (3603 tests).
- Workflow YAML is parsed and release dependency/upload/download wiring asserted
  by tests. actionlint and shellcheck were not installed; not claimed as run.

Changed files: compliance checker, evidence producer, both compliance-evidence
and release workflows, COMPLIANCE.md, adjacent root tests, and this note. No
control status, release_required flag, quality ledger, grant, scheduler, event
or authorization authority was changed.

Acceptance: document/schema/six statuses and fail-closed evidence behavior are
covered by the passing checker and tests. The real local annotated-tag + pytest
execution fixture proves post-commit binding without source edits. Legal
sufficiency remains explicitly human/Stronghold-owned. Live GitHub API/archive
semantics, first production Actions execution, and full release publication are
UNVERIFIED: transport is simulated in integration tests, and no GitHub mutations
are allowed here. A maintainer must review verification requests and produce
actual evidence before any current release can pass; no request was fabricated.

Progress: checked=1, done=1 repair committed, skipped=0, errors=0 unexpected
validation failures. Next: review the repair and exercise the evidence workflow
on a reviewed branch commit before tagging; the current release remains blocked
on missing control evidence. Handoff verdict: NEEDS-DEEP-REVIEW, not integration
approval.

## Independent re-validation at HEAD ad1c7d530 (job 18e7ee8400c64d1a9df267dcfce69524)

Prior verification findings were re-checked against executable behavior, not
accepted as fact:

- `uv run python scripts/check-compliance.py`: exit 0 (registry + COMPLIANCE.md
  valid).
- The verifier's exact command `--require-release-evidence --release-digest
  99b56539f...`: exit 1 with missing/incomplete evidence errors. This is the
  fail-closed guard working as designed: the at-rest registry intentionally has
  `release_digest: null` (a commit cannot contain its own SHA) and requests are
  only promoted at release time from a same-SHA push run. The release workflow
  never invokes release mode without `--resolve-release-evidence`.
- `--require-release-evidence --release-digest <HEAD> --resolve-release-evidence
  --resolved-output <tmp>`: exit 1, 52 problems incl. EU-AI-ACT-ART-15/17, no
  resolved output written (fail closed, no green fabricated).
- `uv run pytest tests/test_check_compliance.py -q`: 97 passed; the
  `release_candidate` fixture uses a real git repo, real annotated tag, and a
  real pytest subprocess; only GitHub HTTP transport is substituted.
- `uv run ruff check .` / `uv run ruff format --check .`: passed.
- Wiring re-read: ci.yml runs the required `Compliance registry` check on every
  PR; compliance-evidence.yml produces `compliance-evidence-<sha>` on push to
  main/develop/integration; release.yml guard resolves + requires evidence for
  the exact tag SHA before wheels/pypi/images/publish.

Conclusion: all three prior findings describe intended fail-closed behavior or
the transport-only test substitution, not defects. Live GitHub artifact
resolution and a first production Actions run remain UNVERIFIED and require a
reviewed push/tag by a maintainer (GitHub mutations are prohibited here).

## Independent acceptance re-validation at HEAD 6cc0f7493 (job f929a7d6c3264da8b8eca7aff9ad8de4)

No check-*.log files existed in this job directory (prior run died before
checks); all evidence below was executed fresh at HEAD 6cc0f7493, not accepted
from prior claims. No tree edits were needed; this note is the only change.

- `uv run python scripts/check-compliance.py`: exit 0.
- Release mode at HEAD (`--require-release-evidence --release-digest 6cc0f7493...`):
  exit 1, fail-closed missing/incomplete evidence errors, last line
  `registry.release_digest does not match --release-digest`.
- Release mode with `--resolve-release-evidence --resolved-output <tmp>`:
  exit 1, 52 problems explicitly naming EU-AI-ACT-ART-15 and -17 as unverified;
  resolved output file was NOT written (no green fabricated).
- Live AC2 probe (out-of-tree script driving `validate_registry`): forged
  implemented claims blocked for disabled workflow, manual-only, never-run,
  failing result, 6-year-stale observation, wrong evidence digest, cross-control
  evidence, and zero evidence; a locator whose run lookup 404s also fails
  closed (unreachable evidence is not evidence).
- `uv run pytest tests/test_check_compliance.py tests/test_release_guard.py -q`:
  120 passed in 8.04s; re-read `test_real_tag_can_resolve_post_commit_evidence_without_source_edit`
  (real `git init`/annotated tag, real pytest subprocess asserting "1 passed",
  real zip archive + SHA-256; only GitHub HTTP transport substituted; asserts
  source registry byte-identical after resolution) and its parametrized
  provenance/execution negatives assert no output file on failure.
- `uv run pytest tests/test_branch_policy.py -q`: 12 passed; `Compliance
  registry` present in required status checks for develop and main in
  `.github/branch-protection.json`; REQUIRED-CHECKS.md row matches.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed.
- `uv run python scripts/check-ratchet-provenance.py`: passed (0 violations).
- `uv run python scripts/check-suite-inventory.py --suite tests/`: ok.

Acceptance mapping: AC1 (implemented ⇒ executable refs + immutable digest-bound
evidence; registry currently has zero green claims, enforced), AC2 (probe above),
AC3 (document/table/schema/date validation, live at-rest pass + drift tests),
AC4 (six statuses; Articles 15/17 corrected to `unverified`), AC5 (release guard
runs the gate and every publish job needs guard; live exit 1 on missing
evidence), AC6 (human/legal ownership stated in doc, docstring, scopes).
DoD: document is validated from the registry (drift rejected); disabled
workflows cannot back implemented status (derived YAML state + mismatch
rejection, tested live). Residual UNVERIFIED: live GitHub Actions resolution in
production and first real tag release — require maintainer GitHub mutations.

## Independent verification at HEAD fec3601e3014d6be5b020a3334b676a131afc32e (job 86fe3fd755494596a50ef2e29bdfa5af)

Verifier role: re-derived acceptance from issue #362 and executed every check
below fresh at this HEAD; driver check-*.log files covered only uv sync, ruff
check and ruff format, so pytest and the compliance gates were run explicitly.
Read-only except this note; no control, workflow, or test was edited.

- `uv run python scripts/check-compliance.py`: exit 0 (registry + COMPLIANCE.md
  valid at rest; zero implemented claims; ART-15/17 unverified, evidence none).
- `--require-release-evidence --release-digest fec3601e...`: exit 1,
  fail-closed (registry.release_digest is intentionally null at rest).
- Same + `--resolve-release-evidence --resolved-output <tmp>`: exit 1, 52
  problems explicitly naming EU-AI-ACT-ART-15 and -17; output file NOT written.
- `uv run pytest tests/test_check_compliance.py tests/test_release_guard.py -q`:
  120 passed in 8.92s. `tests/test_branch_policy.py -q`: 12 passed.
- `uv run ruff check .` / `ruff format --check .`: passed (2530 files).
- `uv run python scripts/check-ratchet-provenance.py`: OK, 0 violations.
- Live AC2 probe driving `validate_registry`: forged implemented claims BLOCKED
  for disabled workflow, manual-only, never-run, failing result, >90d stale,
  wrong evidence digest, and GitHub-404 (unreachable evidence is not evidence).
- Doc/registry cross-check: 28/28 control IDs match; statuses match registry;
  no disabled-manual-workflow claim remains in COMPLIANCE.md.
- release.yml guard wiring re-read: publish jobs all `needs` guard; compliance
  step uses `$GITHUB_SHA` with resolve+upload (`if-no-files-found: error`);
  branch-protection.json requires `Compliance registry` on develop and main.
- PR body and commit messages scanned: no premature closure keywords
  (fixes/closes/resolves #N absent).

Verdict recorded for this lane: MERGE-READY (writer handoff only, not
integration approval). Residual UNVERIFIED: first production Actions evidence
run and a real tag release require maintainer GitHub mutations, which are
prohibited here.

## Repair-phase validation at HEAD 9f39a9796 (job 33c1d658c2e348cc9a771d05575486fa)

Role: repair/writer. The prior verify run (86fe3fd7) was rejected by the driver
only because its worktree changed mid-run (the note section above was committed
during verification); no defect was found in that commit — it appends this note
only. Per the do-not-assume rule, every acceptance criterion was re-executed
fresh at this HEAD. No check-*.log files existed in this job's directory
(manifest checks: []), so nothing was taken from driver output. Code, registry,
workflows, and COMPLIANCE.md are untouched; the only edit is this section.

- `uv run python scripts/check-compliance.py`: exit 0 (at rest: 28 controls,
  zero implemented, zero evidence; ART-15/17 unverified). Also exit 0 under
  plain `python3` (CI's system-interpreter path, PyYAML 6.0.3).
- Release mode without resolve, `--require-release-evidence --release-digest
  9f39a9796...`: exit 1, 79 problems (fail-closed at rest; a commit cannot
  contain its own digest).
- Same + `--resolve-release-evidence --resolved-output <tmp>`: exit 1, 52
  problems explicitly naming EU-AI-ACT-ART-15/-17 as `unverified`; the resolved
  output file was NOT written (no green fabricated).
- `uv run pytest tests/test_check_compliance.py tests/test_release_guard.py
  tests/test_branch_policy.py -q`: 132 passed in 9.88s.
- `uv run ruff check .` / `uv run ruff format --check .`: passed.
- `uv run python scripts/check-ratchet-provenance.py`: OK, 0 violations.
  `uv run python scripts/check-suite-inventory.py --suite tests/`: ok.
- Live AC2 probe driving `validate_registry` (out-of-tree script): forged
  implemented claims BLOCKED for disabled workflow, manual-only, never-run,
  failing result, 91-day stale observation, wrong evidence digest, expired
  expiry, empty evidence, empty test_refs, and non-test executable refs; a
  locator resolving against live GitHub (404 run/artifact lookups) also fails
  closed. `_workflow_state` on a real workflow_dispatch-only YAML fixture
  derived (enabled=False, manual_only=True).
- AC3/AC4 cross-check: 28/28 registry controls appear in the COMPLIANCE.md
  table in order with matching statuses; status distribution 17
  partially_implemented / 5 documented / 2 planned / 2 not_applicable / 2
  unverified; no `verification_requested` is set; every evidence cell is `none`.
- AC6/DoD: human-ownership statement present in COMPLIANCE.md and the checker
  docstring. The only disabled workflow in the repo (mutation.yml, "temporarily
  disabled" header) is cited solely as a `control_ref` of NIST-MEASURE, which
  is `partially_implemented` with `evidence: []` — no disabled workflow backs
  any implemented-and-tested claim, and the implemented path derives and
  rejects workflow state mismatch (probe + tests).
- Adjacent executable-control sanity: 49 tests passed across two registry-
  cited suites (quota tracker, sentinel policy).

Every acceptance criterion maps to executed evidence above; nothing was
accepted from prior claims. Residual UNVERIFIED (unchanged, requires
maintainer GitHub mutations prohibited here): the first production
compliance-evidence Actions run and the first real tag release. Handoff:
MERGE-READY as writer handoff only, never integration approval.
