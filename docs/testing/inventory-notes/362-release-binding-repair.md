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
