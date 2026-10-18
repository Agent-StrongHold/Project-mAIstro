---
inventory-delta:
  tests/: +21
---
# 1821-bootstrap-runtime

Twenty-one cases in `tests/test_bootstrap_runtime.py`, one for each behavior the
#1821 bootstrap contract promises, driven through the real
`scripts/bootstrap-runtime.sh` with stub `python3`/`uv`/`curl` executables on a
fully controlled `PATH`/`HOME`.

What each cluster pins:

- `TestEnsureUv` (9): uv on `PATH` is reused without downloading; uv installed
  but outside this shell's `PATH` is adopted from the known user-owned
  locations instead of duplicated; a host with no uv at all bootstraps through
  the official standalone installer into `~/.local/bin` (asserted user-owned by
  uid) and is usable immediately in the same process; a failed download names
  the URL, stops cleanly, leaves nothing behind, and a retry against a
  recovered network succeeds; an unwritable destination fails with the
  installer's error and nothing else modified; the rc-file PATH block is the
  installer's own idempotent default, skippable via
  `MAISTRO_UV_NO_MODIFY_PATH=1`, and a NEW shell finds uv through it alone;
  version pin and explicit mirror URL select the installer actually
  downloaded; and a TERM delivered while the child installer is still running
  stops the whole run non-zero with an actionable message — the interrupted
  run never adopts the installer's eventual success (bash defers traps behind
  a foreground child, which is why the installer runs under `wait`).
- `TestEnsurePython` (5) and `TestHelperVersusPackageFloors` (2): a 3.11
  interpreter satisfies the helper floor without uv being consulted; a 3.10
  host falls through to uv provisioning the package floor; a machine with
  neither Python nor uv reaches a working runtime in one process (the #1821
  headline path); a failed provisioning fails with the reason; a PEP 668
  externally-managed interpreter without pip is accepted as the helper and
  provably never asked to pip (the stub records every pip attempt); and a uv
  resolution that lies about its version is caught by executing the resolved
  interpreter — the helper floor and the package floor are validated
  separately, and the package floor is pinned to
  `packages/maistro-bootstrap/pyproject.toml` so the two cannot drift.
- `TestNoPipAnywhere` (2): no entrypoint or the library may contain `pip
  install`, `--break-system-packages`, `sudo pip`, or module-style `-m uv`;
  `get.sh`'s one pre-init Python consumer (legacy `.env` migration) goes
  through the contract, with no bare `python3`/`python` left anywhere in it.
- `TestLegacyEnvMigration` (3): the real `migrate_legacy_install` extracted
  from `get.sh` migrates a legacy `.env` through the contract on a host with no
  usable system Python (0600 preserved, real `scripts/secret_env.py` runs);
  resolution failure happens before the first mutation, leaving the legacy file
  byte-identical and no destination created; and a compatible host interpreter
  is used without touching uv at all.

The stubs are behavior fixtures, not mocks of Python objects: each test bakes
the exact version, install state, and exit codes its scenario needs, and the
fixture uv installer models the properties the official astral.sh installer
documents (user-owned destination, marked idempotent rc block,
`INSTALLER_NO_MODIFY_PATH` passthrough). The other touched files only re-point
existing harnesses at the moved definition: `ensure_python` left `install.sh`
for the shared library, so the compose-override, docker-sock, mnemonic, and
secret-env harnesses source it and no longer lift a private copy.

The offline gap these tests cannot close — a real download from astral.sh — was
proved once on this machine outside the suite: a restricted-`PATH` account with
no `python3`, no `pip`, no `uv` and a fresh `HOME` ran the real contract against
the real installer — uv 0.13.1 landed uid-owned in `~/.local/bin`, uv provisioned
cpython-3.15.0 (floor-probed, immediately usable in the same process), a fresh
login shell resolved uv through the installer's `.profile` → `~/.local/bin/env`
block, and re-sourcing stayed idempotent. The same run surfaced the official
installer's real userland prerequisites (`cat`, `awk`, `tar`, `gzip`, `mv`),
which the per-platform promise in `docs/install/default-installer.md` now names.
Remaining unverifiable here: macOS/Windows hardware runs of the same proof,
which stay with the release checklist's platform smoke tests.
