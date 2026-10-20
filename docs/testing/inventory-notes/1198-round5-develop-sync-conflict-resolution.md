# #1198 — round 5: develop-sync conflict resolution (bounded-output merge)

No suite-count delta: this round resolved a preserved merge conflict and
completed the develop sync; collection at the final HEAD matches the recorded
inventory exactly (no front-matter `inventory-delta` block, per the gate's
"no key records no delta" contract).

The previous attempt died on a provider timeout with an in-progress sync merge
preserved in the worktree: `6b631928b` (WIP #2164, bounded sandbox stdout/stderr
capture) half-merged into `auto-1198`, conflicting in
`packages/maistro-core/src/maistro/sandbox/backends/bubblewrap.py`. This round
resolved it in place and completed the sync.

## What was resolved

`bubblewrap.py` carried two conflict hunks; both sides are kept, neither
weakened:

- **Imports** — the #1198 host-path policy imports
  (`authorized_host_mounts`, `read_beneath`, `write_beneath` from
  `maistro.sandbox.paths`) stay, and `OUTPUT_LIMIT_EXIT_CODE` joins the
  protocol import.
- **`exec`** — the per-instance ownership lock (execution, host file transfer
  and teardown serialize on it) stays as the outer structure, and the #2164
  bounded `capture_process` body is adopted inside it, with
  `start_new_session=True` so `capture_process`'s process-group kill reaches
  the workload on timeout or output overflow. The plain `communicate()` path
  (unbounded buffering) is gone.

After the resolution commit (`828b1f178`), `origin/develop` (`eec7a5870`, the
round's stated base) merged clean: `080e358ba`.

## Gate evidence at final HEAD `080e358ba`

- `scripts/check-suite-inventory.py` (CI-exact: bare, ci.yml:676):
  `ok: 17 suite(s) match the recorded inventory` — no delta to record; the
  sync's test additions (`test_capture.py` +19 etc.) arrived with develop's own
  ledger rows.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (ci.yml quality.yml:1462 exact): 1322 reviewed
  identities -> 1322 findings, exit 0. No ledger amendment needed or made.
- `check-test-duplicates.py`, `check-ratchet-provenance.py`,
  `check-shipped-surface-truth.py`, `check-merge-markers.py`: all ok.
- `ruff check .` / `ruff format --check .`: clean.
- `mypy` (AGENTS canonical multi-src invocation): `Success: no issues found in
  902 source files`.
- `uv run pytest packages/maistro-core/tests -q`: **15400 passed, 1076
  skipped, 3 xfailed** (300s).

## Host-path boundary acceptance re-check (issue #1198)

- Positive authorization + canonicalization + symlink policy:
  `tests/sandbox/test_host_path_boundary.py` (denial parametrization covers
  `/`, `$HOME`, `/repo/.env`, `/var/run/docker.sock`, `/run/docker.sock`,
  `/etc/passwd`, `/tmp/../etc/passwd`; symlink-to-outside refused; symlinked
  parent allowed only when resolution stays inside).
- fd-relative/no-follow transfer and final-open swap race:
  `test_host_path_boundary.py::test_final_open_cannot_be_swapped_to_an_outside_target`,
  `...symlink_to_a_repo_secret`; conformance side
  `test_escape_conformance.py::test_host_side_file_transfer_keeps_symlinked_results_beneath_workdir`.
- Serialization/ownership: `...share_ownership_lock` plus the lock documented
  at `docs/security/SANDBOX-SUPPORT-MATRIX.md:170` and preserved in the merged
  `exec`.

## Environment note (not a branch defect)

`bwrap` 0.11.1 is installed here, but the Tier-3 probe reports
`Creating new namespace failed: Resource temporarily unavailable`. Bisected:
the same argv passes without the probe's `preexec_fn`; with it, any
`RLIMIT_NPROC` soft limit below ~2048 breaks namespace creation on this WSL
host (89 processes already run as this uid; `RLIMIT_AS`/`RLIMIT_FSIZE` do not
reproduce it). Live bubblewrap conformance therefore skip-with-reason here
(designed behavior) and runs on CI's ubuntu runners, which install bubblewrap
explicitly (ci.yml:596). Deliberately NOT "fixed" by weakening the rlimits.
