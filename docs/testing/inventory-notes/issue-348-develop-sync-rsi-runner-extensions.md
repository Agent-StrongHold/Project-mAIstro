---
inventory-delta:
  tests/: +1
---

# issue-348-develop-sync-rsi-runner-extensions

Develop-sync repair round for #348 in worktree auto-348: merging
origin/develop (e20e9f52e) made the reference-gallery extension packages
(`extensions/reference-gallery/packages/*`) and `extensions/reference-greeter`
workspace members of the root `pyproject.toml` / `uv.lock`. Every `--locked`
install resolves the WHOLE workspace, so `Dockerfile.rsi-runner`'s
`uv sync --locked` could no longer resolve without the extensions tree in its
build context — the one production Dockerfile that did not copy it. This
round carries that repair, tightens the contract test so the regression class
is gated, and re-proves the image contracts on the merged lock.

## What this round changed

- `Dockerfile.rsi-runner`: `COPY extensions/ /workspace/extensions/` added
  (uncommitted salvage from the blocked prior round, normalized to the same
  `extensions/` form the other four production Dockerfiles use). The members
  are workspace metadata for the lock check, not installed surface.
- `tests/test_image_lock_contract.py`: `Dockerfile.rsi-runner` joined
  `TestWorkspaceMetadataIsPresent` (+1 parametrized case), whose docstring now
  covers `uv sync --locked` as well as `uv export --locked`. Without this, the
  only gate that names the extension-copy contract was silent on the one image
  that syncs rather than exports.
- `docs/testing/inventory-notes/issue-348-lock-enforced-images.md`: front matter
  repaired two ways — (a) to the parser contract develop tightened (delta lines
  must be `<recorded suite>: <±int>`; the old note's `scripts/:`/`workflows/:`
  lines with prose suffixes failed `scripts/check-suite-inventory.py` after the
  merge and moved into that note's body), and (b) `tests/: +0` corrected to
  `tests/: +23`: 144286fcf added `tests/test_image_lock_contract.py` (23
  parametrized cases) with no delta recorded anywhere, and the gate drifted by
  exactly +23 at the merged tip (expected 5628 vs collected 5651). ci.yml:701
  runs this gate, so the merged branch was red on it before this repair.

## Evidence (all executed locally this round, docker 29.1.3)

- `uv lock --check` on the merged lock: clean (468 packages).
- Negative control (the failure the COPY prevents): scratch tree from
  `git archive HEAD` minus `extensions/`, `uv sync --locked --python 3.12
  --extra rsi-fitness --dry-run` → exit 1, "reference-greeter references a
  workspace in `tool.uv.sources` ... but is not a workspace member". Positive
  control: same command with `extensions/` present → exit 0.
- `docker build -f Dockerfile.rsi-runner` (salvage in context): green, and
  `scripts/check-image-lock-reconciliation.py` against the built image →
  "ships exactly the locked set (220 distributions, incl. 4 workspace
  member(s))".
- `docker build -f Dockerfile` (engine): green, reconciliation → "ships
  exactly the locked set (127 distributions, incl. 3 workspace member(s))".
- #348 AC-2 unresolvable-artifact half, executed both directions:
  `uv pip install --require-hashes --no-deps` of a lock export block whose
  hash was replaced with `f`*64 → exit 1 ("Computed: sha256:ce2f…"); the same
  block with the locked hash → exit 0. Drift half: `--locked`/`--frozen` are
  asserted per-Dockerfile by `tests/test_image_lock_contract.py`, and the
  negative control above shows the locked install failing the build outright.
- `scripts/check-build-context.py`: ok — both ignore files carry the same 60
  rules, deny all 27 secret patterns, exclude nothing tracked (extensions/
  is not denied, so the COPY delivers the metadata).
- AC-5 (CI rebuilds twice and compares manifests): the job stands at
  ci.yml `docker-rebuild-compare`; its dump command is exactly the one the two
  reconciliations above executed against built images. The double `--no-cache`
  rebuild with byte-identical manifests was executed and recorded in
  `issue-348-lock-enforced-images.md`; this round did not repeat it.
