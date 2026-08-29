---
inventory-delta:
  packages/hive-conductor/backend/tests: +11
---
# claude-m1-244-hitl-door-15b0

Nine new tests in `packages/hive-conductor/backend/tests/test_hitl_door.py`
for the HITL entry point (#244), driven over HTTP against the app's real
durable store rather than a mock — the issue asks for the answer to be
asserted end to end, and a mocked store proves only that the route called the
method the test told it to. Purely additive.

- pending human work is discoverable without knowing a run_id, and the listing
  carries the node's own question rather than only the fact of being blocked;
- a machine wait is not offered to a human, keeping the executor's
  `_is_human_pause` distinction at the door;
- answering resumes the Run and the answer is on the record the next execution
  reads;
- the store's three refusals map to distinct statuses: unknown run 404, a Run
  that is not paused 409, a node not awaiting an answer 409 with its own
  message — one test each;
- a second answer to an already-answered node is refused, decided rather than
  incidental;
- a hostile answer is Warden-scanned and nothing reaches the store;
- the reserved `_pause` key cannot be supplied, so a responder cannot name the
  execution state of the node that was waiting on it.

**Two more, added on rebase.** `scripts/check_enumerations.py` landed on
`develop` after this branch was written, and it correctly rejected the answer
route: a mutating `/v1/` route with no `_PROTECTED_OPS` entry. The route now
carries `dags.write` on both verbs, and these two prove the entry means
something rather than merely satisfying the gate:

- an unscoped principal is refused the answer route. The run it names is real
  and paused, so the 403 is authorization refusing rather than the run being
  absent — which a 404 would have been, and which would have passed while
  proving nothing;
- an unscoped principal is refused the pending queue too. That listing carries
  the payload each node is asking, so leaving the read open while gating the
  write would have exposed what every blocked Run is doing to anyone
  authenticated.

The nine behavioural tests above now run as a principal that holds the scope,
which is why the file's fixture moved from `authed_client` to `admin_client`.
