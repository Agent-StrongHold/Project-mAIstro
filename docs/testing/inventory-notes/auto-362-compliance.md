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
