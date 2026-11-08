---
inventory-delta:
  tests/: +0
---

# cr1532-verifier-validation-fcb3844

Independent verification + repair round for PR #1532 (retire body status
lines, ADR-092126-a28a) at head `fcb384435a21b9ec22ac0bed135ade14d1c9e0f2`
against develop `05070ff0777ae480830781782bf74c914ce47bbc`. No tests were
added or changed this round; deltas are all zero.

## Repair performed

The lane's previous block was a develop sync conflict preserved in the
worktree: an in-progress merge of `origin/develop` (`05070ff0`, three new
commits — #1596 Workspace BacklogItem, #2287 durable DAG history, #2169
governed tool execution) with exactly one unmerged path, `CHANGELOG.md`. All
other merge changes (102 additions, 76 modifications) were staged from the
develop side and verified to originate in develop commits before committing.

Conflict resolution: HEAD carried the entry as "`…(#2357).** (#2359)`"; develop
refined the same entry to "`…(#2359; follow-up to #2357).**`". Develop's line
contains the branch's intent (the `(#2359)` tracked-issue marker) in its newer
phrasing, so develop's wording was taken verbatim; the shared body of the
entry was untouched. Merge committed as `fcb384435`; `origin/develop` is an
ancestor of HEAD.

## Verification at the new head

Gates re-run with CI's exact arguments, all exit 0:

- `python scripts/check-adr-status-language.py` (registry.yml) — 0 baselined,
  no new, none stale (AC: corpus carries no body status declarations).
- `python scripts/check-adr-status-language-provenance.py` — metric v2;
  candidate fcb38443; trusted base 05070ff0; the empty unversioned legacy
  ledger migrates explicitly with zero tolerance.
- `python scripts/check-suite-inventory.py` (ci.yml) — 21 suites match the
  recorded inventory.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (quality.yml) — 1248
  reviewed identities, 1248 findings, unclassified 0; no unbanked scanner
  finding exists, so the hosted-CI coverage/vulture cancellations need a
  requeue, not a code change.
- `python scripts/check-ratchet-provenance.py` — 0 lifecycle violations, no
  candidate-approved expansion, 55 quality JSON consumers have provenance.
- `check-contract-markers.py`, `check-citation-status.py`,
  `check-adr-index.py`, `check-merge-markers.py`, `check-doc-links.py`,
  `check-release-consistency.py`, `check-backlog-consistency.py` — all clean.
- `uv run ruff check .` and `uv run ruff format --check .` — clean (3555
  files).
- `uv run pytest tests/test_check_adr_status_language.py
  tests/test_check_adr_status_language_provenance.py tests/test_check_adr_index.py
  -q` — 119 passed.

## Behavioral probes (driven through the gate's own machinery, /tmp only)

- Indentation/spelling grammar (AC-1): `**Status:** …` flagged at 0, 1, 2, 3
  leading spaces; bare, `- `, `* `, `+ ` and ordered `1. ` list spellings all
  flagged; nested list markers at 2 and 4 spaces flagged; value-independent
  (retirement, not agreement); blockquote-prefixed line flagged.
- Exemptions (AC-1): a 4-space plain paragraph indent (unmarked indented code
  block) and fenced code blocks (``` and ~~~) are NOT flagged.
- Metric v2 fail-closed (AC-2): candidate ledger missing the version or
  recording v1 → fail; trusted unversioned ledger with nonempty `known` or
  malformed `details` → fail closed; trusted recorded v1 vs declared v2 →
  fail via `require_metric_version`; only the structurally empty unversioned
  trusted ledger migrates, and matching v2 passes.
- Categories 2/3 unchanged (AC-6): a `Superseded by` banner without a
  matching front-matter ref still raises `banner-without-superseded-by`.

## Static surface

- `CHANGELOG.md:623` carries the literal owning marker `(#1532)` inside
  `## [Unreleased]` (lines 24–2569).
- `docs/adr/ADR-092126-a28a-retire-body-status-lines.md` exists with
  `status: Accepted` front matter; `docs/adr/ADR-INDEX.md:219` row agrees
  (checked by `check-adr-index.py`).
- `quality/adr-status-language-baseline.json` records
  `metric_definition_version: 2`, `known: []`, `details: {}`.
- Corpus grep cross-check: the only remaining `**Status:**` occurrences in
  `docs/adr`/`docs/specs` are inline-code prose inside ADR-092126-a28a itself
  and the ADR-INDEX summary column (excluded from the audit by design); no
  anchored declaration lines remain.
