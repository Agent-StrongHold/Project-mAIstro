---
inventory-delta:
  packages/maistro-server/tests: -1
---
# auto-131 develop-sync round 3 (merge of origin/develop, Retry-After CORS)

This merge (6b9dcc469: origin/develop → auto-131, bringing #1592 Retry-After
CORS exposure on the chat refusal 503, #1581 user-model facts, #1471 conductor
session idle policy) is itself drift-neutral: it adds one server test
(`test_a_refusals_retry_after_is_readable_cross_origin`, +1) whose count the
develop side had already recorded by amending its own note
(`claude-ws-1108-refuse-unadmittable-chat-turns-with-a-re-f426.md`, server
+8 → +9). The −1 here settles the pre-existing drift that fixing the ledger
surfaced, so the sum matches what actually collects.

## Where the one node went

The earlier develop-sync unification (a41c7217c / 7fda36aa7, documented in
`auto-131-develop-sync-merge-revalidation.md`) resolved the #1108 conflict by
replacing two superseded auto-131 best-effort endpoint tests
(`*_means_a_null_run_id_and_a_working_endpoint`) with develop's refusal tests —
tests develop's own ledger note already counts. auto-131's original +2 for the
superseded tests (`auto-131-0f5f.md`) stayed in the sum, so after the two
histories united the paper total counted one chat-gate node that no longer
exists as a distinct identity. The note recording that round carried its delta
as unparsable prose (`+0/-0 (rewritten in place: 1)`), which made the whole
ledger unreadable (the check-4 failure of job 18a129c7) rather than merely
off by one; removing that block exposed the arithmetic underneath.

Measured at this head, node-ID sets, not def counts:

- merge base b0fcfcc8a (in both histories): 383 server nodes
- origin/develop tip: 384 (+1 Retry-After)
- auto-131 @ 68018c119: 387 (+1 compensation test, +3 gate tests)
- merged HEAD: 388 — the union; 389 was double-counting the replaced pair.

## Verification

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-server/tests --collect-only -q` → 388 collected.
- `pytest packages/maistro-core/tests/runs/test_chat_admission.py
  packages/maistro-core/tests/test_container_chat_runs.py
  packages/maistro-server/tests/api/test_chat_completions.py
  packages/maistro-server/tests/api/test_chat_completions_gate.py -q`
  → 119 passed (includes develop's new Retry-After test).
