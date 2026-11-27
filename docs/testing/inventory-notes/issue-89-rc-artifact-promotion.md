---
inventory-delta:
  tests/: +47
---

# Issue #89: byte-equivalent final promotion — adopt the soaked RC artifacts

Scope: the shipping workflow's promotion path and the new script that
enforces it. ADR-073126-c4e1 §6: "the final release ships the artifacts the
last rc already validated." Before this change, `release.yml` rebuilt wheels
and container images for a final tag; equal git trees (guarded since the
previous round) make a rebuild *plausible*, not identical — wheel zip members
carry build-time mtimes and image builds re-resolve base layers and locks. A
rebuilt final was a different byte sequence from the candidate the soak
exercised, which voids the soak's evidential value.

## What changed

- `scripts/release_guard.py` (finals, `--verify-rc-tree`): emits the selected
  candidate as an `rc_tag` output — the single source of truth for which RC's
  artifacts the final must adopt. No output on failure; candidates still
  build without a previous candidate.
- `scripts/promote_release.py` (new, stdlib only): the fail-closed promotion
  contract.
  - `record-evidence` (RC runs): freezes one machine-readable identity record
    (tag, commit, tree, run, sha256 of every artifact).
  - `adopt-wheels` (final runs): locates the successful release run of the
    selected RC tag, downloads that run's evidence and `dist` artifacts, and
    verifies every file against the recorded sha256 — byte for byte. A
    mismatch, missing file, or extra file fails the release.
  - `adopt-digests` (final runs): validates the soak evidence bound to the
    exact wheel sha256 map + image digests + configuration digest, requires
    pass-with-cited-evidence on clean install, real-model execution, security
    hot path, backup/restore, and the #860 multi-replica workload, requires
    every invariant-invalidating finding to name the issue it was routed to,
    then emits the digests the images job re-tags.
  - `finalize-evidence` (images job): binds the promoted digests and, for
    finals, the promotion linkage (which RC run the bytes were adopted from).
  - Run selection is strict: the LATEST release run of the selected tag must
    have succeeded; neither an older successful run nor an older candidate is
    acceptable promotion evidence.
- `.github/workflows/release.yml`:
  - `wheels`: builds only for candidates (`prerelease == 'true'`); finals
    adopt the soaked candidate's bytes and re-run twine check, filename
    verification, clean-venv import and minimum-dependency floors against the
    adopted bytes. The candidate identity record travels as the
    `release-evidence-wheels` artifact.
  - `images`: builds only for candidates (quarantine rule unchanged); finals
    adopt the soaked digests (`rc_evidence` step) after gating on soak
    evidence, then scan, Canvas-proof, promote (`imagetools create` on the
    adopted digest), sign, verify, attest and SBOM those SAME digests. The
    `release` environment approval still gates everything public.
  - `github-release`: attaches `release-evidence.json` (always) and
    `soak-evidence.json` (finals) as release assets under the SHA256SUMS, so
    the machine-readable evidence ships with the exact promoted
    artifact/configuration.
  - Verified with actionlint 1.7.7 (`-shellcheck`), which caught and the
    fix removed an ordering bug (a digest consumer referencing the adopt
    step's outputs before that step ran).

## Tests (+47 collected cases in `tests/`)

`tests/test_promote_release.py` (new): record/adopt/finalize validation over
real files and real hashes — evidence field corruption matrix (schema,
version, tag, git ids, run id incl. the bool-is-int trap, run URL, wheel-map
shape incl. path traversal), image-map completeness, soak binding (bytes,
digests, configuration), every required soak check gating promotion on
status and cited evidence, finding-routing enforcement, hash mismatch /
missing / extra dist files, strict RC run selection (latest attempt, other
tags, other workflows, failed-latest blocks), the real zip download path
(gh api payload unpacked; gh failure fails loudly), end-to-end `adopt-wheels`
success and fail-closed paths (tampered bytes, record-of-another-tree), end-
to-end `adopt-digests` (digest emission, missing soak artifact, unrouted
findings), `record-evidence` against a real git repo, `finalize-evidence`
linkage rules, and the workflow wiring test asserting candidates-only builds,
finals-only adoption, `actions: read`, digest fallthrough wiring, and the
soak-evidence publication.

`tests/test_release_guard.py` (+3): `rc_tag` output names the highest numeric
candidate; RC runs emit none; failed tree checks write no outputs.

## Focused validation (this head, not inherited)

- `uv run pytest tests/test_promote_release.py tests/test_release_guard.py -q`
  → **82 passed**.
- `uv run ruff check scripts/promote_release.py scripts/release_guard.py
  tests/test_promote_release.py tests/test_release_guard.py` → exit 0 (the
  C901/SIM102 findings raised during development were fixed by extracting
  `_validate_identity`/`_validate_binding`/`_validate_checks`/
  `_validate_findings`, not suppressed).
- `uv run ruff format --check scripts/ tests/test_promote_release.py
  tests/test_release_guard.py` → exit 0.
- `actionlint 1.7.7 -no-color -oneline -shellcheck` over `release.yml` →
  clean (CI's exact flags, CI's shellcheck).
- `uv run python scripts/check-image-inventory.py` → exit 0; the
  `published_digest_verified` wiring (build → blocking scans → promote →
  sign, in that order, quarantine-only builds) still holds with the
  conditional finals path.
- `uv run python scripts/check-workflow-inventory.py` → exit 0 (31 workflows).
- `uv run python scripts/check-release-consistency.py` → exit 0.
- `uv run python scripts/check-suite-inventory.py --suite tests/` → after
  recording this delta: collected **5932** node IDs match baseline + deltas.

## Acceptance handoff — what is now proven locally, what is not

| Issue #89 criterion | Status after this change |
|---|---|
| RC artifacts built only from the candidate commit | **Implemented and test-pinned**: candidates build; finals fail if they would rebuild (`tests/test_promote_release.py::test_shipping_workflow_promotes_rc_artifacts_on_finals`). Actual execution still requires a real tag run. |
| Soak includes clean install / real-model / security hot path / backup-restore | **Gate implemented**: promotion refuses without pass-with-evidence for each (`validate_soak`). Executing the soak remains external. |
| #860 exact-RC sustained multi-replica soak | **Gate implemented**: `multi_replica_soak` check required, bound to the exact artifacts/config. #860 itself remains open (frozen snapshot); producing the evidence is that lane's work. |
| Findings invalidating an earlier invariant routed before promotion | **Gate implemented**: `invalidates_invariant: true` without `routed_issue: #N` fails promotion. |
| Code/runtime-config change requires new RC + new soak | **Strengthened**: tree drift was already rejected; now artifact/drift *and* soak records must bind to the latest candidate's run, whose digest the final re-tags. |
| Final byte-equivalent to soaked RC | **Implemented**: finals adopt RC wheels (sha256-verified) and re-tag RC image digests (`imagetools create`); no final build exists on the path. Actual byte equality of a real RC/final pair remains UNVERIFIED until a release is run. |
| External package/image/signature/install verification | **Unchanged mechanism, re-targeted to adopted bytes**: finals re-run twine/import/floors, re-scan and Canvas-proof the adopted digest, verify cosign signatures. External execution remains UNVERIFIED. |
| Machine-readable soak evidence tied to exact promoted artifact/config | **Implemented and test-pinned**: evidence schema, artifact binding (exact maps), config digest, promotion linkage; shipped as release assets. A real evidence-producing soak remains UNVERIFIED. |

Residual (external, not reachable from this worktree): actually cutting a
release, running #860's soak, PyPI trusted-publisher registration, the
`release` environment reviewer — maintainer actions outside this lane's
no-GitHub-mutations boundary. The pipeline now *requires* those inputs and
fails loudly without them; it no longer *bypasses* them by rebuilding.

Writer handoff: MERGE-READY as a lane artifact (handoff only, never
integration approval); the release itself stays blocked on real soak
execution, exactly as the issue's contract demands.
