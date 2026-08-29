---
inventory-delta:
  tests/: +53
---
# claude-issue-357-atomic-env-secrets

Fifty-three new node IDs, all in `tests/test_secret_env.py`. Nothing removed or
reparametrised.

## The window, measured

`install.sh` wrote every generated credential and then narrowed the file:

    cat > "$ENV_FILE" <<EOF
    MAISTRO_ACCESS_TOKEN=${token}
    ...
    EOF
    chmod 600 "$ENV_FILE"

Measured on this machine under `umask 0022`:

| Step | Mode |
|---|---|
| after `cat >`, token already written | **644** |
| after `chmod 600` | 600 |

Under `umask 0000` the first row is **666**. Every process able to read the
directory can read the token, the database password, the LiteLLM key and both
Langfuse secrets for the duration of that window — and a crash inside it leaves
them that way permanently.

Three more paths had the same shape: `append_env_once`'s `printf >>` (creates
under the umask when the file is absent), the three Python heredocs' `write_text`
(same), and `get.sh`'s `cp` of a legacy `.env` followed by `chmod 600 … || true`.

## `test_no_observer_ever_sees_a_wider_mode` is the assertion that matters

"It ends up 0600" was **already true** of the broken code, so asserting the final
mode would have discriminated nothing. What the fix actually changes is that no
observer can ever see anything wider.

So the test runs a watcher thread sampling the path throughout a series of
writes and asserts every observed mode is already 0600. Checked against the old
`cat >`-then-`chmod` shape under `umask 0000`: **5 215 samples, `0o666` observed**
— the test fails on the old code, which is the only evidence that it means
anything.

`test_the_temp_file_is_never_wide_either` extends it to the temp file, which
holds the same secrets for as long as it exists.

## Why refusing beats repairing

`validate_target` rejects a symlink, a foreign owner, extra hard links, and an
already-readable mode rather than `chmod`-ing them into shape. Each means
something other than the installer holds the path, and narrowing the mode does
not take that handle away.

The hard-link case is the clearest and has its own test: the second name refers
to the *same inode*, so its holder reads whatever is written there no matter
what mode the first name carries. `chmod` would look like a fix and be none.

`test_a_safe_existing_file_is_accepted` is the counterweight — a 0600 file owned
by the caller with one link is the ordinary re-run, and refusing it would break
every second install.

## Interruption

The issue asks for interrupts before, during and after the write.
`TestInterruption` covers all three, and the "during" case is the reason updates
go through a temp file rather than truncating in place: an interrupted truncate
leaves a `.env` missing whichever keys came after it, so the stack starts with a
partial configuration instead of failing.

`test_an_interrupted_update_leaves_no_temp_file_behind` covers the other half —
a leftover temp file is a second copy of every secret sitting in a directory the
user believes holds one.

## `TestTheInstallersUseIt`

A helper nothing calls fixes nothing; this is the same shape as #419's guards,
which needed tests at their call sites rather than on the module. These four
read `install.sh` and `get.sh` directly and assert no `chmod 600` after a write,
no `cat > "$ENV_FILE"`, no `>> "$ENV_FILE"`, and no `cp` of the legacy file.

## Windows

`get.ps1` never writes `.env`. It resolves a WSL distro and runs `get.sh` inside
it, so the POSIX path above *is* the Windows path, and there is no second
implementation to keep in step. Stated here because "define equivalent Windows
behavior" is in the DoD and the honest answer is that the behaviour is shared
rather than mirrored.


## The last eighteen came from the diff-coverage gate

The first thirty-two covered the security property and left the CLI dispatch,
several refusal branches and the JSON edge cases untested — 87.2% against a 90%
floor. Worth recording *which* code that was, because it is not incidental:

`install.sh` and `get.sh` reach this module **only** through its command line, so
the dispatch in `main()` is production code on the installer's critical path, not
a convenience wrapper. `TestTheCommandLine` drives every subcommand, and
`test_it_runs_as_a_subprocess_the_way_the_installer_calls_it` runs the file as a
script — the only case that proves the `__main__` guard and the executable bit
actually work, which is exactly how the installer invokes it.

`test_create_on_an_existing_file_exits_3` pins the distinct exit code, so `get.sh`
can tell "already there" from "unsafe" and report accurately instead of
collapsing both into one failure.

`test_a_directory_that_cannot_be_fsynced_is_not_fatal` records a deliberate
tolerance: some filesystems refuse `fsync` on a directory handle, the replace is
still atomic, and only durability across a power loss is weaker — not worth
failing an install over.

`test_a_file_owned_by_someone_else_is_refused` moves the *caller* rather than the
file, because the suite does not run as root and cannot `chown`. The comment in it
records why the obvious `lambda: os.getuid() + 1` recurses: `secret_env.os` is the
same module object as `os`, so the patch would call itself.


## No PR check runs a line of the installer

`.github/workflows/release-installer.yml` does run `./install.sh --answers-file
docs/install/examples/answers-v1-smoke.yaml`, which is what makes
`scripts/secret_env.py` reachable in principle. But its triggers are:

    on:
      workflow_dispatch:
      push:
        tags: ["v*"]

So a change to `install.sh` or `get.sh` is not executed by anything on a pull
request. Every other test in this file drives the Python helper, which proves
the helper and not the shell that calls it — a rewiring mistake in `install.sh`
would have reached a release before anything noticed.

`TestTheRealShellPath` closes that. It `sed`s the eight env-writing functions out
of the real `install.sh`, sources them, and runs them in a temp directory under
`umask 0000` — asserting the mode after every one of `create`, `append_env_once`,
`set_env_value`, `fill_env_value` and `ensure_api_keys_contains`, and that the
three functions which used to be Python heredocs kept their replace / append /
fill-if-blank semantics.

Discrimination, measured: with `install.sh` and `get.sh` restored from
`origin/develop` and everything else left in place, **all seven** of
`TestTheRealShellPath` and `TestTheInstallersUseIt` fail — the mode assertion on
0600, and `verify_env_file: command not found` for the function that does not
exist there yet. With the fix, all seven pass.
