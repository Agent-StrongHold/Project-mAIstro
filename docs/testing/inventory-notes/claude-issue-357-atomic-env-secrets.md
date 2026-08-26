---
inventory-delta:
  tests/: +32
---
# claude-issue-357-atomic-env-secrets

Thirty-two new node IDs, all in `tests/test_secret_env.py`. Nothing removed or
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
