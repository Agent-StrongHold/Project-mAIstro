# auto-26 repair handoff (2026-10-03, HEAD 6cf90fa63)

## What this round fixed (the four red CI gates at ed5667d79)

1. **exact-debt-ledger (vulture)** — passes at HEAD: `1359 reviewed identities -> 1359`
   with CI's exact args. Root cause at the old head was an under-merged develop;
   this round merged origin/develop (5765efce8) and verified all three
   quality ledgers row-identical to develop afterwards.
2. **Coverage gate** — `retrieval/expand.py` was at 77.3% changed branch arcs
   (floor 80). Three tests now pin the named arcs (non-string completion
   content; non-string/blank/duplicate expansion terms; fence loop that
   exhausts without an array). Gate: `ok` at 90% lines / 80% branches per file.
3. **Quality gate** — the develop merge widened `check-radon-baseline.py`'s
   scan to all packages, exposing four new unbaselined C-blocks in this
   branch's registry code. Grants cannot authorize in the same PR (ratchet
   provenance reads from the merge base), so the blocks were refactored to
   rank B: `cmd_search`, `load_corpus`, `load_golden`, `evaluate` — behavior
   preserved (eval still MRR 1.0000/recall 1.0000/nDCG 0.9709 on the then-20
   queries; all 63 tests pass). All ~20 other quality-gate script steps pass;
   mypy --strict, pyright 21/21, formal 663, fitness 23 verified earlier at
   this merge state.
4. **test job** — prior red was the direct model egress (fixed by the earlier
   governed-egress repair; `check-model-egress.py` passes: 23 direct callers,
   no expansion). Registry suite 63/63, suite inventory 63 recorded, citation
   status gate passes.

## Acceptance-coverage repairs (issue #26's named cases)

- New tests: renamed source with stable id (fingerprint still moves),
  superseded decision retrieved with `[Superseded]` provenance, duplicate
  identity keeping both claimants addressable; fingerprint test gained the
  removal leg. Golden set grew 20 → 24 (supersession pair both directions,
  linked-AC query via SPEC-256's AC heading stream, one declared no-answer
  case contributing 0). Re-measured: MRR 0.9583 / recall 0.9583 / nDCG 0.930,
  floor 0.90 held. README now carries the measured per-variant comparison
  (filter neutral, enrichment +0.021 MRR, expansion candidates −0.27 MRR)
  and latency/cost.

## Residual

- `check-ac-state.py --ratchet --mandate` (quality-gate step) needs
  PostgreSQL; the Docker engine was unreachable from this session (Windows
  Desktop backend down; 3 start attempts). Exposure nil: the branch adds no
  AC-marked tests and no ac-state notes; CI runs this step with a real PG.
- Local pyright count (21) matches baseline only with `uv sync --locked
  --all-extras` + pip-installed pyright 1.1.414, mirroring CI's steps.
