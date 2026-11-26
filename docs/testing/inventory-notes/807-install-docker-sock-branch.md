---
inventory-delta:
  tests/: +7
---

# #807 the non-default Docker-socket branch is exercised end to end

`tests/test_install_docker_sock.py` (new file, 7 node IDs) closes the AC-3 gap
left by the `upsert_env` defect: Gate C's clean-install leg runs on Linux,
where `record_docker_sock` never leaves the default-`/var/run/docker.sock`
branch, and `release-installer.yml` runs `./install.sh` only on tags — so no
PR check executed the one branch that carried the undefined-function call, and
a supported macOS install (Colima's non-default socket) died with
`upsert_env: command not found` before any container started. A full macOS leg
in Gate C was rejected as the heavier of the two sanctioned options; the
issue's alternative — an equivalent test that explicitly exercises the
non-default branch — is implemented here instead, following the verbatim-lift
pattern of `tests/test_secret_env.py::TestTheRealShellPath` and
`tests/test_install_engine_floor.py`: `ensure_python`, `secret_env_run`,
`set_env_value` and `record_docker_sock` are sed-extracted from `install.sh`
and run under `set -euo pipefail` against a stub `docker` binary, writing a
real `.env` through `scripts/secret_env.py` in a tmp cwd.

Covered: the Colima-style non-default socket is recorded as
`MAISTRO_DOCKER_SOCK` (the regression case — pre-fix this harness exits 127
with `command not found` and writes nothing, verified against `install.sh` at
the defect head), the recorded file stays at 0600 under `umask 0000`, the
default socket records nothing and creates no `.env`, a `$DOCKER_HOST`
fallback after a context-less CLI is recorded the same way, a `tcp://`
endpoint warns without writing, a missing `docker` CLI is a no-op, and a
structural pin asserts the call site names `set_env_value` with no
`upsert_env` anywhere in `install.sh`.
