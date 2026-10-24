---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
  tests/: +3
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
