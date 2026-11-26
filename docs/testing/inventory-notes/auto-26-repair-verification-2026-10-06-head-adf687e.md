inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26-verification (2026-10-06, HEAD adf687ed38ca)

Independent verification of issue #26 / PR 1742 at the develop-sync merge
head adf687ed38ca (merge of 11376c7be into auto-26). Every claim below
was executed in this round at this head, not carried from prior notes.
No production or test code changed (delta +0).

- Duplicate-identity metrics re-proven via the public path on a fresh
  synthetic corpus: raw `RetrievalSearcher.search` returns both ADR-001
  claimants; `evaluate` reduces to first occurrences — recall/mrr/ndcg
  all 1.0, `matched_relevant=("ADR-001",)`. The recall=2.0/ndcg=1.63
  defect stays fixed after the develop sync.
- pytest packages/maistro-registry/tests (retrieval suites + conftest):
  62 passed. pytest tests/test_check_security_inventory.py: 49 passed.
  Gate `scripts/check-security-inventory.py`: OK (59 cited paths, 23
  rows, 2 counted claims recomputed).
- ruff check / ruff format --check: clean (3021 files). mypy at CI's
  exact six-src-dir arguments: Success, 831 files.
  scripts/check-suite-inventory.py --suite packages/maistro-registry/tests:
  67 nodes match the recorded inventory. check-backlog-consistency: ok.
- Live acceptance: `maistro-registry eval . --min-mrr 0.9 --min-recall 0.9`
  -> 0.9583/0.9583/0.9300, exit 0 (README floor reproduces); the
  no-answer golden case reports [MISS] 0.0 (no fabricated citation).
  `search` results resolve to exact source bytes: result `version`
  equals sha256[:12] of the file on disk (probed on ADR-046, SPEC-080126,
  ADR-082126; statuses render, e.g. [Superseded]).
- Stale-index refusal probed hands-on: after editing and after removing
  an indexed document, `search --index` and `eval --index` both exit 2
  with the fingerprint mismatch and the rebuild command.
- Closure-keyword scan: no fixes/closes/resolves in the PR body
  ("Refs #26") or any commit message on the branch.
- Hosted CI at this head was in_progress at review capture (pr-base and
  block success; rest pending) — pending CI is UNVERIFIED by contract
  and remains a separate merge gate.
