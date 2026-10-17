inventory-delta:
  packages/maistro-registry/tests: +0

# auto-26-verification (2026-10-07, HEAD 82cf35961484)

Independent verification of issue #26 / PR 1742 at the develop-sync merge
head 82cf35961484 (merge of 28614700bd into auto-26; two sync merges past
the previously verified 403328166). Every claim below was executed in
this round at this head. No production or test code changed (delta +0);
this note is the only edit.

- pytest packages/maistro-registry/tests: 84 passed (matches the recorded
  inventory). pytest tests/test_check_reachability.py
  tests/test_check_security_inventory.py: 74 passed; slowest single test
  5.95s (test_baseline_matches_the_tree), far under the 30s per-test
  bound that reded the coverage gate at 8c2f58ea — the functools.cache
  walk/census fixes (7edd6ab12, 6efbbfceb) hold. ruff check: clean.
- Gates with CI's exact arguments: scripts/check-reachability.py
  (1366 production modules, 169 unreachable, exit 0);
  scripts/check-security-inventory.py (60 cited paths, 23 rows,
  2 counted claims recomputed, exit 0);
  scripts/check-suite-inventory.py (ok: 17 suites, 28947 unique node
  identities, 0 duplicate evidence).
- Live acceptance at the public seam: `maistro-registry eval . --min-mrr
  0.9 --min-recall 0.9` -> recall@10 0.9583 / MRR 0.9583 / nDCG@10 0.9292,
  exit 0; the declared no-answer case reports [MISS] 0.0.
- Hands-on probes on a /tmp corpus copy (worktree untouched): stale-index
  refusal after a corpus edit (exit 2, both fingerprints and the rebuild
  command in the error); supersession provenance rendered verbatim
  (`ADR-046 [Superseded] (92c1d24898dd) docs/adr/ADR-046-scheduler.md`);
  corpus-statistical rejection observed live ("agent" rejected as
  ubiquitous); a file with invalid front matter indexes as `ADR-777-fake
  [?]` — no fabricated id, status, or governing citation from missing
  evidence.
- mypy packages/maistro-registry/src: 2 import-untyped notes
  (linker.py pre-existing at the merge base; retrieval/expand.py the same
  class against maistro-core's gateway). CI's mypy gate is
  `mypy --strict packages/maistro-core/src` (quality.yml:1446) and does
  not include this package.
- No dependency changes (pyproject/uv.lock untouched); no ratchet-ledger
  edits (quality/ delta is the per-branch ac-state note only).
- Closure keywords: none (`fixes|closes|resolves ... #N`) in any commit
  message on the branch; PR body says "Refs #26" only.
- Hosted CI at this head: all previously failing legs green at capture;
  the aggregate "Coverage gate (publish-set floor + diff coverage)",
  "test", and "gates-ran" jobs were still pending (2026-10-07) — pending
  CI is UNVERIFIED by contract and remains a separate merge gate.
