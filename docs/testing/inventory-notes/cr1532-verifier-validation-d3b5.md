---
inventory-delta:
  tests/: +0
---

# cr1532-verifier-validation-d3b5

Independent verification round for PR #1532 (retire body status lines,
ADR-092126-a28a) at head `726332a48aeb047f37038bbc07724dce903dd751` against
base `4019249e8b07a6de7763be8e448a264cfec787dc` (merge-base equals the develop
tip, so the develop sync is complete). No tests were added or changed; this
note records the round's evidence. Deltas are all zero.

Gates re-run with CI's exact arguments, all exit 0:

- `python scripts/check-adr-status-language.py` (registry.yml) — 0 baselined,
  no new, none stale.
- `scripts/check-adr-status-language-provenance.py` — metric v2; the trusted
  ledger is the structurally empty unversioned shape and migrates explicitly
  to v2 with zero tolerance.
- `python scripts/check-suite-inventory.py` (ci.yml) — 21 suites match;
  baseline `tests/` 4117 plus every unfolded note delta, including this
  branch's `retire-body-status-lines` +52, `1532-ordered-status-followup` +24,
  `1532-p2-fence-blockquote-tests` +4 and the merge note +0, equals 6112,
  exactly the collected count. Measured directly: develop has 20 tests in
  `tests/test_check_adr_status_language.py` and no provenance file; this head
  collects 84 + 16 = 100, a true +80 that the four notes document.
- `scripts/check-ratchet-provenance.py`, `scripts/check-adr-index.py`,
  `scripts/check-citation-status.py`, `scripts/check-citation-status-provenance.py`,
  `tools/lint_lifecycle.py`, `scripts/check-contract-markers.py`,
  `scripts/check-merge-markers.py`, `scripts/check-doc-links.py`,
  `scripts/check-release-consistency.py`, `scripts/check-test-duplicates.py`.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1256 reviewed identities,
  1256 findings; no amendment needed.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- Targeted suites: `tests/test_check_adr_status_language.py`,
  `tests/test_check_adr_status_language_provenance.py`,
  `tests/test_m1_542_policy_coverage.py`, `tests/test_check_adr_index.py` —
  135 passed.
- `uv run python -m maistro_registry.cli lint . --strict` — 443 files, 0
  errors, 0 warnings.

Behavioral red-proof, run in a temp directory against the production
`audit(roots=...)` entry point with a real validating ADR as fixture base:
agreeing bare/dash/star/plus/ordered lines, one- and three-space indented
lines, and a blockquoted line are all flagged; a clean document, a fenced code
block, and a four-space indented code block are all excluded. 11/11 as
specified.

Corpus evidence: the diff removes exactly one `**Status:**` body line from 93
documents under `docs/adr/` and `docs/specs/` and re-adds none; the only
added matches are prose quotes inside the new ADR and its index row.
CHANGELOG carries the literal `(#1532)` marker under `### Changed`.

Hosted-CI note: the failing coverage job
(Coverage gate (publish-set floor + diff coverage)) was cancelled by the
runner (`The operation was canceled.`); its measured sources are exclusively
`packages/*/src` trees, and this branch's diff touches no `packages/` path
(docs, scripts, tests, quality, CHANGELOG only), so the measured outcome
cannot differ from develop's baseline. The cancellation is infrastructure,
not code; the branch-local equivalent of every other gate is green above.
