# Issue #768 repair round — vulture: CI gate green; default-args red is trunk drift

No test counts moved and no ledger line was amended in this round, so there
is no `inventory-delta` block. This note records the executed evidence for
the prior verification finding: *"uv run python scripts/check-vulture-baseline.py
exited 1: unclassified packages/hive-conductor/frontend/node_modules/flatted/python/flatted.py:136"*.

## Executed at this round's tree (head before the repair commit, same content)

1. **CI-canonical invocation** (`.github/workflows/quality.yml:823`,
   `vulture-ratchet.yml:82` — job `exact-debt-ledger`, which is **green on
   the pushed PR head `0d68a75e3272` per the GitHub check-runs API**):

   ```
   uv run python scripts/check-vulture-baseline.py \
     packages/*/src --min-confidence 60 --exclude '*/third_party/*'
   ```

   **exit 0** — `1412 reviewed identities -> 1411 findings`, `unclassified: 0`,
   `never_allowlist: 0`, no candidate/trusted deltas. The branch's only
   ledger edit (pruning the `types.py::unused variable 'SVG'` identity that
   the branch's format gate made reachable) was already correctly committed
   before this round — the "remove identities your fix eliminated" duty.

2. **Default-args invocation** (`packages tests --exclude */.venv/*`):
   **exit 1**, with exactly one unclassified identity —
   `frontend/node_modules/flatted/python/flatted.py:136` — and nothing else.
   `node_modules/` is a gitignored npm install tree (0 tracked files) that
   CI checkouts never contain; the npm `flatted` package happens to ship a
   Python port that vulture reads when a developer machine has run
   `npm ci`. The same class of local-only default-scope red is documented
   twice before:

   - `auto-1058-vulture-invocation.md` — the default scope was never banked
     green on any recent commit and fails even at the develop base and tip;
     the correct owner is a dedicated trunk reconciliation (bank the
     default scope or narrow the script's default to the CI contract), not
     a feature lane. Re-banking it here would also be a self-serving
     ledger rewrite the checker itself forbids ("land a reviewed grant
     first" — authorizations are read from the base revision by design).
   - `768-independent-verification-37fced681.md` — same environmental
     finding classified non-blocking with CI `exact-debt-ledger` green.

## Why this round amends nothing

The two-merge rule (`scripts/ratchet_provenance.py`) reads grants from the
base revision, so a grant added in this branch cannot take effect in it,
and the trusted baseline at the merge base has no `node_modules` rule —
a candidate-only rule cannot turn the default invocation green either.
Amending the ledger for an identity that exists only in untracked
install trees would add unreviewable noise to the per-identity ledger for
zero CI effect. The CI gate — the contract this ratchet enforces — passes
at this head with no amendment needed.
