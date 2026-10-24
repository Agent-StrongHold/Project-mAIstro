---
inventory-delta:
  tests/: +6
---

# Resolution-fork acceptance in the image-lock reconciliation gate (L1836 CI repair)

The security.yml `containers` job failed at "Reconcile installed packages to
uv.lock" (run 40093845270): `beartype==0.22.9 (image) != beartype==0.23.1`. The
image was right — it installs from `uv export --locked --require-hashes` on its
own Python 3.13, and the branch's lock (post `uv lock --upgrade-package
fastmcp --upgrade-package setuptools`) forks beartype: 0.22.9 for
`python_full_version < '3.15'`, 0.23.1 for `>= '3.15'`. The gate's
`parse_expected` kept one pin per name in a dict, so the last fork line
overwrote the first and the image's correct fork read as a version skew.

Six node IDs, all in `tests/test_check_image_lock_reconciliation.py`, against
`scripts/check-image-lock-reconciliation.py`. Five of the six fail against the
old parser and pass against the fixed one (the sixth — shipping the *last*
fork's version — already passed and pins the other fork direction);
fail-before/pass-after recorded in the round notes.

**+2** parse-level: a forked export keeps *every* locked version of a name
(both conditional, required empty) and classifies unconditional vs conditional
versions **by line** when a name carries one of each.

**+4** verdict-level through `main()` with the faked docker dump: the image
shipping the non-last fork (0.22.9) reconciles — the exact regression — as
does the other fork (0.23.1); a version no fork locked is still one red
mismatch naming every locked version (`!= beartype==0.22.9 or
beartype==0.23.1`), never a missing+extra pair; and a name with an
unconditional pin plus a marked alternate gates presence only (shipping the
alternate reconciles, shipping nothing is a missing pin).

Existing behavior is pinned unchanged by the 28 pre-existing tests, which pass
unmodified: single-version names still skew red on any version drift, and
marker-conditional pins still gate nothing when absent. Diff coverage of the
changed script measured with CI's own producer shape (`coverage run --branch
--source=scripts` over the suite, then `check-diff-coverage.py --base
4de7e906d9dc`): 100% lines / 100% branches on the changed file.
