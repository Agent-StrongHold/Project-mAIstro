inventory-delta:
  packages/maistro-registry/tests: +0

# auto-26-verification (2026-10-07, HEAD 403328166118)

Independent verification of issue #26 / PR 1742 at the develop-sync merge
head 403328166118 (merge of 9bd1a93eee into auto-26). Every claim below
was executed in this round at this head. No production or test code
changed (delta +0); this note is the only edit.

- pytest packages/maistro-registry/tests: 84 passed (full suite,
  matches the recorded inventory). pytest
  tests/test_check_reachability.py tests/test_check_security_inventory.py:
  74 passed. ruff check: clean.
- Gates with CI's exact arguments: scripts/check-reachability.py
  (1362 production modules, 169 unreachable, exit 0);
  scripts/check-security-inventory.py (OK: 60 cited paths, 23 rows,
  2 counted claims recomputed, exit 0);
  scripts/check-suite-inventory.py (ok: 17 suites, 28431 unique node
  identities, 0 duplicate evidence). The two gate-script changes on this
  branch are functools.cache performance fixes over pure functions plus a
  copy-at-the-boundary return; no gate semantics weakened.
- Live acceptance at the public seam: `maistro-registry eval . --min-mrr
  0.9 --min-recall 0.9` -> recall@10 0.9583 / MRR 0.9583 / nDCG@10 0.9292,
  exit 0; the no-answer golden case reports [MISS] 0.0. Superseded
  material retrieved with its status verbatim
  (`ADR-046 [Superseded] (92c1d24898dd) docs/adr/ADR-046-scheduler.md`);
  corpus-statistical rejection observed live ("agent" rejected as
  ubiquitous on the scheduler query).
- README comparison table re-derived at this head (449 docs; the table is
  pinned to the 2026-10-03 432-doc revision): `--max-df-share 1.0`
  0.958/0.958/0.930 (table: 0.958/0.958/0.931); enrichment off
  0.938/0.958/0.916 (exact match); +broad static expansion candidates
  0.764/0.896/0.770 vs 0.958 shipped baseline — the same-direction
  expansion regression the table records.
- Stale-index invalidation re-proven hands-on on a temp corpus copy
  (worktree untouched): after editing an indexed ADR, `search --index`
  exits 2 with the fingerprint mismatch and names the rebuild command.
- mypy on packages/maistro-registry/src reports 2 pre-existing
  import-untyped errors in linker.py (present at the merge base; CI's
  mypy gate targets packages/maistro-core/src only).
- Closure-keyword scan: PR body says "Refs #26"; no
  fixes/closes/resolves-#N in any commit message on the branch.
- Hosted CI at this head was queued/in_progress at capture (2026-10-07
  snapshot) — pending CI is UNVERIFIED by contract and remains a
  separate merge gate.
