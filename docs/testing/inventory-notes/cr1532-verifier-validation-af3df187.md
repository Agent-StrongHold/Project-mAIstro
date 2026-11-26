inventory-delta:
  tests/: +0
---

# cr-1532 verifier validation at af3df1875 (develop-sync merge of 80c837d578)

Independent verification of `retire-body-status-lines` (ADR-092126-a28a) at
head `af3df187547eb`, which merges develop tip `80c837d578c6` as second
parent; the worktree carried no unmerged paths and `git status` is clean. No
test was added, removed, or renamed in this round; inventory delta is zero.

## Measured, not assumed

- Develop-sync resolution: merge commit `af3df187547` with parents
  `94c9c7d17a` and `80c837d578c6`; `git ls-files -u` empty. The only
  `quality/` deltas vs the develop tip are the branch's own authored changes
  (`adr-status-language-baseline.json` 2+/1-, `public-routes.json` 5+/16-);
  no rows were lost in auto-resolution because the develop tip is a full
  parent of the head.
- Corpus retirement re-measured: `git diff 80c837d578..HEAD -- docs/adr
  docs/specs` deletes exactly **93** body `**Status:**` lines (bare and
  list-item spellings, with and without trailing spaces); the checked-out
  tree retains **0** declaration lines under `docs/adr`/`docs/specs` (the
  three residual `- **Status` grep hits are prose: the ADR-INDEX legend,
  SPEC-201's "Status bar", SPEC-232's "Status validity per kind").
- Gates re-run at this head, all RC=0: `check-adr-status-language.py`
  (0 baselined, none stale), `check-adr-status-language-provenance.py`
  (empty unversioned legacy ledger, explicit zero-tolerance migration to v2),
  `check-ratchet-provenance.py` (55 consumers), `check-contract-markers.py`,
  `check-public-routes.py` (11 identities, the previously red lane gate),
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (1221 -> 1221, baseline resolves from the develop tip),
  `check-adr-index.py`, `check-citation-status.py`, `tools/lint_lifecycle.py`,
  `check-release-consistency.py`, `ruff check .`, `ruff format --check .`,
  and `check-suite-inventory.py --suite tests/` (6282 identities match the
  recorded baseline).
- Tests re-run: `tests/test_check_adr_status_language.py` +
  `tests/test_check_adr_status_language_provenance.py` -> 100 passed;
  `test_auth_middleware.py`, `test_setup_first_run_questions.py`,
  `test_m1_542_policy_coverage.py` -> 87 passed.
- Live A/B against the develop gate (`git show 80c837d578:scripts/check-adr-
  status-language.py`, both audits driven via `audit(roots=...)` on a clean
  copy of a real corpus ADR): every agreeing body status line — bare,
  dash/star/plus/ordered items, 1- and 3-space indents, an indented nested
  item, and an empty value — produces exactly one `body-status-line` finding
  from the new gate while the develop agreement gate passes it (the hole this
  PR closes, AC-2/AC-3). Fenced and four-space-indented code blocks produce
  no finding from either gate (the documented exemption). Category 2/3
  patterns (`_BANNER_RE`, `_STAYS_RE`) are byte-identical to develop and
  their tests still fire (AC-4).
- Closure keywords: no fixes/closes/resolves in the PR body or any
  branch-only commit message.
- Changelog carries the literal owning-PR marker `(#1532)` (CHANGELOG.md:830);
  the evidence suite carries `pytest.mark.contract("behavioral")`.

## Not verified here

Hosted CI at this exact head remains UNVERIFIED (push is prohibited from this
worker); all gates the hosted run enforces were reproduced green locally.
