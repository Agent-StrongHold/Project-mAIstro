---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 develop-sync + gate re-validation round at 56f358aa2 (job 303a3b8f3e244ce999135f660afdd5bc)

Snapshot: issue #1893 only; branch `auto-1893`, starting head verified exactly
`56f358aa2f8d2798a22524568a55a4b3b200a81e`, briefed base `ab8b3737fa64`.
Worktree clean at entry, no incoming uncommitted work to salvage. Round type:
**develop sync** (the prior block's resolution path) plus re-validation of the
one red job (`exact-debt-ledger`) on the merged tree. No source, test, ledger,
grant, gate or migration edits authored this round; no GitHub mutations.

## develop sync

- `git fetch origin`: `refs/remotes/origin/develop` moved `ab8b3737fa64` →
  `369ab9adde2e`, exactly one commit: `369ab9add` (#2140, docs-only — drops the
  PostgresOntology claim from the ontology Protocol docstring in
  `packages/maistro-core/src/maistro/ontology/protocols.py`, +3/−2). Zero
  `quality/` changes on their side.
- Merged `refs/remotes/origin/develop` into `auto-1893` → merge commit
  `510bd74e5`, conflict-free (`ort`), only `protocols.py` changed.
- Post-merge ledger-integrity check (the AGENTS.md silent-row-loss hazard):
  `git diff --numstat 56f358aa2 HEAD -- quality/` is **empty** (no rows lost
  by the merge); vs `origin/develop` the diff is still exactly the branch's
  additive rows — 10 `ratchet-authorizations.json`, 2
  `reachability-baseline.json`, 11 `reachability-dispositions.json`, 0
  deletions anywhere.
- Local refname hazard recorded: `git rev-parse origin/develop` is ambiguous
  in this worktree (a stale local branch `refs/heads/origin/develop` still at
  `ab8b3737fa64` shadows the remote-tracking ref). All gates below use the
  unambiguous `refs/remotes/origin/develop`, which is what CI's
  `origin/develop` names.

## exact-debt-ledger at CI argv on merged tree 510bd74e5 (base 369ab9add)

Environment: `uv sync --locked --all-extras` re-applied first (CI parity).

- Step `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → exit 0, **1322 reviewed identities → 1322
  findings, unclassified 0, never_allowlist 0**. The brief's ledger-amendment
  path has no target: nothing unbanked, nothing eliminated.
- Step `check-shipped-surface-truth.py` → exit 0 ("matrix is complete").
- Step `check-ratchet-provenance.py` with
  `RATCHET_BASE_REV=refs/remotes/origin/develop` → exit 1 on **exactly**
  `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`
  (both the reachability and reachability-dispositions sub-gates); all eight
  other ratchets and all 53 provenance consumers OK.
- Root cause unchanged and re-derived post-merge: the #1893 reachability
  grant commit `6af21c54e` is an ancestor of this branch's HEAD (+10 rows in
  `quality/ratchet-authorizations.json`) but is **absent from develop**
  (`git merge-base --is-ancestor 6af21c54e refs/remotes/origin/develop`
  fails; the only new develop commit touches a docstring). Provenance reads
  authorizations from the merge base (two-merge rule), so the gate stays red
  until the owner lands the grant on develop — an action prohibited to
  workers.
- **Grant-first proof re-proven on the merged tree**:
  `RATCHET_BASE_REV=6af21c54e` → the FULL provenance gate exits **0**
  ("171 unreachable module(s) have dispositions; new debt uses prior
  reachability authorization"; "OK: 53 quality JSON consumer(s) have explicit
  provenance"). The sole remaining ingredient for `exact-debt-ledger` green
  remains the owner-side grant landing on develop.

## Regression battery on the merged tree

- `uv run ruff check .` → exit 0; `uv run ruff format --check .` → 3301 files
  already formatted, exit 0.
- Targeted pytest (cli_lock, pack_contracts, root_admission_identity,
  admission_codec) → **346 passed, 3 skipped**; the 3 skips are the DSN-gated
  PG legs at `test_admission_codec.py:470` (verified via `-rs`).
- Admission modules and their tests are bit-identical to the last fully
  validated head: `git diff --stat 94de9c2ec HEAD` over
  `admission_codec.py`, `admission_identity.py` and both test files is empty.
- **PG durability re-proven live THIS round** (not carried forward on trust):
  fresh `pgvector/pgvector:pg18` container (`adm1893-r3`, host port 15439, DB
  `adm1893_r3`), real alembic chain `001 → 063_canonical_goals` exit 0, then
  both admission test files with `MAISTRO_REQUIRE_PG_LEGS=1`,
  `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` pointed at the fresh
  server → **204 passed, 0 skipped**. Container removed afterwards.
- mypy (AGENTS.md argv, all-extras env) → "Success: no issues found in 901
  source files".
- `check-suite-inventory.py --suite packages/maistro-core/tests` → ok,
  16567 collected node IDs match the recorded inventory; no test additions
  this round, hence `inventory-delta: 0`.

## Verdict inputs

All candidate-side acceptance evidence is green and freshly executed on the
merged tree. The single red CI job (`exact-debt-ledger`) fails only on the
two #1893 identities, and only because the pre-landed grant (`6af21c54e`)
has not yet reached develop — mechanically proven by the grant-first proof
(full gate exit 0 with a grant-containing base). No candidate-side repair
exists: wiring the modules or deleting them is forbidden by the issue text
and prior rounds; amending `vulture-baseline.json` has no target (exact
1322==1322); amending the grant again would not help (base-only reads).
This is an owner-side two-merge dependency, not a candidate defect.
