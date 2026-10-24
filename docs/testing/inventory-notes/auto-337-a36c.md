---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
  tests/: +1
---
# auto-337-a36c

Repair-round additions for the merge-queue evaluation at e32a2068: the
diff-coverage gate scored changed lines and arcs in `routes/feedback.py`,
`routes/metrics.py` and `services/node_metrics_store.py` below the per-file
floor, and the acceptance-state criteria declared in SPEC-083026-2642
(AC-6..AC-10) needed their own proving tests at the seams they name. All
eight are new tests; none replaced or renamed an existing one.

Store mechanics the durability contract leans on
(`test_durable_node_metrics.py`, +5):

- a non-positive `max_observations` is refused at construction instead of
  evicting every row as it is written;
- a records store without the `initialize` seam still refreshes (the durable
  contract may not require a richer protocol than a plain mapping);
- a record whose `recorded_at` is already a native datetime loads, beside the
  ISO-string round-trip;
- load-time retention trims the records themselves to the bound, not just the
  in-memory buffer;
- `clear()` on a durable store drops the durable rows, and the emptiness
  survives a restart.

Feedback execution-identity refusals (`test_feedback_route.py`, +2): the
`_execution_identity` helper's own door — an invisible run is a 404 and a
configured-away canonical spine is a 503 — exercised directly, since
`_record_feedback` refuses earlier and no route-level test reached these
branches.

The `/v1/dag-metrics/retention` endpoint
(`test_node_metrics.py`, +1): a deployment reports `durable: false`, the
observation bound and its no-ad-hoc-delete policy instead of leaving the
route unmeasured.

## Round 3 (CI repair): reconciliation-gate fork handling (`tests/`, +3)

The containers lane failed at 976ad2f on trivy HIGH CVEs in pypdf 6.21.1
(uv.lock -> 6.21.2), and the fix exposed a second, latent failure in the
reconciliation gate: the previous repair round's fastmcp 4.1.3 bump forked
beartype into two marker-conditional lock entries (`0.22.9 ; python < 3.15`,
`0.23.1 ; python >= 3.15`), and `check-image-lock-reconciliation.py` kept
only the last line per name — so any image on Python <= 3.14 (all of them)
would have been red-flagged as a version skew the moment trivy passed.
`scripts/check-image-lock-reconciliation.py` now records every declared
entry of a forked name and accepts any of them; the three new tests pin the
parse (both entries survive), the acceptance (a 0.22.9 image reconciles),
and the refusal (an undeclared 0.30.0 is still named as a mismatch). No
existing test changed meaning.

## Develop sync (base `ffc27cc43`): two of the three fork tests superseded — delta now `tests/: +1`

The next develop sync brought `issue-5-reconcile-multi-conditional-pins.md`
(`tests/: +2`): develop landed an independent fix of the same forked-pin
defect from the #5 CI-repair round, with its own accept/reject pair. The
sync merge on `tests/test_check_image_lock_reconciliation.py` (the only
conflicted file) was resolved per the `1838-image-lock-reconciliation`
precedent — develop's canonical block verbatim, this branch's superseded
tests removed rather than doubled:

- `test_parse_expected_keeps_every_entry_of_a_forked_conditional_name`
  **stays** (counted by this note): its fixture keeps a required pin
  (`fastapi==0.142.2`) beside the forked name, which develop's all-split
  `SPLIT_EXPORT` fixture does not cover.
- `test_forked_conditional_pin_accepts_any_declared_version` — superseded
  byte-for-byte by develop's
  `test_conditional_pin_with_multiple_marker_versions_accepts_either_branch`
  (same fixture, same assertions). Still reviewable at `54f579117`.
- `test_forked_conditional_pin_rejects_an_undeclared_version` — superseded
  by develop's
  `test_conditional_pin_with_multiple_marker_versions_still_names_an_unknown_branch`,
  which additionally pins the full `one of a, b (a or b)` mismatch clause
  and the absence of a confusing missing/extra pair. Still reviewable at
  `54f579117`.

35 gate tests pass at the merged head; this note's `tests/` delta drops
from +3 to +1 (the surviving parse test). The hive-backend `+8` is
untouched by the sync.

## Develop sync (base `f956a8142`): twin split-resolution fixes reconciled

develop's 1182 lane (its note `1182-image-lock-split-resolution.md`,
`tests/: +5`) landed the same `parse_expected` fix independently, so the
sync merge `64256fabc` resolved the overlapping gate in place: the script
took develop's canonical implementation (per-name version sets for
unconditional and conditional pins alike, `_expected_clause` rendering a
multi-candidate mismatch as `one of a, b`) — a functional superset of this
branch's version — and this round's three tests stay beside develop's five,
with the undeclared-version assertion re-pointed at the `one of ...` clause
form. 35 gate tests pass at the merged head; no test was added, removed or
renamed by the sync itself, so this note's delta is unchanged (develop's
`+5` rides on its own note). `uv.lock` and both frontend package-locks
auto-merged; `uv lock --check` passes and the merged canvas lock is
byte-identical to both parents.
