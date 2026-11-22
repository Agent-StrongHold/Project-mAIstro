---
inventory-delta:
  tests/: +24
---

# 354-wsl-default-distro-detection

## What moved

`tests/test_get_ps1_wsl_detection.py`: 24 node IDs in the root `tests/` suite —
13 parser cases (one per fixture under `tests/fixtures/wsl-list/`) + 10
install-path scenarios + 1 harness/pytest enumeration-drift guard, each
parametrized by case name, supervised through
`tests/installer/wsl_detection_harness.ps1`.

## Why

#354: `get.ps1` parsed `wsl -l -v` without handling the `* ` prefix on the
default distribution's row, so a machine with an existing, perfectly usable
default distro looked empty to the installer and was pushed into
`wsl --install` and the feature-enable reboot loop. The fix (same PR) adds:

- machine-readable preference: `wsl --list --json` is probed and used when the
  installed WSL provides a shape we can map; anything unmapped falls back;
- a structural text-table parser (`ConvertTo-WslDistroRows`) that normalizes
  the UTF-16LE/OEM-decode encoding (NUL stripping, BOM), the `* ` default
  marker, whitespace, and skips localized headers/banners by structure
  (a data row ends in the WSL version `1`/`2`; headers do not), never by
  header text;
- exact case-insensitive name matching (the old `-like "$Name*"` also let a
  request for `Ubuntu` match `Ubuntu-24.04`);
- adoption: when the default distro name is requested (no explicit `-Distro`)
  and an existing usable WSL2 default exists, it is used instead of
  installing; an explicit `-Distro` is always preserved, including across the
  elevation relaunch and post-reboot resume (`Get-PassthroughArgs`).

## The tests

Parser fixtures (real captured `wsl -l -v` variants, each parsed plain and
re-encoded through OEM codepage 437 — the lossy form Windows PowerShell 5.1
actually sees): default marker + second distro (CRLF, blank header line),
single WSL1 stopped default, multiple-with-no-default, docker-desktop trio,
German/French/Japanese/Chinese localized headers, non-ASCII multi-word
imported name, installing state, English and localized no-distro banners,
empty output. Scenarios (scripted `wsl.exe` at the process boundary, real
`get.ps1`): existing-default-usable (the #354 regression — verified to fail
against the pre-fix script), rerun-twice-idempotent (definition of done),
existing-nondefault-usable, adopt-existing-default, explicit-distro-preserved,
fresh-install-no-distros, install-stuck-reboots (the one legitimate reboot),
json-table-preferred, json-unmapped-falls-back, exact-name-match.

## Windows E2E

`windows-detection-e2e` job (release-installer.yml, windows-latest) runs
`tests/installer/run-wsl-detection-e2e.ps1` under both Windows PowerShell 5.1
and PowerShell 7 — the same 23 cases, enumerated from the harness itself.
A real WSL2 install is not hermetic on hosted runners, so `wsl.exe` is
scripted at the process boundary; the script-under-test, its UTF-16LE pipe
encoding, and both interpreters are real. The full in-distro WSL2 leg remains
the SPEC-072726-3439 follow-up.

## Evidence

- `uv run pytest tests/test_get_ps1_wsl_detection.py -q` → 24 passed (pwsh 7.4.6).
- Harness against `git show HEAD:get.ps1`: `existing-default-usable` fails
  ("existing default distro was not used") — the reported bug, caught.
- Same suite pre/post: `tests/test_installer_repository.py` 22 passed.
