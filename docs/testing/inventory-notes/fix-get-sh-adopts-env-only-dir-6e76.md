---
inventory-delta:
  tests/: +16
---
# fix-get-sh-adopts-env-only-dir

Sixteen additions, none removed, all from running the Mac install on a real
Mac rather than reading it. Each defect below was found that way and each test
fails against `develop`'s version of the script it covers.

**`tests/test_get_sh_recovery.py` +10.** Two get.sh defects.

An unfinished install was unrecoverable: an earlier get.sh migrated the `.env`
into `$INSTALL_DIR` before cloning, so a failed clone left a directory that was
not a checkout, and every later run of the one-liner stopped at "exists but is
not a git checkout". The machine this was found on had exactly that directory
from July. Seven tests cover it: what counts as installer leftovers (a `.env`
and Finder's `.DS_Store`, nothing else), that user content is still refused,
that a real checkout is never mistaken for one, that recovery keeps the `.env`
at mode 0600 and leaves no staging directory, and that a failed clone touches
nothing.

The hand-off to install.sh died without a terminal: `[[ -r /dev/tty ]]` is
true on every macOS and Linux host because the node is world-readable, so the
redirect that followed failed with "Device not configured" under `exec`. That
is every non-interactive run of the one-liner -- cloud-init, ssh without `-t`,
CI. The test runs the hand-off in a new session, so there is genuinely no
controlling terminal. Gate C never caught it because it runs install.sh
directly and skips this hand-off.

**`tests/test_install_arm64_check.py` +6.** On Apple Silicon the installer
froze at "checking base images for native arm64 builds...". Docker Desktop's
`credsStore: desktop` helper blocks `docker manifest inspect` whenever it cannot
reach the keychain UI -- 8+ minutes with no output on the Mac this was found on,
7 seconds with the helper bypassed. The check also read a hardcoded image list
that had drifted (`pg17` against the stack's `pg18`), and when a lookup was
killed it told the user a native image "may be emulated". The tests pin: the
list comes from `compose config --images`; locally built images are skipped;
no lookup runs under the user's credential helper; a lookup that hangs is
abandoned and reported as unchecked, not as emulated; a genuinely amd64-only
image is still reported; the temporary config is removed.

**`tests/test_install_docker_sock.py` +0, one test corrected.**
`test_a_missing_docker_cli_is_a_no_op` inherited the real PATH, so on a Mac
with Docker Desktop it found the real `docker`, which reports the non-default
socket, and the "missing CLI" case became the "non-default socket" case. It
passed in CI only because the runner's docker uses the default socket. It now
removes every `docker` from PATH, which is what its docstring always claimed.
