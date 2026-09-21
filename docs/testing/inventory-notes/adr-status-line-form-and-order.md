---
inventory-delta:
  tests/: +3
---
# adr-status-line-form-and-order

Three tests added to `tests/test_check_adr_status_language.py`, all covering
gaps the order-dependence fix exposed rather than restating it:

- `test_the_mutated_adr_is_chosen_the_same_way_whatever_the_filesystem_yields`
  pins the new selection down. The two mutation tests used to take whichever
  ADR `Path.glob` handed over first, which is `os.scandir` order and therefore
  filesystem-dependent; they now select by the properties the mutation needs
  and this test runs that selection in two opposite orders.
- `test_a_list_item_status_line_is_not_exempt` drives the gate's category-1
  check with the `- **Status:** X` spelling, which it did not match before.
- `test_the_claim_is_the_whole_value_not_its_first_word` covers reading the
  whole status value, including the no-claim branch, so `AC Defined` is not
  compared as `AC`.
