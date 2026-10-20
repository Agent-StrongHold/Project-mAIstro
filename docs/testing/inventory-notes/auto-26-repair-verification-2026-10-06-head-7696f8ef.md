---
inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26-repair-verification (2026-10-06, HEAD 7696f8efac0c)

Independent verification of issue #26 / PR 1742 at the merge head with
develop (7334621bf). Every claim below was executed in this round, not
carried from prior notes. No production or test code changed (delta +0).

- Prior finding (duplicate-identity metrics, quality.py): the un-deduped
  path was reproduced hands-on — a ranking carrying ADR-001 twice fed to
  recall_at_k/ndcg_at_k reports recall=2.0,
  ndcg=1.6309297535714575 (exactly the prior round's numbers). At this
  head `_evaluate_case` reduces the ranking with `dict.fromkeys` before
  any metric sees it: recall=1.0, ndcg=1.0, mrr=1.0,
  `matched_relevant=("ADR-001",)`, while the search layer still returns
  both claimants (addressability preserved,
  test_duplicate_identity_keeps_both_documents_addressable).
  Guard: test_duplicate_identity_keeps_metrics_within_bounds (passes).
- pytest packages/maistro-registry/tests: 67 passed (inventory match).
- pytest tests/test_check_security_inventory.py: 49 passed; gate
  `scripts/check-security-inventory.py`: OK (59 paths, 23 rows, 2 claims).
- ruff check / ruff format --check: clean (3017 files).
- mypy at CI's exact six-src-dir arguments: Success, 830 files.
  (Running the registry package alone reports import-untyped notes for
  `maistro.http`/`maistro.capabilities...llm_gateway` — pre-existing
  posture, not how CI invokes mypy.)
- README measured claims reproduce from the authoritative files:
  `maistro-registry eval .` -> MRR 0.9583, recall@10 0.9583,
  nDCG@10 0.9300; `--max-df-share 1.0` variant -> nDCG 0.9312 (README's
  0.931); the declared no-answer query reports
  `[MISS] mrr=0.000 recall=0.000 ndcg=0.000` — a fabricated governing
  citation is not producible from missing evidence.
- Stale-index enforcement demonstrated end-to-end in /tmp (no tree
  edits): an index built over one corpus state, then `search --index`
  against a root with edited content, refuses with both fingerprints and
  the rebuild command (issue: refresh/removal invalidates stale content).
- Closure keywords: none in the PR body ("Refs #26") nor in any branch
  commit message (7334621bf..7696f8efa).
- Ledger hygiene: 99991f4d8 prunes a superseded design_coverage grant
  (tightening); 675f854b9 banks a measured ac-state improvement the
  ratchet demanded. No floor raise, no debt weakening; vulture-baseline
  untouched by the branch.
- Hosted CI at this exact head (live `gh pr view 1742` refresh):
  24 checks SUCCESS — including every previously failing one (Supply
  chain pip-audit, security, SAST, lint-and-type-check, Quality gate,
  exact-debt-ledger, Gate C, formal-conformance). Still IN_PROGRESS at
  verification time: `test`, `integration-scope`, `coverage
  (PostgreSQL)`, `docker-build`; `gates-ran` PENDING. By contract the
  rollup is UNVERIFIED-complete, not green.
