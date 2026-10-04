---
inventory-delta:
  packages/maistro-core/tests: +21
  tests/: +17
---

# 407 compose v2 floor

Issue #407 drops the unsupported Docker Compose v1 fallback and preflights a
minimum Compose v2 in both reachable compose-driving installers:

- `install.sh`: `detect_compose_cmd` no longer falls back to the legacy
  `docker-compose` (or `podman-compose`) binaries; a new
  `ensure_compose_supported` gate in `start_engine` (after `compose_files`
  resolved the exact file set `up` will use) requires
  `MIN_COMPOSE_VERSION="2.17.0"`, and feature-probes the front-end with
  `compose config --quiet` against the real stack files when the version
  string is missing or unparseable. Refusals carry platform-specific upgrade
  instructions (macOS / WSL2 / Linux).
- `maistro upgrade` (`packages/maistro-core/src/maistro/cli/_upgrade.py`):
  `_resolve_compose_runtime` lost its `["docker-compose"]` branch, and
  `preflight()` now runs `_compose_support_error` — same two gates (version
  floor, schema-parse feature probe) — for every install type that drives
  compose (`git`, `tag`, `archive`, `container`; `package` never touches
  compose and is skipped). A below-floor or schema-incompatible front-end
  aborts with `Preflight failed ... No changes were made` before any phase
  moves the source tree.

## Test deltas

- `tests/`: new `tests/test_install_compose_floor.py` (+17 collected node
  IDs), modeled on `tests/test_install_engine_floor.py`: the real functions
  are lifted verbatim out of `install.sh` and driven against a stub `docker`
  binary — v1/below-floor rejections with upgrade instructions, supported
  versions at/above the floor, feature-detection on unparseable version
  strings (including surfacing the compose error so a missing .env variable
  is distinguishable from a v1-generation engine's schema gap),
  platform-specific instruction checks, the no-v1-fallback behavior of
  `detect_compose_cmd`, and the `start_engine` ordering (gate after
  `compose_files`, before `up`).
- `packages/maistro-core/tests` (+21): `test_compose_runtime_resolution` now
  pins that a docker-compose-only host resolves to the default v2 front-end
  (the v1 expectation is gone), plus new unit tests for
  `_parse_compose_version` and `_compose_support_error` (below-floor refusal
  with platform hint, at/above-floor acceptance, unparseable-version feature
  probe both ways, per-platform upgrade hints, absent front-end left to
  phase-time errors) and a preflight integration test proving a below-floor
  compose aborts before any phase command runs. The fail-all recorder in
  `test_failure_aborts_without_false_success` now answers the probe with a
  supported version so the test keeps pinning the phase-failure → rollback
  boundary (a fail-all front-end is now a clean preflight refusal, asserted
  by the new integration test).

No existing node IDs were removed or renamed; the one removed parametrize
case (`docker-compose → docker-compose` selection) is replaced by its
no-fallback inverse within the same test.
