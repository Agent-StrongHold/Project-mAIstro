# 154 — one SSRF validator

Consolidating the two SSRF implementations onto one (#154) nets +10 maistro-core
node IDs, and the shape of that number matters more than its size. The guard's
own suite gains cases for the obfuscated spellings, the http(s) whitelist, an
unparseable URL, a host that resolves to nothing, the unspecified address, and
the async form agreeing with the sync one. `test_marketplace.py` loses the unit
tests of the deleted duplicate's internals — that coverage did not vanish, it
moved to `tests/security/test_ssrf.py`, which covers strictly more. Three
assertions were **inverted** rather than deleted: they pinned the old fail-open
behaviour on an unresolvable host and on a URL with no parseable hostname.

Nine further root-`tests/` node IDs come with this change rather than from
it: `scripts/check-merge-markers.py` is new, and its suite is the reason the
gate can be trusted at all — the eager direction (a Markdown `=======`
underline, a diff quoted in a document) and the lax direction (the exact
block that reached `develop`) are both pinned. The tenth changed node ID is
not new: `test_guard_call_sites_are_counted_as_calls_not_as_text` stopped
asserting a literal `== 3` against the live tree. Adding the async guard
entry point moved the tree to four call sites and that test failed for
having been right, which is the same unmeasured-number failure the gate it
covers exists to catch. It now asserts the property instead: a call counts,
a mention does not, and `ssrf.py` — which names every guard many times in
prose and calls none of them — scores zero.
