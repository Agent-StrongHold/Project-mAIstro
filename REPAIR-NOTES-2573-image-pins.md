# CR-2573 repair — register the re-serialized python:3.15.2-slim-bookworm index in image-pins

Branch: `dependabot/docker/templates/autonoetic/python-498829c`, head `4fca98be08d1`
(dependabot's own commit, sole diff: `templates/autonoetic/Dockerfile.jinja`, both
`FROM` pins `96599df8…` -> `498829c717b…`). Base: `24d410ce0d6e` (develop).

## Diagnosis

The named red CI gate was `Quality / Image pins` (`quality.yml` job
`quality-image-pins`, exact invocation `uv run python scripts/check-image-pins.py`).
Reproduced locally at the starting head, exit 1, both violation directions:

1. `python:3.15.2-slim-bookworm@sha256:498829c717b…` — pinned digest not registered
   in `quality/image-pins.json` (used by `templates/autonoetic/Dockerfile.jinja`);
2. `…@sha256:96599df822d0…` — `used_by` drift: registry named
   `[templates/autonoetic/Dockerfile.jinja, packages/hive-conductor/Dockerfile]`,
   the tree (post-bump) uses `[packages/hive-conductor/Dockerfile]`.

Cause: Dependabot bumped only the template's digest. Docker Hub re-serialized the
`3.15.2-slim-bookworm` tag's OCI index on 2026-11-24, so the mutable tag now
resolves past the 2026-11-20 pin, while `packages/hive-conductor/Dockerfile:246`
(runtime-apt stage, `#2304`) legitimately still pins the original index. The
Dockerfile's own header says it: "Refresh both pins and quality/image-pins.json
together."

## Fix (same shape as the #2414 golang:1.27.3-alpine re-serialized-index repair)

`quality/image-pins.json`: split row 4 into two rows sharing the tag —

- `96599df8…` keeps `recorded 2026-11-20 / recorded_in #2443`, `used_by` narrowed
  to `packages/hive-conductor/Dockerfile`, note rewritten to its actual role
  (Conductor runtime-apt OS/security-patch layer) plus the #2573 split story;
- new row `498829c7…`, `recorded 2026-11-28 / recorded_in #2573`,
  `used_by: [templates/autonoetic/Dockerfile.jinja]`, carrying the full
  template-base contract text from the old row.

The gate rejects duplicate `(image, digest)` rows but tolerates two rows sharing a
tag (verified in `scripts/check-image-pins.py::check_registration`; precedent rows
`golang:1.27.3-alpine` b8c9b82…/fa3d596… coexisted between #1152/#2414/#2375).

## Live registry verification (2026-11-28, this machine)

- `docker buildx imagetools inspect python:3.15.2-slim-bookworm` -> OCI index
  `sha256:498829c717b1e59fc42f0e7865eafe4e04ca0f70a3769d4ae70ba218df54507c`
  (linux/amd64 child `1ec2babe…`, annotated `org.opencontainers.image.version
  3.15.2-slim-bookworm`, base `debian:bookworm-slim` @ `311f7a19…`, created
  2026-11-24, upstream revision `f4c67ece…` 3.15/slim-bookworm) — exactly the new pin.
- `docker run --rm python:3.15.2-slim-bookworm@sha256:498829c717b… python --version`
  -> `Python 3.15.2`.
- `docker buildx imagetools inspect python@sha256:96599df8…` -> still resolves, the
  same index as recorded (amd64 child `6cae5760…`, created 2026-11-05, base
  `debian:bookworm-slim` @ `c67e92c8…`) — the Conductor stage's pin stays live; the
  re-serialization moved only the OS base (`c67e92c8…` -> `311f7a19…`) on the same
  python revision, i.e. a pure security-base refresh, not an interpreter move.

## Gate battery (all green after the fix)

| Check (CI's args where applicable) | Result |
|---|---|
| `uv run python scripts/check-image-pins.py` (quality.yml:2382) | exit 0 — 12 pins across 11 Dockerfiles, all registered |
| `uv run pytest tests/test_check_image_pins.py tests/test_pinned_digest_references.py tests/test_distribution_contract.py -q` | 55 passed |
| `uv run pytest tests/test_root_image_interpreter_lines.py -q` | 2 passed |
| `uv run pytest tests/templates/ -q` (autonoetic render contract) | 9 passed |
| `uv run python scripts/check-image-inventory.py` | OK — 10 Dockerfiles inventoried |
| `uv run python scripts/check-build-context.py` | ok |
| `uv run python scripts/check-image-pins.py --base-digests Dockerfile packages/hive-conductor/Dockerfile` | lists registered pins incl. the Conductor `3.15.2@96599df8…` |
| `uv run ruff check .` | All checks passed! |

Driver's deterministic checks (job dir `check-0/1/2.log`: `uv sync --locked --extra
dev`, `ruff check .`, `ruff format --check .`) were already green; this round's only
tree change is the ledger split above. No Python behavior changed and no tests were
added, so no `docs/testing/inventory-notes/` delta is required.
