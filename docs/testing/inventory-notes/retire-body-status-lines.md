---
inventory-delta:
  tests/: +1
---
# retire-body-status-lines

Net +1 in `tests/test_check_adr_status_language.py`, and the net hides a
larger reshuffle that is worth stating, because ADR-092126-a28a changed what
the first category *is*. It used to check that a body `**Status:**` line
agreed with front matter; it now checks that no such line exists at all.

Removed (2), both testing machinery the new rule deletes:

- `test_the_mutated_adr_is_chosen_the_same_way_whatever_the_filesystem_yields`
  — proved the selection helper picked a document carrying a status line
  regardless of `glob` order. No document carries one now; the tests introduce
  the line themselves, so there is nothing to select for. The order-dependence
  it guarded is covered where it now lives, in `_an_adr`'s own assertions.
- `test_the_claim_is_the_whole_value_not_its_first_word` — covered
  `_claimed_status`, which is gone. Absence needs no status vocabulary, no
  multi-word values and no case folding.

Added (3):

- `test_the_corpus_carries_no_body_status_line_at_all` — the retirement
  itself, asserted against the real corpus. Fails if any of the 83 lines comes
  back, including via a merge reinstating an old revision, which no
  per-document test would notice.
- `test_a_body_status_line_fails_even_when_it_agrees` — the rule that makes
  the retirement durable, and the case the old agreement check let through.
- `test_a_status_line_dressed_up_with_trailing_prose_is_still_caught` — a
  qualified line (`**Status:** Accepted — ratified ...`) is still a line, so
  decoration is not a route back in.

Renamed in place, no count change: the disagreeing-line test keeps its
coverage under `test_a_disagreeing_body_status_line_still_fails`, the empty
line moves from "declares nothing, so skip it" to "still a retired line", and
the two ledger tests drop "contradiction" for "finding".
