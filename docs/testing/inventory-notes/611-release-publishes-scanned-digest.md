---
inventory-delta:
  tests/: +22
---
# 611-release-publishes-scanned-digest

Issue #611 (#346 AC-5): the release must publish the digest that was
scanned, not a rebuild of it. `release.yml` now builds each published image
exactly once into its `-rc` quarantine repository, scans the candidate digest
with Trivy and Grype under security.yml's policy, applies the release tags to
the scanned digest via `docker buildx imagetools create` only after both
scans pass, and cosign-signs that same digest. `quality/image-inventory.json`
flips both `published_digest_verified` flags to `true` — and the +13
collected node IDs in `tests/` are the gate (`scripts/check-image-inventory.py`)
holding that claim to the wiring that makes it true:

- full wiring (build → trivy scan → `imagetools create` promote → `cosign
  sign`, all bound to `steps.<id>.outputs.digest`) passes with the flag
  `true`;
- `true` without a Trivy/Grype step consuming the built digest fails;
- `true` without an `imagetools create` applying the release tags to that
  digest fails — the original gap, where job names were the only evidence;
- `true` without a `cosign sign` of that digest fails (the signature would
  attest an artifact the release does not publish);
- `true` with the promote step placed before the scan step fails on ordering,
  because a finding at the gating severity must stop the publish, not
  correct it;
- `true` with the build itself tagging `:latest` or consuming the computed
  release-tag outputs fails — the build may only push to the quarantine;
- `true` with the build pushing any non-quarantine destination — including
  the immutable version tag itself (`tags: …:${{ github.ref_name }}`) or one
  production repo smuggled into a block-scalar `tags:` list — fails: every
  build destination must be a `-rc` quarantine, so no release tag exists
  before the scans admit the digest (an all-quarantine block-scalar list
  passes);
- the publishing job's steps stop at the next sibling job: scan/promote/sign
  wiring living in a later job does not satisfy this job's claim, and the
  full wiring in a job that is followed by a sibling still reads;
- `true` with no `docker/build-push-action` push, a push step that declares
  no `id:` (nothing to bind a scan to), or a job with no steps at all fails;
- `false` still records the gap without demanding wiring (the honest state of
  an unwired release path), and a non-boolean flag fails;
- a real-tree test pins that both shipped PUBLISHED entries carry the claim
  and the gate's wiring read of the real `release.yml` holds — the test that
  fails if the release is rewired back to publish-before-scan without
  re-recording the claim.

The wiring is read from the workflow text (same line-anchor approach as the
gate's job parser, no YAML dependency), and the negative tests assert the
gate's actual failure text, so a reworded message cannot silently stop
describing the violation.

## Validation log (2026-10-07, head a936e58a6)

- `uv run pytest tests/test_check_image_inventory.py -q` — 37 passed (24
  pre-existing + 13 new).
- `uv run pytest tests/ -q -x --timeout=120` — 4675 passed, 128 skipped
  (= the 4803 collected identities the suite inventory records).
- `uv run python scripts/check-suite-inventory.py --suite tests/` — ok, 4803
  unique identities match the recorded inventory with this note's +13.
- `uv run python scripts/check-diff-coverage.py coverage.xml --base
  b0912ce590d51bcfe4944da57770575e50ae2e8a` — ok, changed gate lines ≥90%
  lines / ≥80% branch arcs.
- `uv run python scripts/check-image-inventory.py` — ok; the gate's wiring
  read accepts the re-wired `release.yml` with both flags `true`.
- `uv run python scripts/check-image-pins.py`,
  `scripts/check-workflow-inventory.py` — ok.
- `uv run ruff check .` / `ruff format --check .` — clean.
- Mechanism proof against a real registry (docker 29.7.2, buildx v0.37.2,
  registry:2): a build pushed with `--provenance=mode=max --sbom=true` to a
  quarantine repo, then `docker buildx imagetools create -t
  <prod>:v1 <rc-repo>@sha256:9e15931a…` — the promoted tag resolves to the
  identical index digest, and the attestation manifest is visible under the
  promoted tag, so the #349 provenance check still finds its materials on the
  production digest.

## Validation log (salvage, 2026-10-07, head 38b2bcb27 + this change)

- Salvage resumed from 38b2bcb27, which had already hardened
  `_is_blocking_scan` (+4 tests) against the reporting-only scan finding:
  a scan must carry the blocking policy (trivy-action `exit-code: "1"`, or a
  trivy/grype `run:` line with `--exit-code 1` / `--fail-on`), and steps with
  `continue-on-error: true` never gate. Its +4 node IDs were never recorded —
  folded into this note's delta (+13 → +22, with this round's +5).
- Codex review findings reproduced against the pre-repair gate and then
  fixed:
  - sibling-job step absorption: a workflow whose publishing job builds but
    whose next job scans/promotes/signs passed `check_publish_wiring` —
    `_job_bounds` ended the block only at column 0. Now ends at any
    two-space sibling key; reproduced failure shows all three missing-wiring
    errors.
  - build-tag confinement: `tags: ghcr.io/example/maistro-engine:${{
    github.ref_name }}` passed — only `:latest` and `steps.*` tags were
    rejected. Now every build destination (inline or block-scalar) must name
    a `-rc` repository.
- `uv run pytest tests/test_check_image_inventory.py -q` — 46 passed.
- `uv run python scripts/check-image-inventory.py` — ok (9 Dockerfiles,
  PUBLISHED 2, both flags true).
- `uv run python scripts/check-suite-inventory.py --suite tests/` — ok
  (see below for the exact command output).
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `uv run python scripts/check-image-pins.py`,
  `scripts/check-workflow-inventory.py`,
  `scripts/check-backlog-consistency.py` — ok.
