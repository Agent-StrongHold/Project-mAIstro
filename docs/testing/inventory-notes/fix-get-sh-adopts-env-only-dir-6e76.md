---
inventory-delta:
  tests/: +23
---
# fix-get-sh-adopts-env-only-dir

Twenty-three additions, none removed, all from installing on a real Apple
Silicon Mac rather than reading the scripts. Every defect below was found that
way, and every new test fails against `develop`'s version of the script it
covers. The end state: a full install on that Mac, from a recovered
`.env`-only directory, with no terminal, came up with the engine and Conductor
healthy and auth enforced.

**`tests/test_get_sh_recovery.py` +10.** An unfinished install was
unrecoverable -- an earlier get.sh migrated the `.env` before cloning, so a
failed clone left a directory that was not a checkout and every later run
stopped at "exists but is not a git checkout". The Mac this was found on had
exactly that directory from July. Seven tests cover adoption: what counts as
installer leftovers, that user content is still refused, that a checkout is
never mistaken for one, that the `.env` keeps mode 0600, that nothing is left
staged, and that a failed clone touches nothing. The rest cover the hand-off to
install.sh with no controlling terminal: `[[ -r /dev/tty ]]` is true on every
host, so the redirect after it failed with "Device not configured" under
`exec` -- every cloud-init and non-interactive ssh run. Gate C never saw it,
because it runs install.sh directly.

**`tests/test_install_arm64_check.py` +7.** The Apple Silicon image check froze
the installer: `docker manifest inspect` ran under Docker Desktop's
`credsStore: desktop` helper, which blocks when it cannot reach the keychain.
It also read a drifted hardcoded list (`pg17` against the stack's `pg18`) and
reported killed lookups as "may be emulated". The seventh test is the
regression this branch nearly shipped: under install.sh's `set -euo pipefail`,
the first draft of the timeout returned 143 from `wait` on its own watcher and
ended the install on a *successful* check. The harness now runs with the same
options as the script.

**`tests/test_install_credential_helper.py` +6.** The same helper hangs every
pull and build, not just manifest lookups: a real install sat 14 minutes at
"load metadata for docker.io/library/python" with docker-buildx's only child a
`docker-credential-desktop get` that never returned. It ignores SIGTERM and
SIGALRM. A bounded probe now fails the install in seconds with what to do; the
tests cover a hang, a helper that traps TERM and ALRM, a healthy helper, a
helper that errors fast (not a hang), no configured store, and a configured
helper that is not installed.

**Two existing tests corrected, count unchanged.**
`test_a_missing_docker_cli_is_a_no_op` inherited the real PATH, so on a Mac it
found real docker and tested the non-default-socket case instead.
`test_start_engine_enforces_the_floor_before_first_daemon_use` pinned three
adjacent lines; it now pins the order it was about -- the floor check directly
after the runtime check and before every step that uses the daemon.

All new tests also pass under `/bin/bash` 3.2, which is what `curl ... | bash`
runs on a stock Mac without Homebrew. Two harnesses use `eval "$(...)"` rather
than `source <(...)`, which bash 3.2 silently reads as empty.
