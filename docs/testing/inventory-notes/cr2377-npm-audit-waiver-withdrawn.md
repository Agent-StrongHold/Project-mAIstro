---
inventory-delta:
  tests/: +1
---

# cr-2377 — the picomatch audit waiver went stale; the two-way ratchet removed it

## What happened

Running the `test` job's audit leg with CI's exact commands at this branch's
head (develop tip `6a1ef1c` merged in, canvas frontend untouched):

```
npm audit --json > /tmp/npm-audit.json || true     # packages/maistro-canvas/frontend
python scripts/npm_audit_gate.py /tmp/npm-audit.json
```

exited 1 with `npm audit waivers are stale — the advisories are no longer
reported: GHSA-fc5q-39xc-vjpf`. The report itself is empty
(`metadata.vulnerabilities.total: 0`) even though the lock still pins
picomatch 4.0.7 — the newest release (`npm view picomatch version` → 4.0.7).

## Why it is a stale waiver, not a gate defect

`https://api.github.com/advisories/GHSA-fc5q-39xc-vjpf` shows
`withdrawn_at: 2026-11-18T15:38:56Z` (summary now reads "Withdrawn Advisory:
picomatch vulnerable to ReDoS …"). npm's audit consumes the same advisory
database, so the advisory stopped being reported hours after
`scripts/npm_audit_gate.py` landed on develop (ba7d378ef7, 2026-11-18
07:16Z). The gate's own two-way ratchet — "an `ALLOWED` entry whose advisory
is no longer reported fails as stale" — then fails the `test` job on every
tree, including develop tip and this PR's merge ref, until the waiver is
deleted. Deleting a waiver is a strict tightening, mandated by the gate it
self-documents (`Delete this waiver the moment the audit report stops listing
the advisory.`).

This is develop-borne, not branch-borne: the branch's diff vs develop tip
touches no lock file and no gate script beyond this repair.

## The repair

- `scripts/npm_audit_gate.py`: `ALLOWED` ships empty, with the withdrawal
  recorded in its comment; the docstring and the blocking-advisory hint
  reworded to past tense (the retired waiver's shape is in git history).
- `.github/workflows/ci.yml`: the audit step's comment updated to the current
  no-waiver state. The step itself is unchanged.
- `tests/test_npm_audit_gate.py`: the two tests that pinned the shipped
  waiver now inject their own allowlist (the fixtures were already
  `allowed=`-parameterized), and one new test pins the shipped state —
  `ALLOWED == {}` — so any future waiver is a conscious edit of that test,
  not a quiet dict append.

## Inventory delta

`tests/: +1` — the new shipped-state pin in `tests/test_npm_audit_gate.py`;
the two reworked tests keep their count.
