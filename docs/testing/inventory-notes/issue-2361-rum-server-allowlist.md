---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# issue-2361-rum-server-allowlist

CI-repair round for the #2273 delete slice (#2361) at head c07c44336e. Two
red gates, two root causes, one of them mis-diagnosed by the previous round.

## Gate 1: hive-conductor-e2e-ui (and integration-scope behind it)

`rum-telemetry.spec.ts:375` ("the collector stored the observations and
groups them by build and route") failed deterministically in the full
compose suite: attempt 1 at the `toContainEqual` correlation (line 411), the
retry at the `emitted.some(api_request && request_id)` precondition
(line 409, after a worker restart re-ran `beforeAll` and drained `captured`).

Root cause — server-side allowlist drift. The slice added `capabilities` to
the browser normalizers' `PAGE_ROUTE_ROOTS` (`frontend/src/lib/rumSchema.ts`)
but not to the collector's second boundary, `PAGE_ROUTE_ROOTS` in
`backend/services/rum_store.py`. Every live `/capabilities` page-load batch
therefore carried a `web_vital` route the server's pydantic validator
refused, and `POST /v1/rum/events` answered **422 for the whole batch** —
visible verbatim in the hive container log at the exact flush timestamps.
Nothing from that page ever stored, so the correlation assertions had no
receipts to read back. The previous round's note
(`issue-2361-capabilities-rum-route-root.md`, "Known residual") recorded this
same 2/2 failure as a pre-existing persist-vs-limit race at base; that
diagnosis is superseded by this one — at base the page-load test targeted
`/agents`, whose root the server list already carried, so the 422 (and the
failure) did not exist before this slice.

Fix: one literal, `"capabilities"`, added to the server
`PAGE_ROUTE_ROOTS` — mirroring the client list the slice already extended.
Proven by execution: the exact CI command
(`docker compose -f docker-compose.test.yml --profile test up --build
--abort-on-container-exit --exit-code-from e2e-tests e2e-tests`) now exits 0
with 246 passed / 1 environmental flaky that passes on retry.

The count that moved: `test_route_root_allowlists_match_the_frontend_contract`
in `backend/tests/test_rum_routes.py` (+1 node). The existing contract test
already pinned `MAX_BATCH_EVENTS` and `RUM_SCHEMA` across the two languages;
route roots were the unpinned half of the same contract, which is exactly the
seam that drifted. The new test parses both literals and demands set
equality, plus a positive assertion that `capabilities` is a reviewed root on
the server side. Verified against the regression it names: run against the
base revision's `rum_store.py` and the current `rumSchema.ts`, the same parse
reports exactly `['capabilities']` as the drift and fails.

## Gate 2: Quality / Acceptance state (and the Quality gate behind it)

`check-ac-state.py --run-tests --ratchet --mandate <base>` exited 1 on:

```
FAIL: authorized floor(s) independent landings have superseded
  - design_coverage: 3 note(s) already clear it on their own:
      auto-1084.json, auto-62.json, auto-80.json
```

The `ac-state.design_coverage@39.641` grant (#166, landed bcd7acb7,
2026-10-25) lowers the folded floor to a value measured before three
independent, later-landing notes pushed measured coverage back above it
(39.8418 on 2026-10-26, 44.4608 on 2026-11-16, 39.6633 on 2026-11-18 — three
distinct landing commits, each later than the grant's, each independently
above the floor). The gate treats such a grant as spent and refuses every
candidate whose tree still carries it; the pruning run is the designed
maintenance path (`check_ac_state_impl.py` computes `superseded_by_present`
from the candidate's own file and reports it as the prune order). The row is
pruned; nothing is loosened — the floor disappears, and every comparison it
took part in gets stricter. Both mandate halves already passed
("every criterion this change declares is proven", "adds no absent links").
Re-run with CI's exact arguments after the prune: exit 0, ratchet OK, both
mandates OK.

No suite count moved for the prune; the +1 above is the only delta.
