# Repair #116 @ e34a1d751 (branch auto-116) — 2026-10-03, round 3

Round 3 (driver job 5c141c9dc460) re-executed the ordered repair — "fix what
is genuinely dead + amend the ledger for reviewed retained identities" —
against fresh evidence at e34a1d751 and confirmed it is **not executable
branch-side**. Every step below re-run or re-read from primary evidence this
round; none of it is inherited from round 2.

- Gate reproduced with CI-exact args (quality.yml:960-965): `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → **exit 1**; exactly the 3 promotion.py
  identities unauthorized vs trusted base (plus the informational stale
  POLICY row, which never fails the gate). Candidate ledger banks exactly
  those 3 rows (quality/vulture-baseline.json:1301-1303), so the ordered
  amendment is a no-op and removing them would newly fail `candidate_added`
  (enforced at scripts/check-vulture-baseline.py:347-356).
- Not genuinely dead: promotion.py:645 `promote` is docstring-pinned "The only
  promotion path"; `attach_effect`/`mark_reversed` carry the AC-6 traceability
  and AC-3 reversal semantics. Test classes AC1–AC6 exercise all three.
- Grants read from base only: scripts/ratchet_provenance.py:478-504
  (`load_authorizations` docstring: "a new grant does not take effect in the
  change that introduces it"). `git diff cf4a562b HEAD --
  quality/ratchet-authorizations.json` is empty; base grants contain 0
  promotion.py rows; `git fetch` → origin/develop still cf4a562b (0 new
  commits).
- Adoption deferral re-read from the Accepted ADR/SPEC: ADR-100126-a9c4
  (status: Accepted, ADR-INDEX.md:221) — "Families that have not adopted the
  ledger yet are not in violation", rewiring is "migration work, not contract
  definition, recorded as follow-up"; SPEC-100126-a9c4:195-206 family table
  marks Record adoption = follow-up for all six families.
- Suppression (noqa-style) rejected as gate weakening: it would route
  retained surface around the grant review, exactly the self-approval path
  ratchet_provenance.py exists to close. Not done.

Everything else re-verified green at e34a1d751 (fresh runs): ruff check /
format --check clean (2835 files); test_promotion_contract.py 32 passed;
template stores (graph/test_template_store.py + graph/test_node_template_store.py)
113 passed, 58 DB-skipped; check-ac-state --run-tests --ratchet --mandate
cf4a562b exit 0; check-suite-inventory 14/14; check-promotion-surface ok;
check-reachability 1223 modules/173 unreachable + dispositions OK; radon
145 == 145; mypy packages/maistro-core/src shows only the 5 pre-existing
maistro_bootstrap import-stub errors (cli/_builders_tui.py:160-163,
cli/_install.py:20 — files untouched by this PR).

The resolution is unchanged and above this lane: (a) land the reviewed grant
on develop, then merge develop here; or (b) fund the ADR-deviating family
adoption as scoped feature work. Neither is reachable from this worktree.

---

# Round 2 record @ dad6bc865 — 2026-10-03

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

## Round 4 (develop sync to 1e4933e2a1): ac-state resolved DB-side; vulture blocker unchanged

- **Merged origin/develop (1e4933e2a1) into auto-116** (round's designated base;
  merge-base was cf4a562b before). Git auto-resolved `quality/*.json` with no
  conflict — audited by hand per the AGENTS.md silent-row-loss warning:
  vulture-baseline = branch 1357 − develop's 10 paid rows = 1347 rows; the 3
  promotion.py rows survived; the stale POLICY row did not return. radon took
  develop's 11/11 rewrite; reachability ledgers stayed branch-side.
- **Vulture gate on the merged tree** (CI-exact args): trusted baseline now
  folds at 1e4933e2a1 (1345 identities, base-only grants per
  ratchet_provenance.py:478-504); candidate bookkeeping exact (no candidate
  deltas). Exit 1 solely on the same 3 unauthorized identities
  (promotion.py:385 attach_effect / :414 mark_reversed / :645 promote,
  core-public-api-surface). Develop's ratchet-authorizations.json is
  byte-identical to cf4a562b's and promotion.py does not exist on develop, so
  no develop-side caller or grant can exist: the two-merge blocker is
  unchanged by the sync.
- **check-ac-state initially failed on the merged tree**: design_coverage
  37.3775 < floor 41.1539. Root cause = measurement environment, not the
  merge: the floor was recorded DB-up, and without MAISTRO_TEST_PG_DSN the
  durable-store AC legs skip — `ac_outcome_plugin` counts a skip as
  not-passing (quality.yml:632-639), collapsing coverage. Re-measured with the
  CI-equivalent stack (pgvector/pgvector:pg18, alembic upgrade head, both DSN
  env vars): **coverage 42.1466 ≥ 41.1539**; the delta then failed as
  "unbanked improvement" and was banked per the gate's own instruction as
  `quality/ac-state-notes/auto-116.json` (measured_with_tests: true). Gate
  **exit 0** with `--run-tests --ratchet --bank --mandate 1e4933e2a1`.
- **mypy --strict packages/maistro-core/src: SUCCESS (686 files, 0 errors)**
  after `uv sync --extra bootstrap`. The "5 pre-existing maistro_bootstrap
  import-stub errors" reported in rounds 1–3 were a missing-extra artifact in
  the worktree venv, not a repository defect.
- Promotion contract tests re-verified on the merged tree: 145 passed / 58
  DB-skipped; ruff check + format clean (2858 files); suite-inventory 14/14;
  promotion-surface ok; reachability exit 0 (1233 modules / 173 unreachable);
  radon 145 == 145.
- **Remaining blocker (unchanged, above this lane):** the vulture grant must
  land on develop first (two merges), or the ADR-deviating family adoption is
  funded as scoped work.

---

# Round 5 @ 7d30dee6d8 (merge of origin/develop c0441cf94b) — 2026-10-03

Synced the branch to this round's designated develop base **c0441cf94b**
(clean auto-merge, commit 7d30dee6d8). Per AGENTS.md the quality/*.json
auto-merges were audited by hand: vulture ledger = develop@c0441cf9 + the 3
promotion.py rows − the stale POLICY row (1345 rows; develop's c0441cf94 had
already dropped the duplicate `entry_id` pair, and the merged scan no longer
produces them — candidate bookkeeping came out EXACT with nothing to prune);
radon took develop's 6-line edit; reachability ledgers branch-side.

Full battery re-run fresh on the merged tree (head 7d30dee6d8):

- **vulture (CI-exact args)**: exit 1, base now c0441cf94b9a — trusted
  1343 → scan 1345, sole failure the same 3 unauthorized identities
  (promotion.py:385 `attach_effect`, :414 `mark_reversed`, :645 `promote`);
  candidate ledger exact (no bookkeeping section). Grants at c0441cf94b still
  contain 0 promotion.py rows (61 vulture entries, verified against the ref),
  so the two-merge blocker is unchanged. The gate's own message says it:
  "land a reviewed grant first."
- **ac-state** `--run-tests --ratchet --mandate c0441cf94b9a8...`: **exit 0**
  on a fresh migrated pgvector/pgvector:pg18 (alembic 001→051, 58 upgrades);
  design coverage 42.1466 == the banked note; 7 criteria added, 0 unproven;
  chain mandate OK.
- Template stores with live PG legs (MAISTRO_REQUIRE_PG_LEGS=1):
  **170 passed, 1 skipped** (vs 113/58 DB-skipped without the DSN) — AC-7's
  shared PromotionApproval proven against real Postgres.
- test_promotion_contract.py: 32 passed (AC1–AC7 classes + reversal + fences).
- ruff check/format: clean (2849 files). mypy core: 0 errors (696 files).
- suite-inventory (develop's rewritten script): 14/14, exit 0; NEW develop
  gate check-test-duplicates.py: exit 0. promotion-surface: ok. radon:
  145 == 145 at base c0441cf94b. reachability: 1245 modules, 173 unreachable,
  exit 0.

Verdict unchanged after five rounds of primary evidence: the ONLY red item is
the vulture authorization, which by design (ratchet_provenance.py:478-504,
base-only grant read) must land on develop before this branch can pass it.
Branch-side options are exhausted: the identities are tested AC-pinned
contract surface (not dead), the ledger banks them exactly, and ADR-100126
-a9c4 scopes family adoption as follow-up. Resolution is above this lane:
land the reviewed grant on develop, then merge develop here.

Operational note: an early alembic invocation this round reported success
against a DB that was not the intended one (no ambient DB_* vars found); the
authoritative runs above all used a dedicated fresh container on :55116
(pg-acstate-116-r5, migrated 001→051 in one observed transaction). Other
lanes' scratch DBs observed at 051/052 — forward migrations only, additive.
