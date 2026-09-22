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

Remaining validation: final diff review, release-mode negative checks at committed
HEAD, final commit. No live Actions artifact or release publication was created;
GitHub mutations are prohibited. Current registry's missing evidence remains an
intentional release blocker rather than fabricated proof.
