---
inventory-delta:
  tests/: +6
---
# claude-issue-414-cross-suite-http-leak

Six new node IDs in one new file. Nothing removed; one existing test loses its
`monkeypatch` parameter without changing its assertions.

## What the file is for

`maistro.http` keeps one process-global transport override so tests can run the
real client against a fake network. `set_test_transport()` has no scope: set it
and every later request in the process goes through that transport.

`tests/hive_conductor/test_airtable_cache.py` called it and never restored it,
so a MockTransport answering 200 to every request stayed live for the rest of
the process. Two Conductor tests asserting that an unreachable URL reports
`disconnected` then read it as reachable — and only when the root suite shared
an interpreter with them, which no CI job does. Nothing was red for as long as
the jobs stayed partitioned the way they are.

The tests here are about the leak rather than its symptom. The two Conductor
tests are where it surfaced this time; the next leak surfaces somewhere else.

## `TestTheOverrideIsScoped`

`override_transport` already existed and is the right API — the bare setter was
simply used instead. `test_it_restores_even_when_the_body_raises` is the case a
`try/finally` is for and the one a bare setter loses; nesting is covered because
a scoped override that clobbered its parent would be a different bug wearing
the same fix.

## `TestTheAutouseResetCatchesWhatEscapes`

Two tests that only mean anything as a pair, and deliberately so.
`test_a_bare_setter_does_not_survive_this_test` leaks on purpose;
`test_the_previous_test_did_not_leak_into_this_one` asserts on what it left
behind. Ordering-dependent by design — within a file, declaration order is a
guarantee pytest gives, and it is the only guarantee this needs.

If the autouse fixture in `tests/conftest.py` is ever removed, the first of
those becomes the thing it warns about and the second goes red. That is the
intended failure mode: the fixture is what stops the *next* bare setter, and it
should not be quietly deletable.

`test_an_unreachable_host_is_still_unreachable_here` states the property the
Conductor tests were really asserting, at the layer the leak actually broke —
with no override in force, a request reaches the real transport and fails
rather than being answered 200 by someone else's mock.

## The fixture, and why it was missing

`packages/maistro-core/tests/conftest.py` has carried this exact autouse reset
all along, with a docstring that predicted this failure verbatim: *"a leaked
override would silently route a later test's requests into an unrelated
MockTransport — the kind of cross-test coupling that shows up as an unrelated
failure days later."*

It did. The root `tests/` tree simply never got the fixture. One tree having
the guard and its neighbour not is how a leak this specific survives, so the
fix is in both places: the calling test uses `override_transport`, and the
conftest catches whatever escapes next.

## The CI step

Every existing step runs one tree in its own process, which is what let this
sit. One step now runs the three together — not a substitute for the per-tree
steps, which give the readable failure and the coverage split, but the only
place a suite's dependence on which sibling shared its interpreter can show up
at all.
