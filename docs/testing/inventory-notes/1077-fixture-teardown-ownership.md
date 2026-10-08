# 1077 fixture teardown ownership

No suite count moved: zero test items were added or removed. What changed is
the teardown ownership of the parametrized fixtures in
`packages/maistro-core/tests/events/test_durable_store_conformance.py`
(#1077), and that is invisible to a node-ID count — all 86 collected items in
that file (43 skipped without a PostgreSQL URL) collect and pass exactly as
before, and the `durable-events` suite totals are unchanged.

The fixtures (`event_log`, `trigger_store`, `invocations`, `cursor_store`)
used to `return` live stores holding an open `aiosqlite` connection (or an
asyncpg pool on the PostgreSQL leg) with no teardown — one leaked connection
per sqlite-parametrized instantiation, 43 per run of the directory. The
leaks surfaced late, in GC, as `ResourceWarning`s and `Event loop is closed`
callbacks attributed to whichever unrelated test happened to trigger
collection; that is the intermittent teardown noise that failed the `test`
check near suite end on #1040, #1071, #1014, #1019 and #1054's runs.

They are now async-generator fixtures that close what they open in their own
teardown (`try/finally` around setup and yield, so a schema-setup failure or
a raising test body still closes the connection; the PostgreSQL leg closes
its pool the same way). A module-level autouse guard,
`_fail_on_leaked_aiosqlite_connections`, monkeypatches `aiosqlite.connect`
to track every connection the module creates and — because it is set up
before the store fixtures — tears down after all of them, asserting each
connection is fully closed (handle released, background thread stopped)
while the test's event loop is still alive. A regression that returns an
open connection from any of the four fixtures fails deterministically at
that fixture's boundary instead of intermittently in CI teardown.
