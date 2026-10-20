---
inventory-delta:
  tests/: +22
---

# auto-409 — unattended answers-file parity for get.ps1 (+22 node tests)

Issue #409: at this base, Unix `get.sh` forwarded `--answers-file` to
install.sh while `get.ps1` exposed only boolean switches, so Windows could not
express the same unattended install. The fix gives get.ps1 an `-AnswersFile`
parameter (preflight validation before any mutation, Windows→WSL path
translation, `bash -s -- --answers-file` forwarding through the get.sh
handoff, survival across the elevation relaunch and reboot resume) and gives
install.sh a preflight guard for the `--answers-file` + skip-wizard conflict
and missing/directory answers paths, reported as one complete error list
before any mutation. One versioned schema (`InstallAnswersV1`,
`schema_version: "1"`) is consumed by both entrypoints; it carries names and
flags only, so secrets stay out of argv and command history (the secure
channel — a staged 0600 credentials file referenced by
`MAISTRO_BOOTSTRAP_CREDENTIALS_FILE` — is path-translated and forwarded by
environment variable, never as an argument).

All +22 are in the new `tests/test_answers_parity_contract.py`, which runs the
same fixture (`docs/install/examples/answers-v1-smoke.yaml`) through every
reachable leg and compares the rendered effective config:

- **+4 Unix entrypoint leg** (real bash, fake install.sh echoing argv):
  get.sh forwards `--answers-file` with relative paths resolved to absolute
  (space-free, `=` form, absolute-untouched, and the pre-existing
  unrecognized-option passthrough unchanged).
- **+4 install.sh preflight leg** (real bash, failure paths only): every
  problem reported in one failure (missing file + skip-wizard conflict),
  directory answers path, no false positives when only one problem exists,
  and the environment-variable form (`MAISTRO_INSTALL_ANSWERS` +
  `MAISTRO_SKIP_WIZARD`) guarded identically.
- **+1 rendered effective config** (real `uv run maistro-install --json`):
  the smoke fixture renders the pinned answers plan (schema v1, source_build,
  no_crypto, bootstrap_admin, ...).
- **+13 Windows-supervised legs** (pytest supervises
  `tests/installer/answers_parity_harness.ps1`, skipped where pwsh is absent
  and run for both shipping editions by the new
  `run-answers-parity-e2e.ps1` steps in release-installer.yml's
  windows-detection-e2e job): 6 unit cases (path translation incl. UNC
  rejection, POSIX single-quoting, four preflight verdicts), 2 handoff cases
  (plain run keeps the bare `| bash` pipe; the answers run forwards
  `bash -s -- --answers-file '<wsl-path>'` and `-AnswersFile` survives
  `Get-PassthroughArgs`), 3 blocked cases (real get.ps1 child process exits 1
  before any mutation with the complete problem list and no false positives),
  the harness/pytest case-list pin, and the cross-platform contract itself:
  the path get.ps1 forwards is the same fixture the Unix entrypoint forwards,
  and rendering it produces the identical effective config.

Regression-checked against the parent commits: every answers-specific case
fails against the base get.ps1 (no `-AnswersFile` surface) and the base
install.sh (no guard); the plain-pipe handoff case passes on both by design.
