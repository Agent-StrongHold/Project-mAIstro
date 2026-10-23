---
inventory-delta:
  workflows/ci.yml: 2 smoke steps rewritten (engine-research, rsi-runner)
---
# claude-issue-346-smoke-tests

Boot/smoke evidence for the `docker-build` job's research and RSI-runner
images (#346 "built, boot/smoke-tested as applicable").

## What the first version got wrong (found by building the images)

The originally added smoke steps never ran: both failed against locally
built images, so they would have been red required checks, not coverage.

- `maistro-engine-research`: `docker run ... chromium --version` — exit 127,
  `chromium: executable file not found in $PATH`. `python -m playwright
  install chromium` puts the browser under `PLAYWRIGHT_BROWSERS_PATH`
  (`/opt/playwright/chromium-*/chrome-linux*/chrome`), never on PATH.
- `maistro-rsi-runner`: `docker run ... python -c "import maistro_rsi"` —
  `ModuleNotFoundError`. `uv sync` installs the workspace into
  `/workspace/.venv`; the base image's `python` is the system interpreter.
  Even `/workspace/.venv/bin/python` fails because `maistro-rsi` is not a
  dependency of the root `maistro-workspace` meta-package — the shipped run
  contracts (`tools/run_rsi_isolated.sh`, `tools/run_rsi_evolve_isolated.sh`)
  import it from the source trees on `PYTHONPATH`.

## The corrected smokes (both executed against the built images, 2026-10-18)

- `maistro-engine-research`: resolves the Chromium path through Playwright
  (`p.chromium.executable_path`) and executes it with `--version`
  (`check=True`). Proves Playwright is installed, the browser it expects
  exists at the configured path, and the Chromium shared-library layer
  actually loads. Observed: `Google Chrome for Testing 156.0.8078.4`, exit 0.
- `maistro-rsi-runner`: mirrors the operator contract —
  `PYTHONPATH=packages/maistro-core/src:packages/maistro-evolve/src:packages/maistro-rsi/src:packages/maistro-bootstrap/src`
  plus `source /workspace/.venv/bin/activate`, then imports `maistro_rsi`
  and `maistro_evolve` (the `python -m maistro_rsi run|evolve` entries).
  Observed: `rsi runtime imports ok`, exit 0.

## Build evidence

`docker build -f Dockerfile.rsi-runner -t maistro-rsi-runner:ci .` and
`docker build -f Dockerfile.research -t maistro-engine-research:ci .` both
succeeded locally (BuildKit, docker 29.1.3) before the smokes ran; the
failed probes above were reproduced against exactly those images.

Validation: `actionlint` 1.7.7 + `shellcheck` 0.10.0 over ci.yml (the same
versions the workflow-lint job pins) pass; the `docker-build` step list was
re-parsed from YAML and executed verbatim.

## Independent re-execution (2026-10-20, verify attempt at 7c3f390a1)

A second attempt rebuilt all three images from the checked-out tree at head
`7c3f390a1` under fresh `:verify-346` tags (prior `:ci` tags left untouched)
and re-ran the evidence rather than trusting the round above:

- `docker build -f Dockerfile.research -t maistro-engine-research:verify-346 .`
  -> exit 0; research smoke verbatim -> `Google Chrome for Testing
  156.0.8078.4`, exit 0.
- `docker build -f Dockerfile.rsi-runner -t maistro-rsi-runner:verify-346 .`
  -> exit 0; rsi-runner smoke verbatim -> `rsi runtime imports ok`, exit 0.
- `docker build -f Dockerfile -t maistro-engine:verify-346 .` -> exit 0; the
  full `Boot the shipped engine image` step (extracted verbatim from ci.yml)
  executed against pgvector/pg18: liveness, readiness, alembic revision
  assertion and the second-boot recreated-cluster check all passed, exit 0.
- `shellcheck` 0.11.0 over the extracted boot script: clean. All three
  workflows parse as YAML; `scripts/check-image-inventory.py` OK (9
  Dockerfiles) and `tests/test_check_image_inventory.py` 24/24 pass.

No tree changes were needed this round; this note is the only edit.
