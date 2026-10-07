---
inventory-delta:
  tests/: +19
---
# Model-egress ratchet measures physical call-site egress (#1089)

`tests/test_check_model_egress.py` grows from 17 to 36 node IDs. The gate they
test changed its measurement (metric v2): `scripts/check-model-egress.py` no
longer classifies a module from endpoint-shaped text plus any `.post` call in
the same file, but from physical model HTTP at the call site — an effect-method
call whose own URL argument carries a completions-family endpoint fragment,
reusing the curated direct-effect census, plus the exact triples the census
records for `_post`-seam callers. Fourteen of the new cases pin that precision:
the shipped `maistro_server.api.chat_completions` route (the v1 false positive
the issue names) and its minimal fixture classify as no egress; bound-constant,
f-string, and streamed URL posts still count; a finding names its qualname,
line, and callee. The rest pin the new reachability join — the approved
Provider boundary is recognized as the terminal boundary and cannot authorize
a new caller, reviewed-unreachable callers classify separately from shipped
escapes, a missing or malformed reachability baseline fails closed, a stale
ledger row fails the gate end to end, and `--report` emits machine-readable
per-caller evidence. Two adjacent coverage suites (`test_m1_542_policy_
coverage.py`, `test_m1_542_diff_coverage_edges.py`) had their `discover`
stubs renamed to `discover_sites` with identical shapes; no node ID was
removed or renamed in them, and no existing assertion was weakened.
