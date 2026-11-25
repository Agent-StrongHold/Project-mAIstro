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

## Executed discrimination evidence (develop-sync merge round, 2026-10-24)

The fail-before/pass-after claim was executed directly at merge head
4c6eb7f1c by installing each historical parser into `scripts/` and running the
six fork node IDs:

- Against the old single-pin-per-name parser (`pins[name] = ...`, last line
  wins, as at 4de7e906d9dc): **5 of 6 fail**, 1 passes — exactly as claimed;
  the survivor is `test_resolution_fork_any_locked_version_reconciles`
  (shipping the last fork's version reconciles under last-line-wins).
- Against the merge base f956a8142 (by-name *sets*, classification by NAME):
  **2 of 6 fail** — `test_required_name_with_conditional_alternate_is_missing_only_when_absent`
  (a name with one unconditional + one marked pin must gate presence; the
  name-keyed classification empties `required`) and develop's
  `..._still_names_an_unknown_branch` (its `(a or b)` clause suffix did not
  exist at the base). Both fixed parsers pass all six.
- The full file is green against the resolved script: 39 passed.
