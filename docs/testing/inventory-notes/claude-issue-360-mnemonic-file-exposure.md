---
inventory-delta:
  tests/: +40
---
# claude-issue-360-mnemonic-file-exposure

Forty new node IDs. Twenty in `tests/test_secret_env.py` (`reserve` and
`purge`, and their CLI), twenty in a new
`tests/test_install_mnemonic_handling.py`. Nothing removed or reparametrised.

## What the phrase is

`bootstrap_first_run` POSTs the staged credentials to `/v1/setup/complete` and
receives, **once**, the 24-word BIP39 phrase that roots the deployment's crypto
identity (ADR-021 signing). If the vault was not initialised, that response is
the *only* copy — the installer says so, in those words, right above the prompt
that waits for the operator to write it down.

So the file it lands in is the most sensitive artifact the installer ever
touches, and it was the least carefully handled.

## Three defects, in the order they bite

### It landed world-readable

`curl -o` supplies a mode only when it **creates** the file, and then under the
caller's umask — 0644 on a typical system. Every user on the box could read the
identity root from the instant it arrived until the cleanup ran.

`secret_env.reserve` makes the path an empty 0600 file first. curl then opens
an *existing* file, and `O_WRONLY|O_CREAT|O_TRUNC` does not widen an existing
file's mode — `test_a_writer_that_truncates_keeps_the_narrow_mode` pins that
property directly, because the whole approach rests on it.

`reserve` purges a leftover rather than failing on it. `create_exclusive`'s
`O_EXCL` is right for a file this process is the sole author of and wrong here:
the leftover is *itself* the secret, so refusing to proceed would preserve
exactly the file we want gone, and would then fail on every retry from then on.

### An interrupt left it on disk

`install.sh` had **no `trap` at all**. The step immediately after the phrase is
printed is a `read` loop that blocks until the operator types `yes` — which is
the point of it. So the interruption case is not exotic; it is the one the
design invites, with the file at its most interesting.

An INT/TERM/EXIT trap now purges the response file. It is cleared before the
function returns, for two separate reasons that `test_the_traps_are_cleared_
before_the_function_returns` records: a live INT trap would hijack Ctrl-C for
the remainder of the install, and a live EXIT trap would purge a path this
function no longer owns.

`$creds` is deliberately **not** in the trap. A pre-commit failure keeps the
staged credentials for retry — that is the existing contract, stated to the
operator on that branch, and `test_the_trap_does_not_purge_the_staged_
credentials` keeps this change from quietly breaking it.

### `shred_file` was strictly worse than `rm`

    size="$(wc -c < "$f")"
    head -c "$size" /dev/zero > "$f"

The `>` truncates at redirection setup, **before** `head` writes a byte. The
original blocks return to the allocator first, so the zeros land wherever the
filesystem next chooses — quite possibly nowhere near the secret. And if that
write failed or was interrupted, the file was left truncated and never
overwritten, while the caller printed `shredded` regardless.

`purge()` opens the descriptor without `O_TRUNC`.
`test_it_does_not_truncate_before_overwriting` asserts on the descriptor flags
rather than on an outcome, because the outcome is exactly the thing a
filesystem is free to vary — an outcome assertion here would be a test that
passes for reasons it does not state.

It also refuses a symlink or a file it does not own, rather than zeroing
whatever is on the other end. A cleanup step that follows a symlink is a way to
make the installer destroy a file of someone else's choosing.

## What is deliberately still true

`purge` is **not** secure erasure, and the AC does not ask it to be — it asks
the installer not to *claim* it is. On a journaling, copy-on-write or
compressing filesystem, and on any SSD with wear levelling, the original blocks
can survive untouched. The operator text now says what was done, states that
residual risk, and names the thing that actually addresses it: full-disk
encryption and key destruction.

`test_it_names_something_the_operator_can_actually_do` exists because a warning
with no action attached is a warning people learn to skip, which makes it worse
than none.

## `validate_target_for_purge` is not `validate_target`

It drops one check: the mode. `validate_target` refuses a world-readable file,
correctly — writing *more* secrets into one compounds the exposure. Purging is
the opposite case. An exposed file is the one most worth removing, and refusing
it because it is exposed would leave it exactly where it is. Every other
refusal is retained, because they are all about writing to the wrong inode
rather than about how wide this one is.

## Discrimination, measured

Against `develop`'s real `install.sh` and `scripts/secret_env.py`, restored
with `git checkout origin/develop --`: **35 of the 40 fail**, across all three
defect classes.

The five that pass on both are invariants rather than regressions —
`bootstrap-credentials.json` was already 0600, the secret is already passed by
path rather than in argv, and the retry contract already held. They are here so
this change cannot break them, not because it fixed them.

## Why a shell-level suite

`release-installer.yml` triggers on tags and `workflow_dispatch` only, so **no
PR check executes a line of `install.sh`**. Every other test here drives the
Python helper, which proves the helper and not the shell that calls it.
`tests/test_install_mnemonic_handling.py` sources the real functions out of
`install.sh` with `sed` and runs them, so a rewiring mistake fails a PR check
rather than a release. Same instrument #357 established, one file over.

`test_an_interrupted_run_leaves_no_readable_phrase` goes through bash's own
signal handling rather than reading the source, because "the trap text looks
right" and "the file is gone after a SIGINT" are different claims.

## Two findings this PR's own tests made

`test_it_no_longer_says_shredded` caught an operator string on the 409 branch
that the first pass missed, and the shell harness surfaced that `ensure_python`
announces itself on the stream an assertion was reading. Both are recorded
because they are the argument for the harness existing.
