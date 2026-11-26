---
inventory-delta:
  tests/: +1
---

# #2304 — delete the withdrawn picomatch waiver from the npm audit gate

## Why

The `test` job's audit step
(`npm audit --json > /tmp/npm-audit.json || true` +
`python scripts/npm_audit_gate.py /tmp/npm-audit.json`) was red: the gate's
own two-way ratchet failed `GHSA-fc5q-39xc-vjpf` as a **stale waiver**.

- `https://api.github.com/advisories/GHSA-fc5q-39xc-vjpf` now reads
  `withdrawn_at: 2026-11-18T15:38:56Z` (summary prefixed "Withdrawn
  Advisory:"). npm's audit derives from that database and no longer reports
  it: `npm audit --json` at `packages/maistro-canvas/frontend` returns
  `metadata.vulnerabilities = {high: 0, critical: 0, total: 0}` (executed
  2026-11-25).
- The gate therefore printed
  `::error::npm audit waivers are stale — the advisories are no longer
  reported: GHSA-fc5q-39xc-vjpf — delete it from ALLOWED` and exited 1 —
  exactly what the ratchet in `scripts/npm_audit_gate.py` prescribes
  ("an `ALLOWED` entry whose advisory is no longer reported fails as
  stale").

## Change

- `scripts/npm_audit_gate.py`: `ALLOWED` is now `{}`. The rationale text
  for the deleted entry is preserved in the module comment/docstring with
  the withdrawal evidence, so the triage history is not lost. Nothing is
  relaxed: an empty allowlist blocks **every** high/critical advisory, and
  a waiver may only be re-added for a live unfixable advisory with a
  rationale specific enough to re-audit.
- `tests/test_npm_audit_gate.py`: tests that exercise "a waiver passes"
  now pass the waiver explicitly via `_run(..., allowed={...})` instead of
  depending on the shipped `ALLOWED` (which must stay empty). One new test,
  `test_the_withdrawn_picomatch_advisory_is_not_waived`, pins the shipped
  `ALLOWED` to `{}` so the withdrawn advisory can never be re-waived
  silently.

## Test delta

- `tests/` +1: `test_the_withdrawn_picomatch_advisory_is_not_waived`.
  All other `tests/test_npm_audit_gate.py` cases keep their node IDs
  (12 existing + 1 new = 13, `uv run pytest tests/test_npm_audit_gate.py`
  → 13 passed). No other suite moved.
