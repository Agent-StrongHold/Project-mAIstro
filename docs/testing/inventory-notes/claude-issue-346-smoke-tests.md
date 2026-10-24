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

No tree changes were needed that round; that note was the only edit.

## Re-execution at the rebuilt head e39919e30 (2026-10-23) — image work green,
## lane-external splice damage blocks the boot battery

The lane history was rebuilt onto develop `4de7e906d` as a single commit.
All four shipped Dockerfiles changed relative to the last validated state
(digest-pinned bases, new install stages), so the build/smoke evidence above
does NOT transfer to this head. What was re-executed here:

- `scripts/check-image-inventory.py` -> OK: 9 Dockerfiles (2 PUBLISHED /
  4 DISTRIBUTED / 3 INTERNAL / 0 RETIRED), exit 0.
- `pytest tests/test_check_image_inventory.py --noconftest` -> 46/46 pass
  (develop's expanded suite; covers the `published_digest_verified: true`
  wiring claim against release.yml's single-build `-rc` quarantine ->
  scan -> `imagetools create` promotion -> cosign flow).
- `ruff check` + `ruff format --check` on the gate script and tests -> clean.
- ci.yml, security.yml, release.yml, quality.yml all parse as YAML; the
  three smoke/boot steps (ci.yml:1110 engine boot + #1825 Canvas proof,
  :1394 research, :1418 rsi-runner) are present; security.yml keeps the
  four Trivy + Grype + syft blocks; quality.yml wires
  `quality-image-inventory` (:1736-1775) into `quality-gate`.

Why the boot/smoke battery could NOT be re-executed at this head — the
rebuild splice is internally inconsistent, in increasing severity:

1. `uv.lock` was corrupted at e39919e30: the `asyncpg 0.31.0` entry carried
   `ast_serialize-0.11.1` sdist/wheel URLs (present in neither develop nor
   the previous lane head), plus a `typeshed-client` entry with a missing
   `source` field; `uv run` could not parse the lock at all. Repaired this
   round by restoring develop's `uv.lock` plus the four pyprojects the
   rebuild had reverted (root ruff `external` V105; maistro-core pydantic
   2.7.0 and pyjwt[crypto]>=2.14 CVE floors; maistro-canvas pillow>=13.0.0
   CVE floor; maistro-design pyyaml re-declaration). `uv lock --check`
   green afterwards.
2. `maistro-core` source is splice-broken: develop's `config/settings.py`
   imports `MAX_CIRCUIT_DOMAINS` from `security/resource_policy.py`, which
   the rebuild reverted to a version without it; restoring that file from
   develop still leaves `import maistro.config.settings` failing (pydantic
   `check_decorator_fields_exist` on `Settings._check_circuit_max_domains`).
   The engine image pip-installs this exact tree, so the #1825 Canvas boot
   proof cannot pass at this head — a tree problem, not a Dockerfile
   problem. NOT repaired further: deciding which side of each splice is
   authoritative is the deep-review question, not a lane edit.
3. `quality.yml` `quality-gate` `needs:` (and its `check_ci_job_results.py`
   argv) name `quality-proof-envelope`, `quality-model-proof`,
   `quality-credentials`, `quality-wiring` — none of which the rebuilt
   file defines — so the workflow fails at plan time on GitHub. The
   image-inventory/pins/workflow-inventory jobs ARE present.
4. The rebuild resurrected `alembic/versions/041_canonical_run_effect_claim.py`,
   `043_capability_invocation_effect_index.py`,
   `045_capability_invocation_logical_effect.py` (absent from develop);
   `tests/migrations/test_revision_metadata.py::test_migration_chain_has_one_head`
   FAILS at this head: the chain has more than one head.
5. Quality ledgers lost rows vs develop: `ratchet-authorizations.json`
   (-1370/+110), `durable-table-retention.json` (-636/+8),
   `branch-independence.json` deleted — per docs/quality-gates.md these
   merges are silent and will fail the ratchet gates at integration.

Round verdict: the #346 gate surface (inventory, tests, wiring, workflow
YAML, scan/SBOM/sign step presence) is green at this head, but the branch
is not integrable until the splice damage (items 2-5) is resolved by a
proper re-integration, after which the three Docker builds + smokes must be
re-run since all four Dockerfiles changed. The only #346-file edit this
round is this note; the lock/pyproject/resource_policy restorations are
recorded in the commit message.
