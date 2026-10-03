# Repair #116 @ dad6bc865 (branch auto-116) — 2026-10-03

## Verdict basis: vulture gate is proven branch-side unpassable; everything else green

Round 2 outcome. Round 1 (job 081061a65556) concluded "branch-side impossible,
no commit"; the driver rejected that and ordered "fix what is genuinely dead +
amend the ledger". This round re-derived everything from primary evidence. The
ordered repair is **not executable branch-side**; the proof chain is below so
the next decision does not re-derive it.

### The single red gate

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (CI-exact,
quality.yml:960-965) exits 1 at dad6bc865:

- `core-public-api-surface: 3 NEW identities vs TRUSTED base` —
  `promotion.py:385 attach_effect`, `:414 mark_reversed`, `:645 promote`.
- Plus 1 informational stale row vs base (`auth/resources.py::POLICY`, removed
  debt — never fails the gate).
- The candidate ledger already banks exactly those 3 identities
  (`quality/vulture-baseline.json`, core-public-api-surface, appended by
  ddc9c308c); candidate_deltas are empty, so ledger bookkeeping is exact.

### Proof chain: no branch-side action can turn it green

1. `_enforce_trusted` (scripts/check-vulture-baseline.py:305-364) fails only on
   `unauthorized = trusted_added − grants`. `trusted` is the baseline at the
   merge base cf4a562b (= origin/develop), which contains 0 promotion.py rows
   (the contract is new on this branch).
2. `load_authorizations` (scripts/ratchet_provenance.py:478-504) reads grants
   **from the base revision only**; its docstring states the doctrine: "a new
   grant does not take effect in the change that introduces it" — two merges.
3. origin/develop is unmoved at cf4a562b (`git fetch` + `git log
   cf4a562b..origin/develop` empty, 2026-10-03), so no grant exists at base.
4. Ledger-only amendment cannot pass: adding is a no-op (rows already banked);
   removing creates `candidate_added` failures. exit 0 requires the 3 findings
   gone from the scan itself.
5. Removing the methods would break the issue's own acceptance criteria — the
   AC-6 test (test_promotion_contract.py:299-320) exercises all three methods;
   AC-1 pins `promote` as the only appending path; AC-3 pins reversal
   metadata. They are tested contract surface, not dead code.
6. Wiring a production family through the contract (the other elimination
   path) is recorded as deferred follow-up by the accepted
   ADR-100126-a9c4: "the ledger is a value object until a store adopts it",
   "adoption per family is tracked in the spec's ACs", rewiring is "migration
   work, not contract definition". SPEC-100126-a9c4's family table marks
   Record adoption = follow-up for all six families. Template activation stays
   family-owned (`promote_audited`) by the same ADR, so there is no sanctioned
   adoption call-site on this branch.

### The two real resolutions (above this lane)

- **(a) Land the reviewed grant on develop first** (two-merge doctrine), then
  merge develop into auto-116. Gate passes with the identities retained as
  reviewed debt; matches repo doctrine and the SPEC's follow-up. A grant
  committed on this branch CANNOT authorize itself — base-only read.
- **(b) Authorize deviating from ADR-100126-a9c4's follow-up scoping** and
  fund a real family adoption (record minting beside `promote_audited`).
  Feature work: needs evaluation-Run evidence the template family does not
  have today, and trips promotion-surface closure, radon, and inventory
  ledgers.

### Executed evidence at dad6bc865 (round 2, all re-run fresh)

- `pytest packages/maistro-core/tests/governance/test_promotion_contract.py`
  → 32 passed; one class per AC (AC-1..AC-7) plus reversal-decision and
  fence-edges classes; tests pin structure (frozen records, v3-not-v2 after
  rollback, fragment matching, empty-evidence refusal), not timing.
- `pytest .../test_template_store.py .../test_node_template_store.py` →
  113 passed, 58 skipped (DB-dependent), AC-7 one-approval-type holds.
- `ruff check .` / `ruff format --check .` → clean (2835 files).
- `check-ac-state.py` → exit 0; `check-suite-inventory.py` → 14/14 suites;
  `check-promotion-surface.py` → ok; `check-reachability.py` → exit 0 (1223
  modules, 173 unreachable); `check-reachability-dispositions.py` → OK (49
  groups cover 173); `check-radon-baseline.py` → 145 == 145.
- Worktree left clean at dad6bc865; only artifact added is this note.
