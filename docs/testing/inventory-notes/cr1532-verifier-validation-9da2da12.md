---
inventory-delta:
  tests/: +0
---

# cr-1532 verifier validation at 9da2da125 (develop-sync merge of f8a2df966)

Independent verification of `retire-body-status-lines` (ADR-092126-a28a) at the
develop-sync head `9da2da125975`, base `f8a2df966a1d`. No test was added,
removed, or renamed; the only test-file change in this round is a docstring
count correction (91 -> 93, measured below), which moves no collected case.

## Measured, not assumed

- Corpus retirement re-measured against the real base: `docs/adr` + `docs/specs`
  at `f8a2df966` carry **93** body `**Status:**` lines across **93 documents**
  (67 ADRs, 26 specs), scanned independently of the gate's own parser
  (fences blanked, blockquote/list/indentation prefixes matched). At
  `9da2da125` the same scan finds **0**. This is the number the ADR, index row,
  changelog entry, and gate docstring already claim; the stale "83"/"91"
  wording in the inventory note and the corpus-test docstring was the only
  remaining mismatch and is corrected by this round.
- Live gate probes (20 fixtures under /tmp, valid registry front matter):
  agreeing bare line, dash/star/plus/ordered spellings, disagreeing value,
  trailing prose, empty value, 1-3 space indents, blockquote, blockquoted
  list item, and a nested list item each produce exactly one
  `body-status-line` finding; fenced (``` and ~~~) and four-space-indented
  code blocks produce none; `banner-without-superseded-by` and
  `body-asserts-status-stays` still fire on their own (AC-1..AC-4).
- Metric v2 wiring: `require_metric_version` exists in
  `scripts/ratchet_provenance.py`; the adapter refuses a candidate ledger
  without v2, admits only the structurally empty unversioned legacy ledger,
  and keeps prior-base grant requirements unchanged (16 adapter cases pass).
- Focused suites: `tests/test_check_adr_status_language.py` +
  `tests/test_check_adr_status_language_provenance.py` = 100 passed at this
  head; targeted producer reproduction (198 tests incl. the two ratchet
  suites and the #542 policy coverage suite) all pass.

## Gates executed at this head (all exit 0)

`check-adr-status-language.py`, `check-adr-status-language-provenance.py`,
`check-adr-index.py`, `check-contract-markers.py`,
`check-release-consistency.py`, `check-ratchet-provenance.py`,
`check-citation-status.py`, spec-AC-index regeneration diff-clean,
`check-merge-markers.py`, `tools/lint_lifecycle.py`,
`check-suite-inventory.py` (21 suites match),
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` (1238 = 1238), `maistro_registry.cli lint . --strict`
(445 files, 0 errors, 0 warnings),
`check-diff-coverage.py` against the base over a targeted `--source=scripts`
producer run: 2 changed measured files at/above 90% lines / 80% branches.
Ruff check + format clean (driver logs at this head).

## Coverage-gate cancellation

The hosted cancellation (run 40380074341, job 121782351343) was the job being
killed at its own 30-minute ceiling before measuring; the in-branch repair
`8f15f2ef0` raises `timeout-minutes` 30 -> 45 with the measured rationale.
This diff changes no publish-set package file, so the 87% floor measures
develop-identical sources; the scripts-producer diff measurement above passes
locally. Full hosted re-run remains the authority for the floor.
