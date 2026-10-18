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
  against the exact pushed `maistro-engine@<digest>` before signing it, so
  publication consumes the digest the Canvas proof tested.
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

Built the engine image from this tree (`maistro-engine:test`, image id
`sha256:f7f47670a84f954d9b10b0cc6c2d1c72137e81085e028f8e66c73d577f7734f8`)
and ran the full smoke against it: PASS (probe, control, boot, migration,
restart durability, authenticated create/read, PostgreSQL row, 401 refusal).
A canvas-less variant built from a stripped Dockerfile fails the probe test
with `ModuleNotFoundError: No module named 'maistro_canvas'` while the
control-detection test still passes — the regression the static and
artifact layers exist to catch. Suite: `tests/` 4508 → 4515 (+7); ruff check
and format clean.
