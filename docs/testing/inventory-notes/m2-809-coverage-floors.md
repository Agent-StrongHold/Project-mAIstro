---
inventory-delta:
  packages/maistro-bootstrap/tests: +6
---

# m2-809-coverage-floors

The m2/809 branch (#992) landed its credential-hardening tests one gate short:
the per-file diff-coverage floor failed on the two source files the change
touched — `cli.py` 0% of its one changed line (the "already staged" skip now
keyed on `staged_credentials_valid`), and `credentials.py` 77.8% of its 18
changed branch arcs (need 80%), partial at the not-a-regular-file raise, the
`S_ISREG` recheck, and the two `os.name != "nt"` guards.

These six nodes close those named gaps; none touch source behavior. In
`test_credentials.py`: a directory planted at the staged path is refused by
both entry points; an inode swapped to non-regular between `is_file()` and the
stat recheck reads as wreckage (the race the recheck exists for, simulated by
intercepting `Path.stat`'s symlink-following looks); and the two Windows arcs —
validity skipping the POSIX mode/nlink checks, staging skipping `fchmod` —
pinned from POSIX with `os.name` faked and `Path` pinned to `PosixPath`, since
`Path(...)` picks its flavour from `os.name` and a real `WindowsPath` render
breaks the rename. In `test_cli.py`: a validly staged file skips the prompts
without rewriting the staging, and with nothing staged and no TTY the run
defers to the UI Setup wizard — the first tests `_maybe_stage_bootstrap_credentials`
has ever had.
