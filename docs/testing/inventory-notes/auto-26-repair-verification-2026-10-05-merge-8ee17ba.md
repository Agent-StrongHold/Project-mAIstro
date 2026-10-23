---
inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26-repair-verification (2026-10-05, merge head 8ee17bab)

Independent verification round at the exact dispatch head `8ee17bab38cc`
(merge of develop `b672b799aba6` into auto-26 `0b2d6e58e1d9`). No production
or test code changed on the branch side; `inventory-delta: +0`.

## Merge hygiene

- No file changed on both sides of the merge
  (`comm` of the two parent diffs is empty), so no quality/ row or other
  content was silently auto-resolved.
- `git diff --numstat b672b799..8ee17bab -- quality/` shows only
  `quality/ac-state-notes/auto-26.json` (+17); no ratchet-ledger rows were
  added, removed, or replaced relative to develop.
- develop's carried changes (git server security, maistro-rsi harvest, route
  permissions) touch no retrieval file; the lane's sources are byte-identical
  to the previously verified head `0b2d6e58e1d9` (empty diff over
  packages/maistro-registry, scripts/check-security-inventory.py,
  tests/test_check_security_inventory.py, inventory baseline).

## Locally re-executed at this head

- `uv run ruff check .` — pass.
- `uv run pytest packages/maistro-registry/tests/test_retrieval_{cli,corpus,
  expansion,index_search,quality}.py -q` — 61 passed.
- `uv run pytest tests/test_check_security_inventory.py -q` — 49 passed.
- `python scripts/check-suite-inventory.py` (CI's no-arg invocation) — 15
  suites, 26,742 collected node IDs, 0 duplicate identities; the develop
  merge carries its own baseline/notes, so the full-repo gate still matches.
- `python scripts/check-security-inventory.py` (CI's no-arg invocation) —
  23 inventory rows match, 2 counted claims recomputed, exit 0 in ~5s
  (parse-once caching fix holds at this head).
- `python scripts/check-vulture-baseline.py packages/*/src --min-confidence
  60 --exclude '*/third_party/*'` (CI's exact arguments) — 1342 reviewed
  identities = 1342 findings against the merge-base baseline; exit 0.
- `python scripts/check-reachability.py` — exit 0.
- `maistro-registry eval --json` — MRR 0.9583, recall@10 0.9583, nDCG@10
  0.9300 over 24 golden queries; `--min-mrr 0.9 --min-recall 0.9` exits 0,
  `--min-mrr 0.99` exits 1 with FAIL; the declared no-answer query reports
  MISS at 0.000 across all metrics.
- `maistro-registry search "recurring agent task scheduler"` — renders
  `ADR-046 [Superseded] (92c1d24898dd)` plus the Accepted successor
  `ADR-082126-f69c`; `sha256sum` of `docs/adr/ADR-046-scheduler.md` confirms
  `92c1d24898dd` is the true content version; corpus-ubiquitous `agent` is
  rejected corpus-statistically.
- Stale index (in /tmp copy, tree untouched): edit leg and removal leg each
  exit 2 naming `maistro-registry index` with both fingerprints; rebuilding
  over the identical corpus reproduces fingerprint `24d3dc8dbb76b41d`
  (432 documents, vocabulary 10656).

## Closure-keyword scan

PR #1742 body ("Refs #26" only) and all 50 commit messages in
`b672b799..8ee17bab` scanned for GitHub closure forms
(fixes/closes/resolves #N): none. `fix(#26)` in conventional-commit subjects
is scope syntax, not a closure keyword.

## Hosted CI

At this exact head the rollup had 26 completed checks (no failures; one
by-design skip) and 4 in progress (coverage ×2, test, Quality gate) at
verification time — pending, therefore UNVERIFIED here; the merge-queue
evaluation reports green. Hosted completion remains the integration gate.
