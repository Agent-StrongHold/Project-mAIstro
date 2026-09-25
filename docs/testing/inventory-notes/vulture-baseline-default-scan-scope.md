---
inventory-delta:
  tests/: +1
---

# Vulture gate default scan scope (#446 repair)

The #446 verification battery reported
`RATCHET_BASE_REV=<base> uv run python scripts/check-vulture-baseline.py` as
failing with "1426 findings versus 1413 reviewed identities and unbanked
candidate ledger deltas". Reproduction showed this was an invocation-scope
mismatch, not new dead-code debt on the branch:

- The script's no-argument default scanned `packages tests --exclude */.venv/*`.
- CI (`vulture-ratchet.yml`, `quality.yml`) and `docs/quality-gates.md` invoke
  the gate as `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`,
  and the reviewed ledger in `quality/vulture-baseline.json` is banked against
  exactly that scope.
- The broad default swept hive-conductor's `backend/` layout and collected
  tests — surfaces no reviewed rule covers — so every bare run failed on 400+
  phantom identities while CI stayed green. The trusted base revision
  (`ba2f1f07`) fails identically under the old default, confirming the branch
  introduced no vulture debt: the CI-shaped invocation reports
  1413 -> 1413 with zero deltas and exits 0 at the branch head.

## Change

- `scripts/check-vulture-baseline.py`: the no-argument default now reproduces
  the CI scope exactly (glob expanded in-process, because Vulture rejects an
  unexpanded glob as a literal path). Explicit argv is unchanged.
- `scripts/run-quality-scans.sh`: the advisory vulture invocations moved from
  the stale `packages tests` scope to the CI scope, so the advisory line can
  actually be green instead of warning forever.
- `tests/test_check_vulture_baseline.py::test_default_scan_reproduces_ci_scope`
  pins the default to the CI scope so the divergence cannot return silently.

## Evidence

- `RATCHET_BASE_REV=ba2f1f077fd2790c704101ea5435cbb4c2ba78b0 uv run python
  scripts/check-vulture-baseline.py` -> exit 0 (1413 reviewed identities ->
  1413 findings, no deltas).
- `uv run pytest tests/test_check_vulture_baseline.py -q` green.
