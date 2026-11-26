---
inventory-delta:
  tests/: +3
---
# Playwright harness npm-pin parity (#2444 CI repair)

Three new tests in `tests/test_playwright_harness_version_parity.py` hold the
e2e harness's `@playwright/test` npm pin (and the repo-side
`packages/hive-conductor/tests/e2e/package.json` + `package-lock.json`
annotations) to the exact version of the digest-pinned
`mcr.microsoft.com/playwright` base image.

## The regression this closes

The raw dependabot head of #2444 bumped only the Dockerfile's FROM line
(`v1.64.1-noble` -> `v1.65.1-noble`) and left the build-time npm pin at
`@playwright/test@1.64.1`. The image version and the npm client version are
not independent pins: playwright-core 1.64.1 resolves browsers.json to
chromium-1248 / firefox-1555 / webkit-2370, while the v1.65.1-noble image
ships chromium-1255 / chromium_headless_shell-1255 / firefox-1572 /
webkit-2388, so every browser launch inside hive-conductor-e2e-ui failed with
"Executable doesn't exist". That failure mode (plus the unregistered digest)
is what red-handedly turned six required checks on the raw dependabot head:
Quality / Image pins, Quality gate (Pillars), Coverage gate and `test` (both
via `tests/test_check_image_pins.py::test_dunder_main_entrypoint_runs_the_real_gate`
running the real gate against the tree), hive-conductor-e2e-ui, and
integration-scope (aggregator waiting on e2e-ui).

## What the tests assert

- `test_dockerfile_npm_pin_equals_the_base_image_version` — the npm pin in
  the Dockerfile's install equals the `vX.Y.Z` in the FROM line.
- `test_e2e_package_manifest_equals_the_harness_pin` — the e2e
  `package.json` dependency declares the same version.
- `test_e2e_lockfile_equals_the_harness_pin` — the e2e `package-lock.json`
  installs the same version.

All three parse the shipped tree only; no registry access, no Docker. The
first test fails byte-for-byte on the pre-fix dependabot state (image 1.65.1,
npm 1.64.1) — verified before the fix was applied to the tree by evaluating
the same parses against `git show 5fdf73fe:packages/hive-conductor/tests/Dockerfile.playwright`
(image `1.65.1`, pin `1.64.1` → mismatch asserted).

## Count

`tests/` +3 (one new file, three node IDs, no parametrization).
