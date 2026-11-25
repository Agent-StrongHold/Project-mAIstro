---
inventory-delta:
  tests/: +0
---

# #2304 — research-image guard tests re-targeted onto develop's donor overlay

## Why

The develop sync in this branch's merge base brought a newer resolution of
the same two supply-chain problems the branch's round-8/9 guard tests were
written against, and the merge kept develop's `Dockerfile.research` side
while keeping the branch's tests — five of which then red at HEAD (the CI
`test` job at `ebe02132a1`, and reproducibly locally):

1. **libatomic1.** Round 8 installed `libatomic1` explicitly because
   playwright 1.65.2's bundled Node driver links `libatomic.so.1` and the
   then-bookworm base's apt closure did not provide it (CI exit-127
   evidence at head `094944a81`). Develop moved the base to the floating
   `python:3.12-slim` digest — Debian **trixie** — where
   `libglib2.0-0t64` (in the image through the Chromium X-stack) depends on
   `libatomic1`, so the driver's dependency is satisfied transitively and
   develop dropped the explicit line. Measured 2026-11-25 against the
   pinned base digest `5e2bdb1b…`: fresh base does not ship the library;
   installing the stage's exact apt list auto-installs `libatomic1`
   14.2.0-19 with `apt-cache rdepends --installed libatomic1` naming
   `libglib2.0-0t64`; `ldd` on the locked playwright 1.65.2 wheel's
   `driver/node` confirms it still needs `libatomic.so.1`.
2. **Driver-node swap.** Round 9 fetched a checksum-verified Node tarball,
   set `PLAYWRIGHT_NODEJS_PATH`, deleted both wheels' bundled binaries and
   pruned npm. Develop's narrower overlay (#2431 lineage) replaces that:
   playwright 1.65.2 already ships fixed Node v26.13.1, only patchright
   1.64.4 still bundles the grype-flagged v24.22.1, and the image copies a
   single `node` binary out of the digest-pinned
   `node:26.13.1-bookworm-slim` donor stage, overwrites patchright's
   `driver/node`, and asserts `node -v` in-build so the build fails on a
   moved wheel layout or version mismatch.

A root-`Dockerfile` divergence the sync left behind is repaired in the same
commit: the engine image's `dockerclibuild` stage kept the branch-side
`-mod=vendor` build while research took develop's `-mod=mod`, reding
`test_engine_and_research_stages_stay_in_sync`. After `go get <fixed> &&
go mod vendor` both build modes compile the patched module set (there is no
security delta), so the engine stage is aligned to develop's reviewed
bytes; both Dockerfiles are now byte-identical to `origin/develop`.

## Change

- `tests/test_research_image_playwright_runtime.py` — same five-test
  count, re-targeted: the two libatomic tests become guards on the
  Chromium runtime stack the production-apt stage must name explicitly
  (playwright-in-lock ⇒ stack present), and the three round-9 swap tests
  become guards on the overlay (donor stage pinned to the bookworm glibc
  image at v26.13.1 with an index digest; COPY + heredoc overwriting
  patchright's `driver/node`; in-build version assertion;
  patchright-in-lock ⇒ overlay legs present). The module docstring records
  the supersession with the measurements above.
- `tests/test_dockercli_vendored_cve_patch.py` —
  `test_stage_revendors_and_builds_in_vendor_mode` renamed to
  `test_stage_revendors_and_builds_the_patched_module_set` and re-asserts
  develop's `-mod=mod` posture (go.mod superseding the tag's stale
  vendor/ tree) for both scanned images.
- `Dockerfile` — dockerclibuild stage aligned to develop (`-mod=mod`),
  removing the only remaining engine/research divergence from trunk.

No test added or removed: both files keep their recorded counts, hence the
`+0` delta.

## Evidence

- `uv run pytest tests/test_research_image_playwright_runtime.py
  tests/test_dockercli_vendored_cve_patch.py
  tests/test_hive_conductor_image_split.py
  tests/test_root_image_interpreter_lines.py -q` → 16 passed.
- `uv run pytest tests/ -q` → 6073 passed, 140 skipped, 0 failed.
- In-image probe on `maistro-engine-research:ci` (built locally from HEAD
  bytes): `patchright driver node: v26.13.1`, `playwright driver node:
  v26.13.1`, npm absent — the overlay produces the scanner-clean surface
  the guards assert.
- `uv run python scripts/check-image-pins.py` → 11 pinned images, all
  registered; `scripts/check-suite-inventory.py` → 21 suites match;
  vulture CI-exact (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`) → 1221 = 1221; `ruff check .` and
  `ruff format --check .` green.
