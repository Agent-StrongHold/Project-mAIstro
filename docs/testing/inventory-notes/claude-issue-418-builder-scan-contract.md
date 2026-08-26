---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
---
# claude-issue-418-builder-scan-contract

Ten new node IDs, all in `packages/hive-conductor/backend/tests/test_agents_routes.py`:
six in `TestTheScanActuallyScans`, four in `TestTheScanIsBounded`. Nothing removed
or reparametrised — the two existing `/scan` cases still pass, because the agent
they build is clean and a real scan agrees with a fake one about a clean config.

## The 404 was the smaller half

#418 was filed as "the Builder posts to a route that does not exist", found by the
verb check in #295's gate. Reading the backend to add that route turned up the
larger problem:

```python
@router.post("/{agent_id}/scan")
def scan_agent(agent_id: str) -> dict:
    return {"findings": [], "status": "clean"}
```

The route that *did* exist scanned nothing. So the two surfaces failed in opposite
directions and the worse one was the one that worked: a 404 at least toasts "Scan
failed", while a hardcoded clean renders the green panel with a checkmark.

`TestTheScanActuallyScans` is written against that: every case in it passes on the
old implementation only if the config is genuinely clean. `test_a_saved_agent_carrying_an_injection_is_reported`
is the direct one — it builds an agent whose description is a prompt injection and
asserts the by-id route flags it, which the constant-return version cannot do.

`test_both_routes_agree_on_the_same_config` exists because two scan surfaces that
can disagree are one too many: a Builder that clears a config the saved-agent scan
later flags is a worse failure than either route being wrong alone. Both now call
`scan_config`, so the test pins the sharing rather than the answer.

## `test_the_literal_route_wins_over_the_id_parameter`

`/v1/agents/scan` and `/v1/agents/{agent_id}` are both one segment, and a path
parameter accepts any single segment. That is exactly how #418 hid for as long as
it did: the first version of `check-frontend-api-routes.py` compared paths only and
read the two as the same route. Only comparing the verb exposed it.

The test stores an agent whose id is literally `scan` and asserts the config
scanner answers, so the registration order is pinned rather than left to whichever
decorator happens to come first in the file.

## `TestTheScanIsBounded`

A proposed configuration is caller-supplied and arbitrarily shaped, and this walk
is the only thing between it and unbounded work: a body nested a few thousand
levels deep is a stack overflow, and a hundred thousand short strings is a hundred
thousand Warden scans.

Every limit rejects with 413 rather than truncating.
`test_a_rejection_is_not_a_clean_result` is the one that matters — had the budget
check returned an empty findings list instead of raising, every oversized config
would render green in the Builder, which is the exact failure the issue exists to
remove.

## What the frontend change is proven by

There is no unit test framework under `frontend/` — no vitest, no jsdom — so the
contract there is held by the type system and the two gates. `bScan` became a
discriminated union (`{ok: true, findings}` / `{ok: false, error}` / `null`), so
reading a failed scan as a findings list does not compile; `tsc --noEmit` is the
check. `scripts/check-frontend-api-routes.py` now covers the line, because the
waiver #299 added is gone.

The stale-green case is worth naming because it was reachable: `bScan` held the
previous run's result through a failed one, so a clean scan followed by a failed
scan left "✓ No issues found" on screen while the toast said "Scan failed". The
handler now clears before the request and records the failure as a failure.
