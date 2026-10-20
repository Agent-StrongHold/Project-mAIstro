inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26 verification (2026-10-09, head 15de1c5e, repair lane L26, job 8f7c528d)

Repair-round re-validation of issue #26 / PR 1742 at the assigned exact
head `15de1c5e403c` (develop base `d99e598e1084`). The previous verify
job (`a64345a4929142ea9`) recorded "validation failed" — but its
check-3.log shows pytest died *at startup* with
`OSError: [Errno 28] No space left on device: '/tmp/tmp4xbtxg63'`
before collecting a single test; ruff check and ruff format had already
passed in the same run. The failure was environmental (transient full
/tmp), not a code regression. This round re-executes the full battery
at the current head with `/tmp` healthy (21G free). No production or
test code changed in this round (`inventory-delta: +0`); this note is
the only edit.

## Locally executed at this head (this round, not carried forward)

- `uv run pytest packages/maistro-registry/tests -q` -> **84 passed**
  (1.74s). `uv run pytest tests/test_check_reachability.py
  tests/test_check_security_inventory.py -q` -> **74 passed**.
- `uv run ruff check .` -> clean; `uv run ruff format --check .` ->
  3212 files clean.
- CI-exact typecheck (ci.yml mypy target list, all ten package src
  trees) -> `Success: no issues found in 1034 source files`.
- Gates with CI's exact arguments:
  - `scripts/check-vulture-baseline.py packages/*/src --min-confidence
    60 --exclude '*/third_party/*'` -> exit 0, 1326 reviewed identities
    = 1326 findings (exact-debt-ledger green).
  - `scripts/check-reachability.py` -> exit 0 (1372 modules, 169
    unreachable).
  - `scripts/check-security-inventory.py` -> exit 0 (60 cited paths, 23
    rows, 2 counted claims).
  - `scripts/check-suite-inventory.py` -> exit 0, 17 suites match.
  - `scripts/check-cross-package-imports.py` -> exit 0.
  - `python -m maistro_registry.cli lint . --strict` (registry.yml
    front-matter gate) -> exit 0, 437 files, 0 errors, 0 warnings.

## Issue #26 acceptance, re-executed live

- Measured quality at the public seam: `maistro-registry eval .
  --min-mrr 0.9 --min-recall 0.9` -> recall@10 **0.9583**, MRR
  **0.9583**, nDCG@10 **0.9292**, exit 0 over the current 449-document
  corpus — matches the floor recorded in test_retrieval_quality.py;
  the only [MISS] is the declared no-answer case, contributing zero
  credit by construction (empty `relevant` -> recall/MRR/nDCG 0.0).
- Supersession with status: `maistro-registry search "recurring agent
  task scheduler" .` ranks `ADR-046 [Superseded] (92c1d24898dd)
  docs/adr/ADR-046-scheduler.md` with its lifecycle status inline, plus
  the Accepted successor — retrieved, never posing as active authority.
- Corpus-statistical rejection, live: the same query reports `terms
  rejected (corpus-statistical): agent`; the no-answer query reports
  `rejected: quantum consciousness for the` and returns only honestly
  provenanced weak matches (no fabricated governing citation).
- Stale-index refusal, live: index built over a corpus copy (fingerprint
  `9a6fbd5e36be1dc5`), one line appended to KNOWN-GAPS.md, then
  `search --index` -> `error: stale index: index fingerprint
  9a6fbd5e36be1dc5 does not match the corpus at this root
  (c916c3c581959faf) ... rebuild it with maistro-registry index`,
  exit 2. Refresh/removal invalidation covered structurally by
  test_stale_index_reason_enforces_freshness_against_the_corpus
  (addition + content-change legs) and
  test_fingerprint_moves_with_any_corpus_change (removal leg).
- Acceptance-case tests re-run individually, all passing:
  renamed-source/stable-id (test_renamed_source_keeps_stable_id_but_
  moves_the_fingerprint), changed content (test_version_changes_when_
  bytes_change), superseded decision (test_superseded_decision_is_
  retrieved_with_its_status), duplicate identity (corpus addressability
  + test_duplicate_identity_keeps_metrics_within_bounds), useless
  expansion terms (test_expansion_terms_face_corpus_statistics),
  no-relevant-result (test_search_with_no_hits_says_so), real-corpus
  floor (test_real_corpus_meets_the_recorded_quality_floor).

## Hosted CI at this head

All 22 completed check runs SUCCESS on `15de1c5e403c` (Quality gate,
exact-debt-ledger, SAST, coverage legs, lint-and-type-check, test,
registry validation, Gate C); the skips are service-limited workflow
legs. Pending/skipped hosted legs remain a separate merge gate and are
UNVERIFIED here by contract.

## Residual risks

- origin/develop has 3 commits not in this branch (harmless divergence;
  no sync conflict to resolve — the triggering failure was disk-full,
  not merge-related).
- No closure keywords in any of the 92 branch commits; PR body says
  "Refs #26" only. No issue-closure actions taken.
