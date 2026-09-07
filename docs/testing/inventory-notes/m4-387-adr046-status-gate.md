---
inventory-delta:
  tests/: +9
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
