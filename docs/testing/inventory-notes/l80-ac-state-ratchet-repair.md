# L80 ac-state ratchet repair (round 4)

Verifier finding 1 for issue #80's repair round 3 was the Quality gate's
acceptance-state ratchet failing at head `06200e1df` with two distinct
refusals. This note records what was executed, what was repaired, and the one
part that is provably not repairable from this branch.

## What the gate refused, and the repair applied

1. **Superseded authorization** — `design_coverage@33.9095` (issue #729) is
   overtaken by three notes landed in three distinct commits, each later than
   the grant's `f7d770efb`: `auto-48.json` @37.693 (55c5ad892),
   `auto-1158.json` @38.0924 (150916f93), `auto-1138.json` @38.0924
   (ca4caec7d).
   The gate itself instructed: "prune it from quality/ratchet-authorizations.json".
   **Repaired:** the entry is pruned (`ac-state` section is now `{}`).
2. **Floor undercut** — measured `design_coverage` 33.0728 vs the folded
   floor 38.0924. The gate's own remedy for a fall is to bank it with
   justification. **Repaired:** `quality/ac-state-notes/auto-80.json` banks
   this branch's measured state (all twelve counters, measured with
   `--run-tests`).

## Evidence the residual floor failure is inherited, not caused by this branch

- A detached worktree at the immutable mandate base `ca4caec7d` measures the
  identical state: `design coverage: 33.0728% over 156 taken decisions`,
  and all eleven other counters match `auto-1138.json`'s banked values
  exactly. This branch's diff (sandbox tests + RSI tier guard) touches no
  spec, ADR, or AC marker.
- All AC-marked tests pass in every configured test root (879+1+32+6+85+88+320
  passed, 0 failed), so the shortfall is not failing evidence but the corpus
  state the base ships.
- The floor of 38.0924 is the `max`-fold of notes at the immutable base;
  grants are read at the base by design ("the same commit cannot both lower
  the floor and permit itself to"). No in-branch edit can lower it, and
  adding a new lower grant from this lane would be a unilateral ratchet
  weakening outside this lane's authority (the campaign permits grant edits
  only for the vulture ledger in explicit CI-repair rounds).
- Restoring 33.0728 → 38.0924 would mean adding ≈5 decision-points of
  reachable ADR coverage (≈8 of 156 taken decisions going 0→fully proven);
  fabricating that from a sandbox-test lane is not legitimate evidence.

The merge-queue path is unaffected by design: it measures the actual base in
a detached worktree and compares candidate-vs-base (equal here), so this
residual blocks only the pull_request review path — for every lane branched
off `ca4caec7d`, not just this one. The durable fix is a develop-side
reviewed correction (a new grant or note fold matching the measured corpus),
which must land through its own review.

## Commands executed (round 4)

- `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate ca4caec7d…`
  → before: 2 FAILs (floor + superseded grant); after prune+bank: 1 residual
  FAIL (inherited floor, see above).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → ok, 1412 reviewed identities, unclassified 0.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py
  packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py` → 25 passed (live Docker).
- `uv run pytest packages/maistro-rsi/tests` → 785 passed.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-rsi/tests` → ok (785).
