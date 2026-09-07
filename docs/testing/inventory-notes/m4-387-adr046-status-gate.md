---
inventory-delta:
  tests/: +18
---
# m4-387 — one authoritative superseded status for ADR-046

#387 gave ADR-046 a single authoritative status: the front matter (canonical,
#379), the banner, and the body's historical note now all say Superseded by
ADR-082126-f69c, and a new registry gate reads the body's structured status
markers so the three-way contradiction that motivated the issue cannot
re-form unnoticed.

The +9 node IDs are all in `tests/test_check_adr_status_language.py` (new):

- Committed state is clean, and ADR-046 itself is checked by identity.
- Category 1 (body `**Status:**` lines): a disagreeing line fails; fixing a
  baselined one requires pruning the ledger; a 29th contradiction cannot be
  absorbed by the 28 legacy entries.
- Category 2 (replacement banners): a banner naming a different replacement
  than front matter `superseded-by` fails.
- Category 3 (status-asserting prose): the ADR-046 sentence shape fails, the
  line-wrapped spelling still matches, and dated past statements ("the status
  was `Accepted` at that time") are history, not assertions, and pass.

The +9 diff-coverage repair cases (same file) close the gate's last uncovered
statements:

- Category 2's other half: a banner on a document whose front matter has no
  `superseded-by` at all (banner-without-superseded-by).
- Ledger plumbing: a missing ledger reads as no known exceptions; `--update`
  banks exactly what the audit found and the next ordinary run passes.
- `_display` falls back to the verbatim path outside the corpus; a file with
  no front matter is body-only; the `__main__` guard exits 0 both in-process
  (`runpy`) and as a subprocess the way CI shells out.

Ledger correction (suite-inventory drift repair): this note also absorbs two
node IDs that landed under the #387 provenance adapter commit (36ce38e7)
without a note of their own — one case each in
`test_ratchet_provenance_integration_base.py` and
`test_m1_542_policy_coverage.py`
(`test_adr_status_language_adapter_covers_introduction_expansion_and_oracle`).
The diff-coverage repair itself added 7 node IDs (the first front-matter
bump of +8 was an off-by-one, corrected here): 9 + 7 + 2 = 18.
