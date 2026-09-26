# auto-147 CI gate repair, round two

Repairs the two findings the verifier recorded at head
`35acad344cb06bbcdda7f1d22704046f61e3724b`, against live CI evidence pulled
read-only from PR #1291's check rollup (run 36226696153, job 108362003603).

## Finding 1 — trailing whitespace

`docs/testing/inventory-notes/auto-147-merge-pause-wakers.md:29` carried a
trailing space after `test_parked_status_follows_the_executor`, so
`git diff --check ca4caec7..HEAD` exited 2. Removed the space; the check now
exits 0 against both the base and HEAD.

## Finding 2 — "Quality gate (Pillars 1–4, 7, 8)" FAILURE

The only red check on the PR. Its log ends with the acceptance-state ratchet's
own remedy, verbatim:

```
FAIL: authorized floor(s) independent landings have superseded
  - design_coverage: 3 note(s) already clear it on their own:
      auto-1138.json
      auto-1158.json
      auto-48.json
A correction this durably overtaken is no longer what holds the floor up; prune it
from quality/ratchet-authorizations.json.
```

Pruned exactly that one entry — `ac-state: design_coverage@33.9095` (#729) —
from `quality/ratchet-authorizations.json`. The section held nothing else and
is now absent, which `_validated_grant_records(None)` reads as "no grants".

This is candidate bookkeeping the gate itself demands, not a new
authorization: the grant lowered nothing (the base fold sits above it), and
every comparison already excluded it via `superseded_by_floor`, which is
computed at the base precisely so the pruning run cannot loosen its own
bound. Verified by reproducing the gate's grant-decision block at
`ca4caec7d3193fb786e41d9ae3c6ccf94ac15304` against the pruned working tree:

- `superseded_by_present` — the exact failing predicate — is now `{}`;
- `_removed_binding_grants` returns `[]` (a superseded counter is exempt);
- the base fold for `design_coverage` still exceeds 33.9095, so the floor the
  notes hold is unchanged by the prune.

No tests were added or removed in this round; the inventory totals are
unchanged (maistro-core 11136, hive-conductor backend 2814, both gates ok).

## Validation battery at this head

- `git diff --check ca4caec7d3193fb786e41d9ae3c6ccf94ac15304` — exit 0
- `uv run ruff check .` / `uv run ruff format --check .` — clean
- focused delegation battery (7 files) — 195 passed
- `test_agent_delegate_remote.py` + `test_container_node_composition.py` —
  19 passed (the loud missing-dependency refusals live here)
- `scripts/check-suite-inventory.py` for both suites — ok
- `scripts/check-wiring-reads.py` — ledger matches
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60` —
  exit 0 (1412 reviewed -> 1411 findings)

CI re-verification of the remote rollup remains with the integrator; this
worker does not push.
