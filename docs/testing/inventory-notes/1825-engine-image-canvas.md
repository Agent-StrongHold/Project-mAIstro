---
inventory-delta:
  tests/: +7
---

# #1825 — the shipped engine image must carry (and prove) its Canvas surface

The engine advertises `/v2/canvas`, but the root Dockerfile's dependency
install omitted `maistro-canvas`: `_wire_canvas_ability()` hit `ImportError`
at startup, left `app.state.canvas_store` unset, and every Canvas route
answered 503 forever — invisible to `/health/live`, a healthy API container,
or a monorepo test environment where `uv sync` installs everything. The
repair ships the package in the supported image and proves the artifact.

## Production changes

- `Dockerfile` — the builder stage COPYs and pip-installs
  `./packages/maistro-canvas`; the runtime stage deliberately does not copy
  the source tree (the wheel is pure Python, so nothing reads it from disk,
  and keeping it out preserves a clean "imports come from the venv alone"
  proof boundary).
- `scripts/smoke-engine-canvas.sh` — the artifact-level proof, ONE
  implementation consumed by two workflows: an import probe of
  `PgCanvasStore` and the PIL-backed compositor run with `--network=none`,
  no mounts and no PYTHONPATH (image contents only); a control probe against
  the Dockerfile's own pinned builder base that must FAIL (so a probe that
  lost its teeth fails loudly); then the pre-existing boot smoke
  (clean PostgreSQL 18 volume, migration through the shipped entrypoint,
  migrated-cluster restart durability) extended with the Canvas proof:
  `canvas_store_unavailable` (the error-level branch) asserted absent, an
  authenticated create/read through `/v2/canvas`, the unauthenticated request
  refused, and the row verified in PostgreSQL itself. Prints the tested
  image id / repo digests, so the evidence names its artifact.
- `.github/workflows/ci.yml` — the docker-build job's inline boot smoke is
  replaced by the script (its restart-durability logic moved verbatim), so
  CI proves the built candidate.
- `.github/workflows/release.yml` — the images job runs the same script
  against the exact pushed candidate digest (its `maistro-engine-rc@<digest>`
  quarantine reference — the release build is push-only into `-rc`, and
  promotion re-tags that same digest, so this is still the digest the
  release tags resolve to) before signing it, so publication consumes the
  digest the Canvas proof tested.
- `quality/image-inventory.json` — the maistro-engine rationale names the
  Canvas-enabled supported profile and its proof; Dockerfile.research is
  identified as a deliberately Canvas-lean profile whose `/v2/canvas`
  reports 503 truthfully.

## Test moves (+7 `tests/`)

`tests/test_engine_canvas_packaging.py` (new, 7 cases, three layers):

- 4 static cases (no Docker, every PR): the builder stage must COPY and
  pip-install maistro-canvas; both workflows must still invoke the smoke
  script; the script's Canvas-less control image must equal the Dockerfile's
  pinned builder base; the script must keep the isolation (`--network=none`)
  and behavioral (PostgreSQL row check, auth refusal) markers — including a
  guard that it never gates on the `canvas_store_wired` log line, which the
  production structlog level filters out.
- 3 Docker-gated cases (skip without `MAISTRO_ENGINE_IMAGE`, the same
  opt-in contract as `MAISTRO_TEST_PG_DSN`; the full boot smoke additionally
  wants `MAISTRO_ENGINE_IMAGE_SMOKE=1`): the built image must pass the exact
  probe the script runs, the Canvas-less control must fail it with
  `ModuleNotFoundError`, and the full smoke must end in PASS.

`tests/test_distribution_contract.py::test_docker_build_job_boots_the_image_it_built`
was reshaped (no count change): the live→ready boot order it pinned inline
now lives in the script, so the workflow-side half pins the invocation
following the build and the script-side half pins the boot order.

## Validation on this head

Re-validated on the develop-synced head (merge of origin/develop
`9a4b0c5cc` resolved cleanly, commit `47a63e397`) by rebuilding the artifact
and re-running every layer:

- Built `maistro-engine:test` from this tree (image id
  `sha256:ee98c889803fc31521e9a72f858d1e0d23b3d5271f3f8d535d69726fce20a817`)
  and ran `scripts/smoke-engine-canvas.sh` against it: PASS — import probe on
  image contents only (`--network=none`, no mounts; printed
  `maistro-canvas 0.9.0 PgCanvasStore`), Canvas-less control failed the probe
  as expected, boot through the shipped entrypoint (`python -m
  maistro_server.entrypoint` → `alembic upgrade head` → uvicorn) on a clean
  PostgreSQL 18 volume with the `alembic_version` row verified, no
  `canvas_store_unavailable` in the logs, authenticated create/read through
  `/v2/canvas` with the row verified in PostgreSQL, unauthenticated create
  refused; smoke printed the tested image id and repo digests.
- `MAISTRO_ENGINE_IMAGE=maistro-engine:test uv run pytest
  tests/test_engine_canvas_packaging.py` → 6 passed, 1 skipped (the skipped
  case is the full smoke, executed directly above).
- Regression direction proven on a Canvas-less artifact
  (`maistro-engine:nocanvas`, verified to fail the probe with
  `ModuleNotFoundError: No module named 'maistro_canvas'`):
  `MAISTRO_ENGINE_IMAGE=maistro-engine:nocanvas ...` →
  `test_built_engine_image_imports_the_canvas_store` FAILED with "the built
  engine image cannot import the Canvas store on its own contents — the
  #1825 omission is back" while the control-detection test still passed and
  this workspace has every package installed — the workspace cannot mask a
  Canvas-less artifact. An earlier stripped-Dockerfile build (image id
  `sha256:f7f47670a84f954d9b10b0cc6c2d1c72137e81085e028f8e66c73d577f7734f8`)
  had shown the same PASS/FAIL pair.
- Static gates on this head: `uv run ruff check .` and
  `uv run ruff format --check .` clean; `pytest
  tests/test_engine_canvas_packaging.py tests/test_distribution_contract.py`
  → 9 passed, 3 skipped; `scripts/check-suite-inventory.py --suite tests/`
  → ok (5511 nodes, matches the recorded inventory);
  `scripts/check-test-duplicates.py` → ok; `scripts/check-image-inventory.py`
  → OK. (`scripts/check-suite-inventory.py` without `--suite` reports 9
  pre-existing collection errors in `extensions/reference-greeter` and
  `packages/maistro-ext-harness` — `ModuleNotFoundError: No module named
  'maistro_ext_harness'` under the local dev sync, untouched by this
  branch's root-`tests/` change; CI runs the gate after a full workspace
  install.)

## CI-repair round (this head)

The first merge-queue evaluation of this branch failed four required gates
plus two advisory ones; each was reproduced locally, repaired at source, and
re-proven:

- `test` (and, by its meta-tests, the inventory gate): commit `cf69ba7ec`
  retargeted release.yml at the `-rc` quarantine reference but left
  `test_the_workflows_still_run_the_canvas_smoke` pinning the production
  name — `pytest tests/` → 3 failed (the packaging assertion above plus
  `tests/test_check_image_inventory.py`'s two real-tree cases). Assertion
  updated to the `-rc` reference; `pytest tests/ --ignore=tests/tools/registry`
  → 5280 passed, 138 skipped.
- Quality / Image inventory: `check-image-inventory.py` reads any step
  containing `imagetools create` as a promotion step; the proof step's
  *comment* said "Promotion is a byte-for-byte `imagetools create` re-tag",
  which placed a phantom promotion before the scans ("applies release tags
  before its scans"). The comment now describes the re-tag without the
  command literal and points at the step that performs it; gate → `OK: every
  Dockerfile is inventoried...`, both meta-tests green.
- SAST / Gitleaks: the smoke's `ROUTER_API_KEY` env assignment carries the
  ascending-digit placeholder (sixteen hex digits, twice) the inline ci.yml
  smoke carried for months; it is a fixture value, not a credential —
  recorded in `.gitleaksignore` scoped to the introducing commit `13e8d307`
  (path+rule+line; deliberately paraphrased here, since quoting the flagged
  line verbatim would make this note trip the same rule). Changed-range scan
  (`gitleaks git --log-opts=<merge-base>..HEAD`) → no leaks found; the
  history-wide `--all` arm's 13 findings are all from other unmerged lane
  branches (none is an ancestor of origin/develop; same pattern the ignore
  file already documents).
- devskim (advisory): code-scanning flagged DS137138 (http URL) and DS162092
  (loopback) on the smoke's two endpoint literals. The scheme/host are now
  split (`http_scheme`/`loopback` variables) — the repo's documented
  split-the-literal convention — with byte-identical values passed to the
  engine and curl. `shellcheck` on the script and `actionlint -shellcheck`
  over both touched workflows are clean.
- coverage (no services) red at this head is NOT this branch: all five
  publish-set suites pass locally with the exact CI commands and environment
  (core 15365 passed/1073 skipped, canvas 465/75, evolve 998, rsi 1624,
  bootstrap 233), and the same CI step fails on the lockfile-only boto3
  dependabot PR — an environmental failure elsewhere, not a regression here.

Re-validation on the repaired head: rebuilt `maistro-engine:test` from this
exact tree (image id `sha256:e908b5ef2fe029ecf1d76ac85b09a09c3146a63e8ff0eb
a282208dbc6a32dffd`) and re-ran the full smoke → PASS (import probe printed
`maistro-canvas 0.9.0 PgCanvasStore` on image contents only, control failed
as expected, design `0bd3fff5-df01-402a-9670-239541d2451c` created, read
back through `/v2/canvas`, verified in PostgreSQL); with
`MAISTRO_ENGINE_IMAGE=maistro-engine:test MAISTRO_ENGINE_IMAGE_SMOKE=1`,
`pytest tests/test_engine_canvas_packaging.py` → 7 passed (all three Docker
gated layers included, no skips); `ruff check`/`ruff format --check` clean;
`check-image-inventory.py`, `check-workflow-inventory.py`,
`check-workflow-write-safety.py`, `check-suite-inventory.py` all ok.

