---
inventory-delta:
  tests/: +76
---

# Issue #362 compliance registry gate

Adds root tests covering registry schema validation, explicit statuses,
immutable evidence requirements, release-digest fail-closed behavior, disabled,
manual-only, or stale evidence, evidence scope and GitHub artifact provenance,
commit-bound workflow locator resolution, test-reference shape,
release-required unverified controls, the no-tag evidence workflow, and
malformed or drifting COMPLIANCE.md table rows.

The repair batch adds: mandatory `expires` on every `implemented`,
`partially_implemented`, or `documented` claim (a null expiry can never go
stale, so it fails closed), attestation content and artifact-provenance failure
paths, commit-bound artifact resolution failures, GitHub API failure handling,
workflow-state derivation failures, registry/evidence schema failure tables,
document structure and drift rejections, checker and producer `main` exit
codes, and producer fail-closed behavior for subprocess failures or empty test
lists.

## Independent verification round (2026-09-25)

Verified at branch head `53d61585d135859edbe1d8069ce28ce3a3529314` (develop base
`03c8ba83a7119c7bf9f734aff0ab8be4cbf975c0`); no tree edits beyond this note.

- `python scripts/check-compliance.py` exit 0 at rest ("compliance registry and
  COMPLIANCE.md are valid").
- Release mode `--require-release-evidence --release-digest 53d61585d…`
  `--resolve-release-evidence` exit 1 and refused to write the resolved output
  (fail closed for all 26 `release_required` non-green controls).
- `uv run pytest tests/test_check_compliance.py -q`: 97 passed (9.2s); 17
  acceptance-critical tests re-run explicitly. `uv run ruff check .` and
  `uv run ruff format --check .` clean; `check-branch-protection.py`,
  `check-required-checks.py`, `check-ratchet-provenance.py`,
  `check-branch-independence.py` all exit 0 at this head.
- Independent string-level probes (no source edits): forged `implemented`
  ART-15 document row rejected as registry drift + implemented-without-evidence;
  dropped status cell rejected as malformed row (8 vs 9 cells); registry-side
  forged implemented claim rejected (no release digest / no immutable evidence).
- Registry fact check: 28 controls, 0 `implemented`, evidence arrays all empty,
  no `verification_requested` set; ART-15/17 `unverified`.
- Residual UNVERIFIED (requires GitHub mutations outside this lane): first
  production `compliance-evidence.yml` run on main/develop, and the first real
  tag release resolving evidence at that exact SHA. The real-tag fixture
  (`test_real_tag_can_resolve_post_commit_evidence_without_source_edit`) covers
  the binding with a real git repo + real pytest subprocess; only GitHub I/O is
  faked.
- Note: `uv run mypy scripts/check-compliance.py` (not a project gate — CI mypy
  targets `packages/*` only) reports 2 strict-mode errors (lines 408, 878);
  recorded, not blocking.

## Repair-phase re-validation (2026-09-25, head `357fcbc7fae46842a468d148d510475259315bc6`)

No source edits; validation-only round recorded in this note.

- `uv run python scripts/check-compliance.py` exit 0 at rest.
- Release mode `--require-release-evidence --release-digest <HEAD>` exit 1 with
  79 problems (all 26 `release_required` controls fail closed; ART-15/17
  `unverified` blocks release).
- `uv run pytest tests/test_check_compliance.py -q`: 97 passed (12.7s).
  `uv run ruff check .` and `uv run ruff format --check .` clean.
  `check-branch-protection.py`, `check-ratchet-provenance.py`,
  `check-branch-independence.py` all exit 0.
- String-level probes via the checker module (files copied, no tracked-file
  edits): dropped Status cell → rejected (8 vs 9 cells); forged `implemented`
  ART-15 document row → rejected (registry drift + implemented-without-
  evidence); registry-side forged `implemented` ART-15 → rejected (no release
  digest, no immutable evidence); `_workflow_state` on the live
  `compliance-evidence.yml` → `(enabled=True, manual_only=False)`.
- Wiring: ci.yml `compliance` job runs on push (main/integration/develop), all
  PRs, and merge_group; "Compliance registry" is a required check for develop
  and main in `.github/branch-protection.json`; release.yml `guard` job runs
  the fail-closed check before `wheels`/`pypi`/`images`/`github-release`
  (all `needs: guard`) and attaches the validated `release-compliance.json`
  to the GitHub release with SHA256SUMS.
- Prior CI findings at this head re-examined: `wheel-imports` reproduced
  locally — `uv build` of all 10 package wheels plus
  `scripts/verify-wheel-imports.py --dist ... --python 3.12` exit 0 (all bare
  and extras import checks pass), and the lane diff touches no `packages/*`;
  `integration-scope` is an aggregate that includes `wheel-imports`, so both
  failures are transient/aggregate CI noise, not acceptance failures.
- Residual UNVERIFIED (unchanged, requires GitHub mutations outside this
  lane): first production `compliance-evidence.yml` push run on main/develop,
  and the first real tag resolving evidence at that exact SHA.

## Independent verifier re-validation (2026-09-25, head `3cbd0cc3c5d33a5f186112fa193109725e0cb449`)

Fresh review run at the exact PR head; develop base `03c8ba83a7119c7bf9f734aff0ab8be4cbf975c0`
unchanged. Delta `357fcbc7f..HEAD` is note-only (this file, +34 lines), so all
gates behave identically at both heads.

- `uv run pytest tests/test_check_compliance.py -x -q`: **97 passed** (10.2s),
  executed by the verifier, not inherited.
- `uv run ruff check .`: clean. `uv run python scripts/check-compliance.py`:
  exit 0 ("compliance registry and COMPLIANCE.md are valid").
  `scripts/check-branch-protection.py`: exit 0.
- Release mode executed by verifier:
  `check-compliance.py --require-release-evidence --release-digest <HEAD>`
  → exit 1, fail-closed problems incl. "registry.release_digest does not match
  --release-digest" and all release_required controls not implemented.
- Verifier's own forgery probes (in-memory module load, no tracked-file edits):
  forged `implemented` ART-15 rejected (no digest/no evidence/no last_verified);
  disabled-workflow evidence rejected ("has disabled workflow evidence
  supporting implemented status"); 8-cell table row rejected ("has 8 cells;
  expected 9"); forged document row rejected (registry drift);
  `_workflow_state(compliance-evidence.yml)` → `(True, False)`; STATUSES =
  exactly the six required; MAX_EVIDENCE_AGE = 90 days.
- mypy gate re-run with the exact CI target list (`packages/*/src`):
  "Success: no issues found in 713 source files", exit 0 — confirms the strict
  mypy notes above are non-gate.
- wheel-imports CI failure at `357fcbc7f` independently reproduced as green by
  the verifier: all 10 package wheels built with `uv build` into a temp dist,
  `scripts/verify-wheel-imports.py --dist ... --python 3.12` → exit 0 ("All
  wheels import from a clean venv"). Lane diff touches no `packages/*`;
  `integration-scope` aggregates `wheel-imports` → both CI failures are
  transient, not acceptance failures.
- Closure-keyword audit: PR #1464 body contains only "Refs #362"; no
  fixes/closes/resolves with issue refs in any commit message on the branch
  (one commit body uses the word "closes" in prose about a coverage finding,
  no issue ref — cannot auto-close).
- Residual UNVERIFIED (unchanged, requires GitHub mutations outside this
  read-only lane): live CI rollup at head `3cbd0cc3c`, first production
  `compliance-evidence.yml` push run, and the first real tag resolving
  evidence at its exact SHA.
