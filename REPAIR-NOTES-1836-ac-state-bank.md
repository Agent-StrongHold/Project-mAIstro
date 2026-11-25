# REPAIR-NOTES-1836 — acceptance-state bank repair (branch auto-1836 @ 2253d6385)

Assigned block: "commit status not successful", with the prior verify verdict
NEEDS-REPAIR naming one concrete defect:
`uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
f8a2df966a1d0db82be5fc08a571ed4750902c88` → rc=1, "FAIL: unbanked
improvement — design_coverage: 39.8641, floor still says 39.6633".

## Root cause (re-derived this round, not trusted)

- The branch note `quality/ac-state-notes/auto-1836.json` was last banked at
  `6864fc00b`, before the develop-sync merge `bb1a4df59487` raised the
  measured `design_coverage` from 39.6633 to 39.8641. The ratchet half of
  the required Quality / Acceptance-state gate fails on an unbanked
  improvement by design ("an unbanked improvement fails too so the ceiling
  cannot hold slack a later regression would spend", `.github/workflows/
  quality.yml` acceptance-state step comment).
- Reproduced at HEAD `2253d63854d2` this round: rc=1 with the identical
  message and fold listing (48 notes at base f8a2df966a1d), matching the
  prior verify round's two deterministic reproductions.

## Repair (exactly what the gate itself prescribes)

```
uv run python scripts/check-ac-state.py --run-tests --ratchet --bank
```

writes only `quality/ac-state-notes/<branch>.json`
(`scripts/check_ac_state_impl.py::_bank` → `ac_state_notes.write_note`).
Diff reviewed before commit: exactly one line
(`design_coverage` 39.6633 → 39.8641), no other file changed. No code,
spec, or test changed, so no suite-inventory delta applies. The banked
value equals the gate's own fresh measurement — this is exact banking, not
slack: the floor moves up, which only tightens future regressions.

## Evidence after the repair

- `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
  f8a2df966a1d0db82be5fc08a571ed4750902c88` (CI-exact PR path, from
  `quality.yml` "acceptance-state ratchet + mandate") → **rc 0**: "OK: 10
  debt counters sit exactly on their ceilings and 1 progress counter sits
  exactly on its floor (folded from 48 note(s) at f8a2df966a1d)"; acceptance
  mandate OK (0 criteria added or newly claimed, 0 unproven); chain mandate
  OK (0 absent links introduced).
- The `--run-tests` half executed the ~180 `@pytest.mark.ac` tests inside
  every invocation above (failing run, bank run, green re-run), all passing.
- Record drift corrected in place: `docs/testing/inventory-notes/
  verify-1836-bb1a4df59487.md` had claimed the mandate gate rc 0 at
  `bb1a4df59487`; it actually measured rc=1 there. The note now carries an
  explicit in-place correction pointing here rather than a silent rewrite.
- Owner acceptance of SPEC-101826 remains open by design (issue #1836 open,
  spec `status: Proposed`) — this repair changes nothing about that gate.
