---
inventory-delta:
  packages/maistro-core/tests: +44
---
# claude-issue-327-idempotent-turn-append-f2bd

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

**+34** in a new `tests/persistence/test_session_turn_idempotence.py`. Eleven
cases parametrized over the in-memory, SQLite and PostgreSQL stores (33), plus
four that are not parametrized because they are about a specific engine: AC-7
forces a batch to fail partway, which needs a column type that can reject a
value, and AC-8 asserts what the *database* refuses when a writer skips the
store's guard — the whole reason the marker is a key rather than a `SELECT`.

The in-memory store is a parametrization rather than left out as "just a
double". Most of the suite runs against it, so a double that cannot reproduce a
retry is a double that hides one.

**+5** in `tests/agents/test_base.py` and **+2** in `tests/runs/test_chat_execution.py`,
which are AC-9's two halves. The container half asserts the dispatch carries the
Run's own id and that two Attempts under one Run name the same turn; the agent
half drives `handle()` twice against a *real* `InMemorySessionStore` rather than
the module's fake, because a fake that records `turn_id` proves it was passed and
not that passing it changes anything — which is the claim.

Two of the seven are guards on the other five rather than new behaviour:
`test_two_turns_of_one_session_both_land` fails a store that drops every append
after the first, which would otherwise satisfy the retry test; and
`test_an_identified_append_does_not_disturb_the_sequence` pins that a marker
written beside the messages does not perturb the ordering #327's other half
exists to protect.

**+3** answering two Codex P1 findings, one per fix plus a guard.
`test_purge_expired_deletes_both_tables_in_one_transaction` pins that the sweep
is one transaction, because the state between its two DELETEs -- messages gone,
marker committed -- silently suppresses the next retry of that turn.
`test_the_session_store_does_not_share_its_connection` pins that the SQLite
store owns the connection its transaction spans, and
`test_the_session_store_still_writes_and_reads_on_its_own_connection` guards it:
a connection nobody can use would satisfy "not shared" and be useless.

No test was removed. Four assertions in `tests/persistence/test_pg_sessions.py`
changed from `len(purge_calls) == 1` to naming both tables the sweep deletes
from, in order: the retention sweep now expires a turn's marker with the
messages it admitted, and a marker outliving them would suppress a turn that no
longer exists.
